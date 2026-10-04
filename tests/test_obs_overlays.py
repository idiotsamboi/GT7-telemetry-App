"""Local OBS overlays: tokenless read-only frame, fixed addresses, global focus, resizing, league-free."""
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.config import Config
from backend.app.group.graphics import GRAPHIC_TEMPLATES

BASE = 'http://127.0.0.1:8000'


def make(tmp_path, port):
    Config(tmp_path).save({'http_port': port, 'speech_enabled': False, 'hands_free': False})
    return TestClient(create_app(tmp_path), base_url=BASE)


def test_every_overlay_has_a_fixed_local_address_and_works_without_a_league(tmp_path):
    with make(tmp_path, 18301) as c:
        # No pairing, no group: the frame endpoint is open and read-only.
        for template in GRAPHIC_TEMPLATES:
            r = c.get('/obs-api/frame', params={'graphic': template.id})
            assert r.status_code == 200, template.id
            body = r.json()
            assert body['mode'] == 'solo'
            assert body['graphic']['width'] == template.width and body['graphic']['height'] == template.height
            assert [e['entry_id'] for e in body['state']['entries']] == ['local']
            assert body['state']['coverage'] == 'local driver only'
        assert c.get('/obs-api/frame', params={'graphic': 'nope'}).status_code == 404
        # Mutations need the paired browser.
        assert c.put('/api/obs/config', json={}).status_code == 401
        c.post('/api/pair', json={})
        listing = c.get('/api/obs').json()
        assert len(listing['overlays']) == len(GRAPHIC_TEMPLATES)
        assert all(o['url'] == f"{BASE}/obs/{o['id']}" for o in listing['overlays'])


def test_focus_applies_to_all_overlays_and_resizing_persists(tmp_path):
    with make(tmp_path, 18302) as c:
        c.post('/api/pair', json={})
        config = c.get('/api/obs').json()['config']
        config['identity'] = {'display_name': 'Sam', 'number': '7', 'team': 'Apex', 'class_name': 'Gr.3'}
        config['focus']['primary'] = 'local'
        config['sizes'] = {'timing': {'width': 600, 'height': 400}}
        saved = c.put('/api/obs/config', json=config)
        assert saved.status_code == 200
        for graphic in ('driver', 'telemetry', 'fuel_status'):
            body = c.get('/obs-api/frame', params={'graphic': graphic}).json()
            assert body['workspace']['slots']['primary'] == 'local'
            assert body['state']['entries'][0]['identity']['display_name'] == 'Sam'
        timing = c.get('/obs-api/frame', params={'graphic': 'timing'}).json()['graphic']
        assert (timing['width'], timing['height']) == (600, 400)
        # Persisted to disk and reloaded by a fresh app.
    with make(tmp_path, 18302) as c2:
        c2.post('/api/pair', json={})
        again = {o['id']: o for o in c2.get('/api/obs').json()['overlays']}
        assert (again['timing']['width'], again['timing']['height']) == (600, 400)
        reset = c2.post('/api/obs/reset').json()
        assert {o['id']: o for o in reset['overlays']}['timing']['width'] == GRAPHIC_TEMPLATES.get('timing').width


def test_invalid_config_is_rejected(tmp_path):
    with make(tmp_path, 18303) as c:
        c.post('/api/pair', json={})
        config = c.get('/api/obs').json()['config']
        assert c.put('/api/obs/config', json={**config, 'sizes': {'nope': {'width': 500, 'height': 200}}}).status_code == 404
        assert c.put('/api/obs/config', json={**config, 'sizes': {'timing': {'width': 5, 'height': 200}}}).status_code == 422


def test_car_image_folder_overrides_bundled_and_falls_back(tmp_path):
    folder = tmp_path / 'pack'
    folder.mkdir()
    (folder / '2159.png').write_bytes(b'USER-IMAGE')
    Config(tmp_path / 'data').save({'http_port': 18304, 'speech_enabled': False, 'hands_free': False, 'image_pack_dir': str(folder)})
    with TestClient(create_app(tmp_path / 'data'), base_url=BASE) as c:
        assert c.get('/cars/2159.png').content == b'USER-IMAGE'
        (folder / 'brands').mkdir()
        (folder / 'brands' / '10.png').write_bytes(b'USER-BRAND')
        assert c.get('/brands/10.png').content == b'USER-BRAND'
        assert c.get('/tracks/1.png').status_code in (200, 404)   # bundled fallback when the frontend is built
        assert c.get('/cars/../secret.png').status_code in (404, 422)
        assert c.get('/cars/not-there.png').status_code == 404
        # /api/pick-folder opens a real OS dialog, so it is not exercised here.
        assert c.post('/api/pick-folder', json={}).status_code == 401
