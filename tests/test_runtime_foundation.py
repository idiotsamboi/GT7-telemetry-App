"""Runtime wiring of the bus, lifecycle events, replay determinism, crash recovery and audio privacy."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from backend.app.config import Config, Settings
from backend.app.runtime import Runtime
from backend.app.storage import Store
from backend.app.telemetry import demo_sample
from backend.app.telemetry.bus import (CONNECTION_CHANGED, LAP_COMPLETED, SESSION_ENDED, SESSION_STARTED,
                                       SOURCE_CHANGED)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / 'tests' / 'fixtures' / 'replay_golden.json'


@pytest.fixture
def runtime(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False, 'ps5_ip': '127.0.0.1'})
    store = Store(tmp_path / 't.db')
    r = Runtime(cfg, store)
    yield r
    store.close()


def feed(r, frames, start=0):
    for i in range(start, start + frames):
        r.consume(demo_sample(i / 60, i))


# ---- bus wiring ------------------------------------------------------------------------------------------
def test_subscribers_are_wired_in_the_original_order(runtime):
    subscribers = list(runtime.bus.metrics_snapshot()['subscribers'])
    assert 'event:driver_career' in subscribers
    order = [name for name in subscribers if not name.startswith('event:')]
    assert order == ['driver_line', 'track_map', 'training', 'track_service', 'live_delta', 'live_analysis',
                     'reception_test', 'sessions', 'coaching', 'rules', 'derived', 'dev_packets']


def test_failing_subscriber_is_isolated_and_counted_as_pipeline_error(runtime, monkeypatch):
    def boom(_sample):
        raise RuntimeError('analysis bug')

    monkeypatch.setattr(runtime.live_analysis, 'consume', boom)
    feed(runtime, 10)
    assert runtime.pipeline_errors == 10 and runtime.received == 10          # later subscribers still ran
    assert runtime.sessions.id and 'application processing failure' in runtime.sessions.quality
    assert runtime.receiver['last_error']['code'] == 'pipeline_exception'
    assert runtime.bus.metrics_snapshot()['subscribers']['live_analysis']['errors'] == 10
    assert runtime.sample is not None and runtime.derived_values.get('speed_kmh') is not None


def test_demo_replay_paths_survive_a_subscriber_failure(runtime, monkeypatch):
    """Before the bus a consumer exception in the demo/replay path propagated out of source_loop."""
    monkeypatch.setattr(runtime.training, 'consume', lambda s: 1 / 0)
    feed(runtime, 5)          # must not raise
    assert runtime.received == 5


def test_lifecycle_events_are_emitted_on_the_bus(runtime):
    seen = []
    runtime.bus.subscribe_events('test', lambda e: seen.append((e.kind, e.data)))
    feed(runtime, 6100)                                     # > 100 s: three laps of the 30 s demo lap
    runtime.sessions.end()
    kinds = [k for k, _ in seen]
    assert kinds.count(SESSION_STARTED) == 1 and kinds.count(SESSION_ENDED) == 1
    assert kinds.count(LAP_COMPLETED) >= 2 and CONNECTION_CHANGED in kinds
    laps = [d['lap'] for k, d in seen if k == LAP_COMPLETED]
    assert all(lap['complete'] for lap in laps) and laps[1]['duration_ms'] == 30000


def test_source_switch_emits_source_changed_and_resets_derived_state(runtime):
    seen = []
    runtime.bus.subscribe_events('src', lambda e: seen.append((e.kind, e.data)), kinds=[SOURCE_CHANGED])
    feed(runtime, 30)
    runtime.switch('demo')
    assert seen == [(SOURCE_CHANGED, {'source': 'demo'})] and runtime.derived_values == {}


def test_snapshot_serves_derived_channels_and_services(runtime):
    feed(runtime, 60)
    snap = runtime.snapshot()
    # derived channels are evaluated at 20 Hz, so they may lag the newest sample by a couple of frames
    assert snap['derived']['speed_kmh'] == pytest.approx(snap['sample']['values']['speed_kmh'], rel=0.02)
    assert snap['services'] == [] and snap['safe_mode'] is None       # services are only built by start()


def test_ui_hz_is_lowered_only_in_low_power_profile(runtime):
    runtime.settings.ui_hz = 15
    runtime.performance_profile = 'DESKTOP'
    assert runtime.effective_ui_hz() == 15
    runtime.performance_profile = 'LOW_POWER'
    assert runtime.effective_ui_hz() == 8
    runtime.settings.ui_hz = 4
    assert runtime.effective_ui_hz() == 4


# ---- replay determinism ------------------------------------------------------------------------------------
def summarize(r):
    laps = [{k: lap[k] for k in ('number', 'duration_ms', 'complete', 'partial', 'comparable', 'timing_source')}
            for lap in r.sessions.report()['laps']]
    return {'laps': laps, 'pace': r.sessions.report()['pace'],
            'events': sorted({e['category'] for e in r.events}),
            'quality': sorted(r.sessions.quality)}


def bus_sequence(r, frames):
    seen = []
    r.bus.subscribe_events('seq', lambda e: seen.append(e.kind))
    feed(r, frames)
    r.sessions.end()
    return seen


def test_replaying_the_same_frames_gives_identical_bus_events_laps_and_report(tmp_path):
    results = []
    for n in range(2):
        cfg = Config(tmp_path / f'r{n}')
        cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False})
        store = Store(tmp_path / f'r{n}' / 't.db')
        r = Runtime(cfg, store)
        sequence = bus_sequence(r, 4000)
        results.append({'events': sequence, **summarize(r)})
        store.close()
    assert results[0] == results[1]
    if not GOLDEN.exists():           # first run writes the golden; afterwards it is a regression fixture
        GOLDEN.write_text(json.dumps(results[0], indent=1, sort_keys=True))
    assert results[0] == json.loads(GOLDEN.read_text())


def test_replay_source_reproduces_the_recorded_laps(tmp_path):
    """Record with the demo source, then feed the stored rows back exactly like `source_loop`'s replay path."""
    from backend.app.telemetry import Sample
    cfg = Config(tmp_path / 'rec')
    cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False})
    store = Store(tmp_path / 'rec' / 't.db')
    live = Runtime(cfg, store)
    feed(live, 3700)
    sid = live.sessions.id
    live.sessions.end()
    store.flush()
    recorded = summarize(live)['laps']
    rows, cursor, record_id = [], -1e30, 0
    while True:
        page = store.samples(sid, cursor, 1000, record_id)
        if not page:
            break
        rows += page
        cursor, record_id = page[-1]['mono'], page[-1]['record_id']
    cfg2 = Config(tmp_path / 'rep')
    cfg2.save({**cfg2.settings.model_dump(), 'speech_enabled': False, 'hands_free': False})
    store2 = Store(tmp_path / 'rep' / 't.db')
    replay = Runtime(cfg2, store2)
    for row in rows:
        replay.consume(Sample(row['values'], row['mono'], row['utc'], row['variant'], 'replay', row['quality']))
    replay.sessions.end()
    assert summarize(replay)['laps'] == recorded and len(rows) == 3700
    assert replay.sessions.provenance == 'replay'
    store.close()
    store2.close()


