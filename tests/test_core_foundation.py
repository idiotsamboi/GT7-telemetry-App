"""core/: registry, errors, lifecycle, events, features, permissions, commands, logging, config migrations."""
import asyncio
import json
import logging

import pytest
from pydantic import BaseModel

from backend.app.config import Config, Settings
from backend.app.core import commands as cmd
from backend.app.core import config_migrations as cm
from backend.app.core import features, logging_setup as ls, permissions as perm
from backend.app.core.errors import AppError, HTTP_STATUS, ResultCode
from backend.app.core.events import AppEvent, EventBus
from backend.app.core.lifecycle import BaseService, ServiceRegistry, ServiceState
from backend.app.core.platform import resolve_performance_profile
from backend.app.core.registry import DuplicateRegistration, Registry
from backend.app.core.version import SETTINGS_SCHEMA_VERSION


def run(coro):
    return asyncio.run(coro)


# ---- registry / errors --------------------------------------------------------------------------
def test_registry_rejects_duplicates_and_serialises_without_callables():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Item:
        id: str
        fn: object = None

    reg = Registry('t')
    reg.register(Item('a', print))
    with pytest.raises(DuplicateRegistration):
        reg.register(Item('a'))
    assert reg.get('a').id == 'a' and 'a' in reg and len(reg) == 1
    assert reg.to_public() == [{'id': 'a'}]      # callable stripped
    with pytest.raises(KeyError):
        reg.require('missing')


def test_app_error_carries_status_and_maps_codes():
    error = AppError.from_status(409, 'busy')
    assert (error.status_code, error.detail, error.code) == (409, 'busy', ResultCode.CONFLICT)
    assert AppError.from_code(ResultCode.RATE_LIMITED, 'slow').status_code == 429
    assert AppError.from_status(500, 'x').code == ResultCode.UNAVAILABLE
    detail = {'message': 'x', 'required_sharing': ['a']}      # structured details survive (group 409 case)
    assert AppError.from_status(409, detail).detail is detail
    assert set(HTTP_STATUS) == set(ResultCode)


# ---- lifecycle ---------------------------------------------------------------------------------
class Svc(BaseService):
    def __init__(self, sid, fail=False, log=None):
        super().__init__()
        self.id, self.fail, self.log = sid, fail, log if log is not None else []

    async def _start(self):
        if self.fail:
            raise RuntimeError('boom')
        self.log.append(('start', self.id))

    async def _stop(self):
        self.log.append(('stop', self.id))


def test_lifecycle_orders_by_dependency_and_stops_in_reverse():
    log = []
    reg = ServiceRegistry()
    reg.register(Svc('c', log=log), depends_on=('b',))
    reg.register(Svc('b', log=log), depends_on=('a',))
    reg.register(Svc('a', log=log))
    assert reg.order() == ['a', 'b', 'c']

    async def go():
        await reg.start_all()
        assert {s.id: s.state for s in reg.statuses()} == {'a': 'running', 'b': 'running', 'c': 'running'}
        await reg.stop_all()

    run(go())
    assert log == [('start', 'a'), ('start', 'b'), ('start', 'c'), ('stop', 'c'), ('stop', 'b'), ('stop', 'a')]


def test_one_failed_service_does_not_stop_others_and_dependents_are_marked():
    reg = ServiceRegistry()
    reg.register(Svc('ok'))
    reg.register(Svc('bad', fail=True))
    reg.register(Svc('child'), depends_on=('bad',))
    reg.register(Svc('other'))
    run(reg.start_all())
    states = {s.id: s for s in reg.statuses()}
    assert states['ok'].state == 'running' and states['other'].state == 'running'
    assert states['bad'].state == 'failed' and 'boom' in states['bad'].last_error
    assert states['child'].state == 'failed' and states['child'].error_code == 'dependency_failed'


