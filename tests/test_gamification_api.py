"""F001/F002/F006: paired local API validation and career-only reset."""
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.config import Config


def test_career_api_pairing_profiles_settings_reset_and_export(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({'http_port': 18871, 'speech_enabled': False, 'hands_free': False})
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1:8000') as c:
        assert c.get('/api/gamification/dashboard').status_code == 401
        assert c.post('/api/pair', json={}).status_code == 200
        dashboard = c.get('/api/gamification/dashboard').json()
        assert dashboard['profile']['total_xp'] == 0
        assert len(dashboard['skills']) == 10
        assert all(s['score'] is None for s in dashboard['skills'])
        assert c.post('/api/gamification/profiles', json={'display_name': '   '}).status_code == 422
        second = c.post('/api/gamification/profiles', json={'display_name': 'Test driver'}).json()
        assert c.post('/api/gamification/profiles/' + second['id'] + '/select').status_code == 200
        assert c.get('/api/gamification/profile').json()['id'] == second['id']
        assert c.put('/api/gamification/settings', json={'enabled': 'yes'}).status_code == 422
        assert c.put('/api/gamification/settings', json={'enabled': False}).json()['enabled'] is False
        assert c.get('/api/gamification/xp/history?limit=201').status_code == 422
        assert c.get('/api/gamification/diagnostics').json()['processor']['running'] is True
        bundle = c.get('/api/gamification/export').json()
        assert bundle['provenance'] == 'local_career_export'
        imported = c.post('/api/gamification/import', json={'bundle': bundle})
        assert imported.status_code == 200 and imported.json()['live_rewards_enabled'] is False
        assert c.post('/api/gamification/import', json={'bundle': {'format': 'bad'}}).status_code == 422
        assert c.post('/api/gamification/reset', json={'confirmation': 'yes'}).status_code == 422
        assert c.post('/api/gamification/reset', json={'confirmation': 'RESET CAREER'}).status_code == 200
        assert c.get('/api/sessions').status_code == 200
        assert c.post('/api/gamification/xp', json={'amount': 999}).status_code == 405
