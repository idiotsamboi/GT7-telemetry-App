"""Regression tests for issues found in the review of the foundation pass."""
import asyncio
import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.config import Config, Settings
from backend.app.core import commands as cmd
from backend.app.core.commands import audit_target
from backend.app.core.permissions import Principal
from backend.app.diagnostics_report import mask_ips, path_patterns, _scrub
from backend.app.domain.alerts import AlertCenter
from backend.app.storage import Store
from backend.app.storage.audit import AuditSink

BASE = 'http://127.0.0.1:8000'


# ---- audit rows can never poison the recorder's write batch --------------------------------------------------------
def test_audit_target_is_scalar_and_bounded():
    assert audit_target({'target': {'a': 1}, 'id': 'w1'}) == 'w1'           # structured target ignored, falls back to id
    assert audit_target({'target': {'a': 1}}) == ''
    assert audit_target({'target': 'x' * 500}) == 'x' * 100
    assert audit_target({'id': 7}) == '7' and audit_target({'id': True}) == '' and audit_target({}) == ''


def test_a_malformed_audit_row_does_not_roll_back_samples(tmp_path):
    store = Store(tmp_path / 't.db')
    try:
        for i in range(3):
            store.put('sample', ('S', None, float(i), i, json.dumps({'i': i})))
        store.put('audit', ('a1', time.time(), 'local:me', 'x', 'c', {'not': 'storable'}, 'h', 'ok', 'm', None))     # bind error
        store.put('sample', ('S', None, 9.0, 9, json.dumps({'i': 9})))
        store.flush()
        assert store.query('SELECT COUNT(*) n FROM samples')[0]['n'] == 4          # every sample survived
        assert store.error is None and store.health()['failed_other_rows'] == 1     # and the failure is visible, not silent
    finally:
        store.close()


def test_audit_sink_coerces_values_to_storable_scalars(tmp_path):
    store = Store(tmp_path / 't.db')
    try:
        AuditSink(store)({'actor': 'local:me', 'capability': 'c', 'command_id': 'x', 'result_code': 'ok', 'target': {'a': 1},
                          'payload_hash': 5, 'message': None, 'session_id': None, 'utc': '12.5'})
        store.flush()
        rows = store.audit()
        assert len(rows) == 1 and rows[0]['utc'] == 12.5 and rows[0]['target'] == "{'a': 1}"[:200]
    finally:
        store.close()


def test_command_with_structured_target_is_audited_with_empty_target(tmp_path):
    Config(tmp_path).save({'http_port': 18231, 'speech_enabled': False, 'hands_free': False})
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        c.post('/api/pair', json={})
        c.post('/api/commands/raceControl.message', json={'target': {'a': 1}, 'text': 'x', 'scope': 'all'})    # fails validation/state
        time.sleep(.2)
        rows = c.get('/api/audit').json()
        assert any(r['command_id'] == 'raceControl.message' and r['target'] == '' for r in rows)
        assert c.get('/api/services').json()[0]['state'] != 'failed'                 # the recorder is not poisoned


def test_destructive_confirm_must_be_literally_true():
    async def go(value):
        ctx = cmd.Ctx(Principal('local', 'me'))
        return await cmd.dispatch(ctx, 'training.restart', {'layout_id': 'x', 'confirm': value}, limiter=cmd.RateLimiter())
    from backend.app import commands_catalog  # noqa: F401
    assert asyncio.run(go('false')).diagnostic == 'confirm'
    assert asyncio.run(go(1)).diagnostic == 'confirm'


# ---- settings ---------------------------------------------------------------------------------------------------------
def test_settings_update_merges_nested_units_instead_of_replacing(tmp_path):
    Config(tmp_path).save({'http_port': 18232, 'speech_enabled': False, 'hands_free': False, 'units': {'speed': 'mph', 'temperature': 'F'}})
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        c.post('/api/pair', json={})
        assert c.post('/api/commands/settings.update', json={'units': {'fuel': 'gal_us'}}).status_code == 200
        units = c.get('/api/settings').json()['units']
        assert units == {'speed': 'mph', 'temperature': 'F', 'fuel': 'gal_us', 'distance': 'm', 'pressure': 'bar'}


