"""HTTP adapter for the foundation: services, features, capabilities, commands, diagnostics, safe mode."""
import json
import time

from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.config import Config

BASE = 'http://127.0.0.1:8000'


def make(tmp_path, port, **settings):
    Config(tmp_path).save({'http_port': port, 'speech_enabled': False, 'hands_free': False, **settings})
    return TestClient(create_app(tmp_path), base_url=BASE)


def pair(client):
    assert client.post('/api/pair', json={}).status_code == 200


def states(client):
    return {s['id']: s['state'] for s in client.get('/api/services').json()}


def test_services_features_capabilities_and_health(tmp_path):
    with make(tmp_path, 18201) as c:
        pair(c)
        services = states(c)
        assert {'telemetry_receiver', 'recorder', 'engine', 'diagnostics', 'local_ai', 'track', 'microphone',
                'group_host', 'group_client', 'overlay_output'} <= set(services)
        assert services['recorder'] == 'running' and services['telemetry_receiver'] in ('running', 'stopped', 'starting')
        assert services['group_client'] == 'stopped' and services['local_ai'] == 'stopped'
        flags = {f['id']: f for f in c.get('/api/features').json()}
        assert flags['packet_c_interpretations']['enabled'] is False and flags['battle_index']['enabled'] is True
        me = c.get('/api/me/capabilities').json()
        assert 'settings.write' in me['capabilities'] and 'overlay.read' not in me['capabilities']
        health = c.get('/api/health').json()
        assert health['ok'] and health['version']
        assert isinstance(c.get('/api/state').json()['services'], list)


def test_state_snapshot_carries_services_derived_and_no_safe_mode(tmp_path):
    with make(tmp_path, 18202) as c:
        pair(c)
        c.post('/api/control', json={'action': 'demo'})
        time.sleep(.6)
        state = c.get('/api/state').json()
        assert state['safe_mode'] is None
        assert state['derived'].get('speed_kmh') is not None      # served by the registry, not recomputed in the UI
        assert {s['id'] for s in state['services']} >= {'recorder', 'telemetry_receiver'}


def test_channels_endpoint_lists_reported_derived_and_unavailable(tmp_path):
    with make(tmp_path, 18203) as c:
        pair(c)
        channels = {x['id']: x for x in c.get('/api/channels').json()}
        assert channels['speed']['source'] == 'reported' and channels['speed_kmh']['source'] == 'calculated'
        assert channels['tyre_wear']['source'] == 'unavailable' and channels['tyre_wear']['availability']
        assert channels['current_ms']['source'] == 'experimental'
        assert all('accessor' not in x for x in channels.values())


def test_commands_catalogue_dispatch_codes_and_audit(tmp_path):
    with make(tmp_path, 18204) as c:
        pair(c)
        catalogue = {x['id']: x for x in c.get('/api/commands').json()}
        assert {'session.end', 'source.demo', 'engineer.ask', 'settings.update', 'training.restart'} <= set(catalogue)
        assert catalogue['training.restart']['destructive'] and catalogue['session.end']['audited']
        assert c.post('/api/commands/no.such', json={}).status_code == 404
        bad = c.post('/api/commands/session.set_target', json={'target_ms': 'fast'})
        assert bad.status_code == 422 and bad.json()['code'] == 'invalid_input'
        ok = c.post('/api/commands/source.demo', json={})
        assert ok.status_code == 200 and ok.json()['ok'] and ok.json()['command_id']
        time.sleep(.5)
        assert c.get('/api/state').json()['source'] == 'demo'
        ask = c.post('/api/commands/engineer.ask', json={'text': 'how much fuel'}).json()
        assert ask['ok'] and ask['data']['intent'] == 'fuel'
        assert c.post('/api/commands/training.restart', json={'layout_id': 'x'}).status_code == 422   # needs confirm
        ended = c.post('/api/commands/session.end', json={}).json()
        assert ended['ok'] and ended['audit_id']
        rows = c.get('/api/audit').json()
        assert any(r['command_id'] == 'session.end' and r['result_code'] == 'ok' for r in rows)
        assert 'payload' not in rows[0]