def test_lifecycle_rejects_cycles_unknown_deps_and_duplicates():
    reg = ServiceRegistry()
    reg.register(Svc('a'), depends_on=('b',))
    reg.register(Svc('b'), depends_on=('a',))
    with pytest.raises(ValueError, match='cycle'):
        reg.order()
    reg2 = ServiceRegistry()
    reg2.register(Svc('x'), depends_on=('nope',))
    with pytest.raises(ValueError, match='unknown'):
        reg2.order()
    with pytest.raises(ValueError, match='duplicate'):
        reg2.register(Svc('x'))


def test_stuck_stop_is_bounded():
    class Stuck(Svc):
        async def _stop(self):
            await asyncio.sleep(30)

    reg = ServiceRegistry(stop_timeout=.05)
    reg.register(Stuck('s'))
    reg.register(Svc('t'))

    async def go():
        await reg.start_all()
        await asyncio.wait_for(reg.stop_all(), 2)

    run(go())


def test_event_bus_isolates_handler_failures():
    bus, seen = EventBus(), []
    bus.subscribe('bad', lambda e: 1 / 0)
    bus.subscribe('good', seen.append)
    bus.emit(AppEvent('lap_completed', {'lap': 3}))
    assert seen[0].data == {'lap': 3} and bus.metrics['handler_errors'] == 1


# ---- features / platform -----------------------------------------------------------------------
def test_feature_flags_use_legacy_storage_and_overrides():
    s = Settings()
    assert features.is_enabled('packet_c_interpretations', s) is False
    assert features.is_enabled('packet_c_interpretations', Settings(trust_c_fields=True)) is True
    assert features.is_enabled('battle_index', s) is True
    assert features.is_enabled('battle_index', Settings(feature_flags={'battle_index': False})) is False
    assert {f['id'] for f in features.snapshot(s)} >= {'v3_track_authority', 'local_ai', 'tyre_heat_rate', 'ui_redesign_shell'}


def test_performance_profile_auto_selection():
    assert resolve_performance_profile('AUTO', cpus=4, memory=16 * 2 ** 30) == 'LOW_POWER'
    assert resolve_performance_profile('AUTO', cpus=16, memory=2 * 2 ** 30) == 'LOW_POWER'
    assert resolve_performance_profile('AUTO', cpus=16, memory=32 * 2 ** 30) == 'DESKTOP'
    assert resolve_performance_profile('DESKTOP', cpus=1, memory=1) == 'DESKTOP'


# ---- permissions / commands --------------------------------------------------------------------
def test_role_capability_matrix():
    driver = perm.Principal('driver', 'd1', 'g1')
    assert perm.can(driver, 'telemetry.publishOwn') and perm.can(driver, 'driver.respond')
    assert not perm.can(driver, 'raceControl.setFlag') and not perm.can(driver, 'telemetry.viewAll')
    assert perm.can(perm.Principal('driver', 'd1', flags={'share_traffic_with_drivers': True}), 'telemetry.viewAll')
    assert not perm.can(perm.Principal('driver', 'd1', status='pending'), 'telemetry.publishOwn')
    assert perm.can(perm.Principal('host'), 'raceControl.setFlag') and perm.can(perm.Principal('local'), 'settings.write')
    assert not perm.can(perm.Principal('local'), 'overlay.read')
    with pytest.raises(KeyError):
        perm.can(driver, 'not.a.capability')


def test_spectator_workspace_scope():
    spec = perm.Principal('spectator', 's1', 'g1')
    mine = {'owner': 's1', 'shared_with': []}
    shared = {'owner': 'x', 'shared_with': ['s1']}
    other = {'owner': 'x', 'shared_with': []}
    assert perm.can(spec, 'graphics.take', mine) and perm.can(spec, 'graphics.edit', shared)
    assert not perm.can(spec, 'graphics.take', other)
    overlay = perm.Principal('overlay', 'o', scope={'workspace_id': 'w1'})
    assert perm.can(overlay, 'overlay.read', {'id': 'w1'}) and not perm.can(overlay, 'overlay.read', {'id': 'w2'})