def test_saving_never_persists_a_schema_this_build_cannot_load(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'schema_version': 99})
    assert json.loads((tmp_path / 'settings.json').read_text())['schema_version'] == 2
    assert Config(tmp_path).recovery_notice is None


def test_locked_settings_file_during_migration_keeps_valid_settings(tmp_path, monkeypatch):
    (tmp_path / 'settings.json').write_text(json.dumps({'schema_version': 1, 'reserve_l': 7, 'hands_free': True}))
    import backend.app.config as config_module

    def locked(*a, **k):
        raise PermissionError('file is locked by OneDrive')

    monkeypatch.setattr(config_module, 'backup_before_migration', locked)
    cfg = Config(tmp_path)
    assert cfg.recovery_notice is None and cfg.settings.reserve_l == 7 and cfg.settings.hands_free is True
    assert cfg.migrated_from == 1                                    # migrated in memory; write-back retried on next save


def test_non_ascii_settings_round_trip(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'setup_notes': 'Nürburgring – Nordschleife ✓ 日本'})
    assert Config(tmp_path).settings.setup_notes == 'Nürburgring – Nordschleife ✓ 日本'


def test_invalid_settings_copies_are_rotated(tmp_path):
    for _ in range(8):
        (tmp_path / 'settings.json').write_text('{broken')
        Config(tmp_path)
        time.sleep(.002)
    assert len(list(tmp_path.glob('settings.invalid-*.json'))) == 5


def test_launcher_config_keeps_the_recovery_notice_and_starts_in_safe_mode(tmp_path):
    (tmp_path / 'settings.json').write_text(json.dumps({'schema_version': 99}))
    cfg = Config(tmp_path)                                           # what run.py builds first
    assert cfg.recovery_notice
    with TestClient(create_app(tmp_path, config=cfg), base_url=BASE) as c:
        c.post('/api/pair', json={})
        state = c.get('/api/state').json()
        assert state['safe_mode']['reason'] == 'settings_invalid' and state['recovery_notice']
    assert list(tmp_path.glob('settings.invalid-*.json'))            # the newer-schema file was preserved, not overwritten


# ---- lifespan cleanup --------------------------------------------------------------------------------------------------
def test_failed_startup_releases_lock_store_and_log_file_and_keeps_crash_marker(tmp_path, monkeypatch):
    from backend.app import api as api_module
    Config(tmp_path).save({'http_port': 18233, 'speech_enabled': False})
    (tmp_path / '.running').write_text('crashed earlier')

    async def boom(self):
        raise RuntimeError('service start exploded')

    monkeypatch.setattr(api_module.Runtime, 'start', boom)
    with pytest.raises(RuntimeError, match='exploded'):
        with TestClient(create_app(tmp_path), base_url=BASE):
            pass
    assert (tmp_path / '.running').exists()                          # the crash evidence is not erased by a failed start
    # everything was released: the same data dir and port can be used straight away
    monkeypatch.undo()
    (tmp_path / '.running').unlink()
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        c.post('/api/pair', json={})
        assert c.get('/api/state').json()['safe_mode'] is None
    (tmp_path / 'logs' / 'app.jsonl').unlink()                       # log file is not held open (would raise on Windows)


def test_lock_conflict_does_not_erase_the_running_instances_marker(tmp_path):
    Config(tmp_path).save({'http_port': 18234, 'speech_enabled': False})
    with TestClient(create_app(tmp_path), base_url=BASE):
        assert (tmp_path / '.running').exists()
        with pytest.raises(RuntimeError, match='single-receiver lock'):
            with TestClient(create_app(tmp_path), base_url=BASE):
                pass
        assert (tmp_path / '.running').exists()


def test_stale_logging_teardown_does_not_disable_a_newer_apps_logging(tmp_path):
    import logging
    from backend.app.core.logging_setup import setup_logging, shutdown_logging
    first = setup_logging(tmp_path / 'a', 'INFO')
    second = setup_logging(tmp_path / 'b', 'INFO')
    shutdown_logging(first)                                          # app A shuts down late: must not touch app B's handlers
    logging.getLogger('system').info('still logging')
    for h in logging.getLogger().handlers:
        h.flush()
    assert 'still logging' in (tmp_path / 'b' / 'app.jsonl').read_text()
    shutdown_logging(second)