def test_settings_update_command_and_route_share_one_implementation(tmp_path):
    with make(tmp_path, 18205) as c:
        pair(c)
        r = c.post('/api/commands/settings.update', json={'ui_hz': 9})
        assert r.status_code == 200 and c.get('/api/settings').json()['ui_hz'] == 9
        assert c.get('/api/settings').json()['schema_version'] == 2
        bad = c.post('/api/commands/settings.update', json={'track_id': 'nope'})
        assert bad.status_code == 422 and 'Unknown GT7 layout' in bad.json()['message']
        put = c.put('/api/settings', json={**c.get('/api/settings').json(), 'ui_hz': 10})
        assert put.status_code == 200 and put.json()['settings']['ui_hz'] == 10


def test_control_shim_maps_app_errors_to_http(tmp_path):
    with make(tmp_path, 18206) as c:
        pair(c)
        assert c.post('/api/control', json={'action': 'nonsense'}).status_code == 400
        assert c.post('/api/control', json={'action': 'replay', 'value': 'missing'}).status_code == 404


def test_read_only_calls_never_change_service_state(tmp_path):
    """Workspace rule: services are backend-owned; navigating the UI (GETs) must not start/stop anything."""
    with make(tmp_path, 18207) as c:
        pair(c)
        before = states(c)
        for path in ('/api/state', '/api/settings', '/api/sessions', '/api/tracks', '/api/track-map', '/api/capabilities',
                     '/api/features', '/api/channels', '/api/diagnostics', '/api/storage', '/api/group/state',
                     '/api/engineer/requests', '/api/audio', '/api/training/progress', '/api/export-formats'):
            assert c.get(path).status_code in (200, 404), path
        assert states(c) == before


def test_diagnostics_bundle_is_redacted(tmp_path):
    with make(tmp_path, 18208, ps5_ip='192.168.77.20') as c:
        pair(c)
        token = (tmp_path / 'control-token').read_text().strip()
        c.post('/api/client-errors', json={'message': f'boom credential={token}', 'component': 'Chart'})
        raw = c.get('/api/diagnostics').json()
        assert raw['versions']['app'] and raw['services'] and 'last_errors' in raw
        bundle = c.post('/api/diagnostics/copy', json={}).json()
        text = json.dumps(bundle)
        assert token not in text
        assert '192.168.77.20' not in text
        assert str(tmp_path) not in text and str(tmp_path).replace('\\', '/') not in text
        assert bundle['redaction']['ips_masked_to_24'] is True
        assert any('boom' in json.dumps(e) for e in bundle['last_errors'])
        opted = json.dumps(c.post('/api/diagnostics/copy', json={'include_ips': True}).json())
        assert token not in opted          # opting in to IPs never reveals secrets


def test_client_errors_are_rate_limited_and_logged_redacted(tmp_path):
    with make(tmp_path, 18209) as c:
        pair(c)
        codes = [c.post('/api/client-errors', json={'message': f'e{i}', 'stack': 'at x?token=SECRETVALUE', 'url': 'http://h/#token=abc'}).status_code
                 for i in range(35)]
        assert codes[:30] == [200] * 30 and 429 in codes[30:]
        log = (tmp_path / 'logs' / 'app.jsonl').read_text()
        assert 'SECRETVALUE' not in log and '"sub": "ui"' in log


def test_export_formats_registry_route(tmp_path):
    with make(tmp_path, 18210) as c:
        pair(c)
        ids = {f['id'] for f in c.get('/api/export-formats').json()}
        assert ids == {'bundle_v1', 'csv', 'jsonl', 'html_report'}
        assert c.get('/api/sessions/nope/export?format=csv').status_code == 404
        assert c.get('/api/sessions/nope/export?format=zip64').status_code == 422


# ---- safe mode --------------------------------------------------------------------------------------------
def test_forced_safe_mode_blocks_heartbeat_mic_and_ai_until_confirmed(tmp_path):
    Config(tmp_path).save({'http_port': 18211, 'speech_enabled': False, 'ps5_ip': '127.0.0.1', 'hands_free': True})
    with TestClient(create_app(tmp_path, safe_mode=True), base_url=BASE) as c:
        pair(c)
        state = c.get('/api/state').json()
        assert state['safe_mode']['active'] and state['safe_mode']['reason'] == 'forced'
        time.sleep(.6)
        assert c.get('/api/state').json()['receiver']['heartbeats'] == 0
        flags = {f['id']: f['enabled'] for f in c.get('/api/features').json()}
        assert flags['local_ai'] is False and flags['packet_c_interpretations'] is False
        left = c.post('/api/commands/safe_mode.leave', json={}).json()
        assert left['ok'] and left['audit_id']
        time.sleep(1.0)
        after = c.get('/api/state').json()
        assert after['safe_mode'] is None and after['receiver']['heartbeats'] >= 1