def _reg():
    class Payload(BaseModel):
        n: int

    calls = []
    reg = Registry('cmds', public=lambda c: {'id': c.id})

    async def handler(ctx, body):
        calls.append(body.n)
        if body.n == 99:
            raise AppError.from_code(ResultCode.CONFLICT, 'nope')
        if body.n == 98:
            raise RuntimeError('bug')
        return cmd.CommandResult(ResultCode.OK, 'done', data={'n': body.n})

    reg.register(cmd.CommandDef('t.do', 'settings.write', Payload, handler, audited=True, rate=(3, 60)))
    reg.register(cmd.CommandDef('t.danger', 'sessions.purge', Payload, handler, destructive=True))
    return reg, calls


def test_dispatcher_validation_capability_rate_audit_and_errors():
    reg, calls = _reg()
    audit = []
    ctx = cmd.Ctx(perm.Principal('local', 'me'), audit=audit.append, session_id='S')
    limiter = cmd.RateLimiter()

    def d(ctxx, cid, payload):
        return run(cmd.dispatch(ctxx, cid, payload, registry=reg, limiter=limiter))

    assert d(ctx, 'nope', {}).code == ResultCode.NOT_FOUND
    assert d(ctx, 't.do', {'n': 'x'}).code == ResultCode.INVALID_INPUT
    ok = d(ctx, 't.do', {'n': 1})
    assert ok.ok and ok.data == {'n': 1} and ok.audit_id == audit[-1]['id']
    assert audit[-1]['command_id'] == 't.do' and audit[-1]['result_code'] == 'ok' and audit[-1]['session_id'] == 'S'
    assert 'n' not in audit[-1]     # payload is hashed, never stored
    assert d(ctx, 't.do', {'n': 99}).code == ResultCode.CONFLICT         # AppError -> result code
    assert d(ctx, 't.do', {'n': 1}).code == ResultCode.RATE_LIMITED      # (3 per 60 s)
    driver = cmd.Ctx(perm.Principal('driver', 'd'))
    assert d(driver, 't.do', {'n': 1}).code == ResultCode.NOT_AUTHORIZED
    assert d(ctx, 't.danger', {'n': 1}).code == ResultCode.INVALID_INPUT   # needs confirm
    assert d(ctx, 't.danger', {'n': 1, 'confirm': True}).ok
    bug = d(ctx, 't.danger', {'n': 98, 'confirm': True})
    assert bug.code == ResultCode.UNAVAILABLE and bug.diagnostic == 'RuntimeError'
    assert cmd.CommandResult(ResultCode.RATE_LIMITED).http_status == 429
    assert calls == [1, 99, 1, 98]      # rejected calls never reached the handler


def test_rate_limiter_window_slides():
    lim = cmd.RateLimiter()
    assert lim.allow(('a', 'b'), 2, 10, now=0) and lim.allow(('a', 'b'), 2, 10, now=1)
    assert not lim.allow(('a', 'b'), 2, 10, now=2)
    assert lim.allow(('a', 'b'), 2, 10, now=11.5)


# ---- logging ---------------------------------------------------------------------------------
def test_redaction_of_secrets():
    text = 'GET /overlay#token=abc123SECRET&x=1 X-Control-Token: s3cr3tvalue Bearer abcdefghijklmnop password=hunter2'
    out = ls.redact_text(text)
    assert 'abc123SECRET' not in out and 's3cr3tvalue' not in out and 'abcdefghijklmnop' not in out and 'hunter2' not in out
    nested = ls.redact({'credential': 'xyz', 'ok': 1, 'inner': {'api_key': 'k', 'name': 'bob'}, 'urls': ['http://h/?token=abcd']})
    assert nested['credential'] == ls.REDACTED and nested['inner']['api_key'] == ls.REDACTED
    assert nested['inner']['name'] == 'bob' and 'abcd' not in json.dumps(nested['urls'])