# ---- recorder crash recovery ---------------------------------------------------------------------------------
def test_recorder_recovers_after_abrupt_kill_with_bounded_loss(tmp_path):
    """Kill the process mid-session (no close, no flush): the unfinished session becomes `interrupted` and at most
    the un-committed tail (queue + one 240-row batch) is lost."""
    script = textwrap.dedent(f'''
        import os, sys, time
        sys.path.insert(0, {str(ROOT)!r})
        from backend.app.config import Config
        from backend.app.storage import Store
        from backend.app.runtime import Runtime
        from backend.app.telemetry import demo_sample
        root = {str(tmp_path / 'crash')!r}
        cfg = Config(root); cfg.save({{**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False}})
        store = Store(root + '/telemetry.sqlite3'); r = Runtime(cfg, store)
        for i in range(3000): r.consume(demo_sample(i / 60, i))
        time.sleep(1.0)                          # let the writer commit what it has
        for i in range(3000, 3200): r.consume(demo_sample(i / 60, i))
        print(r.sessions.id, flush=True)
        os._exit(1)                              # abrupt death: no atexit, no flush
    ''')
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=120)
    sid = result.stdout.strip().splitlines()[-1]
    assert result.returncode == 1 and len(sid) == 32, result.stderr
    store = Store(tmp_path / 'crash' / 'telemetry.sqlite3')
    try:
        detail = store.detail(sid)
        assert detail['status'] == 'interrupted' and detail['ended']
        count = store.query('SELECT COUNT(*) n FROM samples WHERE session=?', (sid,))[0]['n']
        assert 3000 <= count <= 3200, count                       # only the un-committed tail can be lost
        assert 3200 - count <= 240 + 200                           # bounded by one batch plus in-flight window
    finally:
        store.close()


# ---- privacy -----------------------------------------------------------------------------------------------------
def test_no_audio_or_transcript_is_persisted(runtime, tmp_path):
    feed(runtime, 200)
    runtime.command('how much fuel')
    assert runtime.transcript is None                            # retain_transcripts is off by default
    runtime.sessions.end()
    runtime.store.flush()
    stray = [p.name for p in tmp_path.rglob('*') if p.suffix.lower() in ('.wav', '.pcm', '.flac', '.mp3', '.ogg', '.raw')]
    assert stray == []
    rows = runtime.store.query('SELECT payload FROM events')
    assert not any('how much fuel' in r['payload'] and '"transcript"' in r['payload'] for r in rows)


def test_transcript_is_only_kept_when_the_user_opts_in(runtime):
    runtime.settings.retain_transcripts = True
    runtime.command('how much fuel')
    assert runtime.transcript == 'how much fuel'