# ---- diagnostics redaction ------------------------------------------------------------------------------------------------
def test_redaction_handles_windows_path_spellings_case_and_ipv6():
    root = r'C:\Users\Sam\OneDrive\GT7\data'
    patterns = path_patterns([(root, '<data>'), (r'C:\Users\Sam', '<home>')])
    samples = [
        r'C:\Users\Sam\OneDrive\GT7\data\telemetry.sqlite3',
        'C:/Users/Sam/OneDrive/GT7/data/telemetry.sqlite3',
        "OSError: 'C:\\\\Users\\\\Sam\\\\OneDrive\\\\GT7\\\\data\\\\telemetry.sqlite3'",       # repr-doubled backslashes
        r'c:\users\sam\onedrive\gt7\data\telemetry.sqlite3',                                     # different case
    ]
    for text in samples:
        out = _scrub(text, patterns, mask=True)
        assert 'Sam' not in out and 'sam' not in out.lower().replace('sqlite', '') and '<data>' in out, (text, out)
    assert _scrub(r'C:\Users\Sam\Desktop\x.txt', patterns, mask=True).startswith('<home>')
    masked = mask_ips('gw 192.168.1.20 v6 fe80::1ff:fe23:4567:890a lo 127.0.0.1 t 2026-09-30T04:15:37 loop ::1 full 2001:db8:0:0:0:0:0:1')
    assert '192.168.1.x' in masked and '<ipv6>' in masked and '127.0.0.1' in masked and '04:15:37' in masked and '::1' in masked
    assert 'fe80' not in masked and '2001:db8' not in masked and '192.168.1.20' not in masked


# ---- alerts ------------------------------------------------------------------------------------------------------------------
def test_acknowledged_alert_reopens_when_it_fires_again_after_a_quiet_spell():
    now = [1000.0]
    center = AlertCenter(clock=lambda: now[0])
    first = center.raise_alert('telemetry', 'critical', 'Fuel critical', 'a', dedupe_key='fuel_critical')
    center.acknowledge(first.id)
    now[0] += 5
    center.raise_alert('telemetry', 'critical', 'Fuel critical', 'b', dedupe_key='fuel_critical')
    assert center.active() == []                                     # flapping right after acknowledgement stays quiet
    now[0] += 60
    center.raise_alert('telemetry', 'critical', 'Fuel critical', 'c', dedupe_key='fuel_critical')
    assert [a.message for a in center.active()] == ['c'] and center.active()[0].count == 3


# ---- scenario playback -------------------------------------------------------------------------------------------------------
def make_runtime(tmp_path):
    from backend.app.runtime import Runtime
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False})
    store = Store(tmp_path / 't.db')
    return Runtime(cfg, store), store


def test_scenario_frames_mark_source_gaps_like_live_packets(tmp_path):
    from tests.test_runtime_foundation import drive_scenario
    r, store = make_runtime(tmp_path)
    try:
        drive_scenario(r, 'packet_loss_burst')
        assert 'source sequence gap' in r.sessions.quality or r.seq.counts['gaps'] > 0
        assert r.seq.counts['gaps'] > 0
    finally:
        store.close()


def test_scenario_step_ignores_frames_after_a_source_switch(tmp_path):
    from backend.app.telemetry.sources import ScenarioDemo
    r, store = make_runtime(tmp_path)
    try:
        r.source = 'demo'
        r._scenario_iter = ScenarioDemo(seed=0).run('normal_laps')
        r._scenario_t0 = time.monotonic() + .08                      # the step will sleep ~80 ms before delivering the first frame

        async def go():
            async def switch_midway():
                await asyncio.sleep(.01)                             # ...and the source is switched well inside that gap
                r.source_generation += 1                             # what switch() does
                r.source = 'live'
            task = asyncio.create_task(switch_midway())
            await r._scenario_step(time.monotonic())
            await task
        before = r.received
        asyncio.run(go())
        assert r.received == before                                  # the synthetic frame was not injected into the new source
    finally:
        store.close()


def test_scenario_name_prefers_setting_then_cli_override(tmp_path):
    r, store = make_runtime(tmp_path)
    try:
        assert r.scenario_name() == ''
        r.scenario_override = 'normal_laps'
        assert r.scenario_name() == 'normal_laps'
        r.settings.demo_scenario = 'lap_transition'
        assert r.scenario_name() == 'lap_transition'
    finally:
        store.close()