def test_logging_writes_redacted_jsonl_and_rate_limits_repeats(tmp_path):
    ls.setup_logging(tmp_path / 'logs', 'INFO')
    try:
        log = ls.get_logger('network')
        for _ in range(5):
            ls.log_event('network', logging.ERROR, 'bind_failed', port=1, token='SECRET-VALUE')
        log.info('joined with credential=TOPSECRET')
        for h in logging.getLogger().handlers:
            h.flush()
        lines = [json.loads(x) for x in (tmp_path / 'logs' / 'app.jsonl').read_text().splitlines()]
        errors = [x for x in lines if x['event'] == 'bind_failed']
        assert len(errors) == 1                       # repeats within the window suppressed
        assert errors[0]['sub'] == 'network' and errors[0]['details']['token'] == ls.REDACTED
        assert 'TOPSECRET' not in json.dumps(lines)
        assert ls.ERRORS.ring and ls.ERRORS.ring[0]['event'] == 'bind_failed'
    finally:
        ls.setup_logging(None, 'WARNING')


def test_repeat_filter_reports_suppressed_count():
    now = [0.0]
    f = ls.RepeatFilter(window=60, clock=lambda: now[0])

    def rec():
        return logging.LogRecord('x', logging.ERROR, __file__, 1, 'same', (), None)

    assert f.filter(rec())
    assert not f.filter(rec()) and not f.filter(rec())
    now[0] = 61
    r = rec()
    assert f.filter(r) and r.suppressed == 2


def test_unknown_log_subsystem_rejected():
    with pytest.raises(ValueError):
        ls.get_logger('nonsense')


# ---- config migrations -------------------------------------------------------------------------
V1_SETTINGS = {'schema_version': 1, 'ps5_ip': '192.168.1.20', 'variant': 'B', 'ui_hz': 15, 'hands_free': False}


def test_migration_1_to_2_adds_fields_and_preserves_values():
    raw, applied = cm.migrate(dict(V1_SETTINGS))
    assert applied == [1] and raw['schema_version'] == SETTINGS_SCHEMA_VERSION
    assert raw['units']['speed'] == 'kmh' and raw['performance_profile'] == 'AUTO' and raw['feature_flags'] == {}
    assert raw['ps5_ip'] == '192.168.1.20' and raw['ui_hz'] == 15
    assert cm.migrate(raw) == (raw, [])          # already current: no-op


def test_migration_refuses_newer_and_invalid_versions():
    with pytest.raises(cm.MigrationError):
        cm.migrate({'schema_version': 999})
    with pytest.raises(cm.MigrationError):
        cm.migrate({'schema_version': 'x'})


def test_config_migrates_old_file_with_backup_and_keeps_values(tmp_path):
    (tmp_path / 'settings.json').write_text(json.dumps(V1_SETTINGS))
    cfg = Config(tmp_path)
    assert cfg.migrated_from == 1 and cfg.recovery_notice is None
    assert str(cfg.settings.ps5_ip) == '192.168.1.20' and cfg.settings.variant == 'B' and cfg.settings.units.speed == 'kmh'
    assert json.loads((tmp_path / 'settings.v1.bak.json').read_text())['schema_version'] == 1
    assert json.loads((tmp_path / 'settings.json').read_text())['schema_version'] == SETTINGS_SCHEMA_VERSION


def test_config_keeps_last_three_backups(tmp_path):
    import os
    import time
    for i in range(1, 6):
        p = tmp_path / f'settings.v{i}.bak.json'
        p.write_text('{}')
        os.utime(p, (time.time() + i, time.time() + i))
    (tmp_path / 'settings.json').write_text(json.dumps(V1_SETTINGS))
    cm.backup_before_migration(tmp_path / 'settings.json', 1)
    assert len(list(tmp_path.glob('settings.v*.bak.json'))) == cm.KEEP_BACKUPS


def test_config_newer_or_corrupt_file_falls_back_to_safe_defaults(tmp_path):
    (tmp_path / 'settings.json').write_text(json.dumps({'schema_version': 99}))
    cfg = Config(tmp_path)
    assert cfg.settings.hands_free is False and cfg.recovery_notice and 'preserved' in cfg.recovery_notice
    (tmp_path / 'settings.json').write_text('{not json')
    assert Config(tmp_path).recovery_notice


def test_new_install_writes_current_schema(tmp_path):
    cfg = Config(tmp_path)
    cfg.save(cfg.settings.model_dump())
    assert json.loads((tmp_path / 'settings.json').read_text())['schema_version'] == SETTINGS_SCHEMA_VERSION
    assert cfg.migrated_from is None