# ---- scenario-driven demo source ------------------------------------------------------------------------------------
def drive_scenario(r, name, max_items=20000):
    """Run a scenario through the real `_scenario_step` (sequence guard + consume) without waiting in real time."""
    import asyncio
    from backend.app.telemetry.sources import ScenarioDemo
    r.settings.demo_scenario = name
    r.source = 'demo'                                       # `_scenario_step` only runs while the demo source is active
    r._scenario_iter = ScenarioDemo(seed=0).run(name)
    r._scenario_t0 = -1e9                                   # every item is already "due"
    r._scenario_base = None

    async def go():
        for _ in range(max_items):
            before = r.receiver.get('phase')
            await r._scenario_step(0)
            if r.receiver.get('phase') == 'demo_scenario_complete':
                break

    asyncio.run(go())


def test_packet_loss_scenario_goes_through_the_sequence_guard(runtime):
    drive_scenario(runtime, 'packet_loss_burst')
    assert runtime.seq.counts['gaps'] > 0 and runtime.received > 100
    assert runtime.sample.provenance == 'demo'                # always labelled synthetic


def test_out_of_order_scenario_counts_reorders_and_drops_late_packets(runtime):
    drive_scenario(runtime, 'out_of_order')
    assert runtime.seq.counts['reordered'] >= 10 and runtime.received > 100


def test_normal_laps_scenario_produces_laps_deterministically(tmp_path):
    outcomes = []
    for n in range(2):
        cfg = Config(tmp_path / f's{n}')
        cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False})
        store = Store(tmp_path / f's{n}' / 't.db')
        r = Runtime(cfg, store)
        drive_scenario(r, 'normal_laps')
        r.sessions.end()
        outcomes.append(summarize(r)['laps'])
        store.close()
    assert outcomes[0] == outcomes[1] and len([lap for lap in outcomes[0] if lap['complete']]) >= 2


def test_demo_scenario_setting_is_validated_and_migrated(tmp_path):
    from backend.app.config import Settings
    assert Settings(demo_scenario='normal_laps').demo_scenario == 'normal_laps'
    with pytest.raises(ValueError):
        Settings(demo_scenario='does_not_exist')
    from backend.app.core.config_migrations import migrate
    assert migrate({'schema_version': 1})[0]['demo_scenario'] == ''


# ---- feature flags are enforced, not just reported --------------------------------------------------------------------
def test_feature_flags_gate_runtime_behaviour(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False,
              'feature_flags': {'tyre_heat_rate': False, 'spatial_coaching': False, 'clean_air_advice': False}})
    store = Store(tmp_path / 't.db')
    r = Runtime(cfg, store)
    try:
        assert r.feature('tyre_heat_rate') is False and r.feature('battle_index') is True
        feed(r, 300)
        assert r.tyre_heat_result is None and r.spatial_lap is None          # monitors are off, not just hidden
        assert r.clean_air_advice() is None
        r.update_settings({**r.settings.model_dump(), 'feature_flags': {}})
        assert r.feature('tyre_heat_rate') is True
        feed(r, 300, start=300)
        assert r.tyre_heat_result is not None
    finally:
        store.close()


def test_group_flags_are_read_from_the_runtime(tmp_path):
    from types import SimpleNamespace
    from backend.app.group.service import GroupService
    s = GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / 'db.sqlite'), config=SimpleNamespace(root=tmp_path)))
    assert s.flag('battle_index') is True                                     # no settings on the runtime: default on
    s.runtime.settings = Settings(feature_flags={'battle_index': False, 'steward_auto_cues': False})
    assert s.flag('battle_index') is False and s.flag('net_order_projection') is True and s.flag('steward_auto_cues') is False


def test_safe_mode_switches_experimental_behaviour_off_without_touching_saved_settings(tmp_path):
    from backend.app.safe_mode import SafeMode
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False, 'trust_c_fields': True,
              'local_ai_enabled': True})
    store = Store(tmp_path / 't.db')
    r = Runtime(cfg, store)
    try:
        assert r.sessions.settings.trust_c_fields is True and r.rules.settings.trust_c_fields is True
        r.set_safe_mode(SafeMode('forced'))
        assert r.sessions.settings.trust_c_fields is False and r.rules.settings.trust_c_fields is False
        assert r.sessions.settings.model_dump()['local_ai_enabled'] is False
        assert r.settings.trust_c_fields is True and r.settings.local_ai_enabled is True     # the real settings are untouched
        r.update_settings({**r.settings.model_dump(), 'ui_hz': 9})                             # saving in safe mode...
        assert Config(tmp_path).settings.trust_c_fields is True                                 # ...never persists the override
        assert r.sessions.settings.trust_c_fields is False                                      # and the view survives the update
        r.switch('demo')
        assert r.rules.settings.trust_c_fields is False                                         # ...and a source switch
        r.set_safe_mode(None)
        assert r.sessions.settings.trust_c_fields is True and r.rules.settings.trust_c_fields is True
        from backend.app.safe_mode import SafeModeSettings
        with pytest.raises(AttributeError):
            SafeModeSettings(r.settings).trust_c_fields = True                                   # the view is read-only
    finally:
        store.close()
