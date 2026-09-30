"""F071/F074/F076/F081: missions reuse validated challenges and structured memory."""
from datetime import datetime, timedelta, timezone
import json

from backend.app.gamification.repository import CareerRepository
import backend.app.gamification.repository as repository_module
from backend.app.storage import Store


def record(store, repo, sid, start, end, count=3, offset=0):
    driver = repo.active_profile_id()
    repo.bind_session(sid, driver, 'live')
    store.put('session', (sid, start.isoformat(), end.isoformat(), 'completed', 'live', '{}', '{}'))
    for i in range(count):
        lap = {'id': f'{sid}:{i}', 'number': i+1, 'duration_ms': 90000+i*10+offset, 'comparable': True,
               'complete': True, 'partial': False, 'quality': [], 'refuel': False}
        store.put('lap', (lap['id'], sid, json.dumps(lap)))
        repo.record_lap_context(sid, lap['id'], {'layout_id': 'layout-a', 'car_id': 42, 'provenance': 'live', 'identity_state': 'locked'})
    store.flush()
    return repo.process_session(store.detail(sid), driver, repo.session_context(sid))


def test_mission_completion_relationship_and_memory_are_idempotent(tmp_path, monkeypatch):
    store = Store(tmp_path/'db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    now = datetime.now(timezone.utc)
    try:
        record(store, repo, 'baseline', now-timedelta(hours=2), now-timedelta(hours=1))
        daily = next(c for c in repo.challenges() if c['kind'] == 'permanent')
        repo.start_mission(daily['id'])
        assert repo.engineer()['missions'][0]['status'] == 'accepted'
        monkeypatch.setattr(repository_module, 'now', lambda: (now+timedelta(hours=2)).isoformat())
        result = record(store, repo, 'future', now+timedelta(minutes=1), now+timedelta(hours=1), count=20, offset=20)
        assert result['status'] == 'eligible'
        engineer = repo.engineer()
        assert engineer['xp'] == 25 and engineer['missions'][0]['status'] == 'completed'
        driver = repo.active_profile_id()
        repo.process_session(store.detail('future'), driver, repo.session_context('future'))
        assert repo.engineer()['xp'] == 25
        assert engineer['memory']['last_comparable_session']['source_id']
        repo.clear_memory()
        assert repo.engineer()['memory'] == {}
        assert repo.career()['chapters'][0]['completed'] is True
        assert repo.career()['chapters'][1]['completed'] is True
        assert repo.streaks()[0]['current_count'] == 1
        repo.set_focus('braking')
        assert repo.engineer()['focus'] == 'braking'
        assert 'Only measurable' in repo.engineer()['briefing']['focus_note']
    finally:
        store.close()