def test_unclean_shutdown_marker_triggers_safe_mode_and_clean_stop_clears_it(tmp_path):
    Config(tmp_path).save({'http_port': 18212, 'speech_enabled': False})
    (tmp_path / '.running').write_text('crashed')
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        pair(c)
        assert c.get('/api/state').json()['safe_mode']['reason'] == 'unclean_shutdown'
        assert (tmp_path / '.running').exists()
    assert not (tmp_path / '.running').exists()          # clean shutdown removes the marker
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        pair(c)
        assert c.get('/api/state').json()['safe_mode'] is None


def test_crash_detection_can_be_disabled(tmp_path):
    Config(tmp_path).save({'http_port': 18213, 'speech_enabled': False, 'safe_mode_on_crash': False})
    (tmp_path / '.running').write_text('crashed')
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        pair(c)
        assert c.get('/api/state').json()['safe_mode'] is None


def test_invalid_settings_start_in_safe_mode_with_notice(tmp_path):
    (tmp_path / 'settings.json').write_text('{broken')
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        pair(c)
        state = c.get('/api/state').json()
        assert state['safe_mode']['reason'] == 'settings_invalid' and state['recovery_notice']


def test_storage_failure_falls_back_to_safe_database(tmp_path, monkeypatch):
    from backend.app import api as api_module
    real = api_module.Store
    calls = []

    def flaky(path, *a, **k):
        calls.append(path.name)
        if path.name == 'telemetry.sqlite3':
            raise RuntimeError('database disk image is malformed')
        return real(path, *a, **k)

    monkeypatch.setattr(api_module, 'Store', flaky)
    Config(tmp_path).save({'http_port': 18214, 'speech_enabled': False})
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        pair(c)
        state = c.get('/api/state').json()
        assert state['safe_mode']['reason'] == 'storage_failed' and 'malformed' in state['safe_mode']['detail']
    assert calls == ['telemetry.sqlite3', 'telemetry-safe.sqlite3']


def test_startup_writes_structured_log(tmp_path):
    with make(tmp_path, 18215) as c:
        pair(c)
    lines = [json.loads(x) for x in (tmp_path / 'logs' / 'app.jsonl').read_text().splitlines()]
    events = {(x['sub'], x['event']) for x in lines}
    assert ('system', 'startup') in events and ('system', 'shutdown') in events


def test_developer_endpoints_are_hidden_until_developer_mode(tmp_path):
    with make(tmp_path, 18216) as c:
        pair(c)
        assert c.get('/api/dev/packets').status_code == 404 and c.get('/api/dev/scenarios').status_code == 404
        assert c.post('/api/commands/settings.update', json={'developer_mode': True}).status_code == 200
        c.post('/api/control', json={'action': 'demo'})
        time.sleep(.7)
        packets = c.get('/api/dev/packets?n=5').json()
        assert 1 <= len(packets['frames']) <= 5 and packets['frames'][0]['provenance'] == 'demo'
        assert 'speed_kmh' in packets['frames'][0]['values'] and packets['frames'][0]['raw_hex'] is None
        scenarios = c.get('/api/dev/scenarios').json()
        assert {s['id'] for s in scenarios['scenarios']} >= {'normal_laps', 'packet_loss_burst', 'variant_switch_A_to_C'}
        assert c.post('/api/commands/settings.update', json={'developer_mode': False}).status_code == 200
        assert c.get('/api/dev/packets').status_code == 404


def test_dev_frame_ring_stays_empty_and_bounded(tmp_path):
    from backend.app.storage import Store
    from backend.app.runtime import Runtime
    from backend.app.telemetry import demo_sample
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False})
    store = Store(tmp_path / 't.db')
    r = Runtime(cfg, store)
    for i in range(300):
        r.consume(demo_sample(i / 60, i))
    assert len(r.dev_frames) == 0                     # developer mode off: nothing is buffered
    r.settings.developer_mode = True
    for i in range(300, 900):
        r.consume(demo_sample(i / 60, i))
    assert 0 < len(r.dev_frames) <= 50
    store.close()
