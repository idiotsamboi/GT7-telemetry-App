"""P1-EVENTS: progression event log, notification center storage, anti-farming pure functions."""
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.config import Config
from backend.app.gamification import CareerRepository, events as events_mod, processor as processor_mod
from backend.app.gamification.antifarm import combined_factor, duplicate_source, low_information, repeated_identical
from backend.app.gamification.events import emit_for_scorecard, event_id
from backend.app.gamification.notifications import MAX_PER_DRIVER, add_notification
from backend.app.gamification.processor import CareerProcessor
from backend.app.storage import Store


@pytest.fixture
def career(tmp_path):
    store = Store(tmp_path / 'career.db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    yield store, repo
    store.close()


def finalized(store, repo, sid='s1', provenance='live'):
    driver = repo.active_profile_id()
    repo.bind_session(sid, driver, provenance)
    laps = [dict(id=f'{sid}-{i}', complete=True, partial=False, comparable=True,
                 quality=[], refuel=False, duration_ms=90000 + i * 100) for i in range(2)]
    store.put('session', (sid, '2026-01-01', '2026-01-02', 'completed', provenance, '{}', '{}'))
    for lap in laps:
        store.put('lap', (lap['id'], sid, json.dumps(lap)))
        repo.record_lap_context(sid, lap['id'], dict(layout_id='layout-a', car_id=123, provenance=provenance, identity_state='locked'))
    store.flush()
    return store.detail(sid), driver, repo.session_context(sid)


def counts(store):
    return (store.query('SELECT COUNT(*) n FROM career_events')[0]['n'],
            store.query('SELECT COUNT(*) n FROM career_notifications')[0]['n'])


def test_event_id_is_deterministic_and_distinct():
    a = event_id('PB_SET', 'd', 'session', 'x')
    assert a == event_id('PB_SET', 'd', 'session', 'x') and len(a) == 32
    assert a != event_id('LEVEL_UP', 'd', 'session', 'x') and a != event_id('PB_SET', 'e', 'session', 'x')


def test_double_process_is_noop(career):
    store, repo = career
    session, driver, context = finalized(store, repo)
    card = repo.process_session(session, driver, context)
    assert card['status'] == 'eligible'
    first = emit_for_scorecard(store, card, repo.curve)
    assert first >= 2                                   # SESSION_ENDED + first-session achievement
    snapshot = counts(store)
    assert snapshot[0] == snapshot[1] == first
    assert emit_for_scorecard(store, repo.process_session(session, driver, context), repo.curve) == 0
    assert counts(store) == snapshot
    kinds = {r['kind']: r['provenance'] for r in store.query('SELECT kind,provenance FROM career_events')}
    assert {'SESSION_ENDED', 'ACHIEVEMENT_UNLOCKED'} <= set(kinds) and set(kinds.values()) == {'CALCULATED'}


def test_non_live_creates_nothing(career):
    store, repo = career
    session, driver, context = finalized(store, repo, sid='r1', provenance='replay')
    card = repo.process_session(session, driver, context)
    assert card['status'] == 'excluded' and emit_for_scorecard(store, card, repo.curve) == 0
    forged = dict(card, status='eligible', xp_awarded=40)        # even a forged eligible card cannot bypass provenance
    assert emit_for_scorecard(store, forged, repo.curve) == 0
    assert counts(store) == (0, 0)


def test_notifications_bounded_and_ordered(career):
    store, repo = career
    driver = repo.active_profile_id()

    def add(db):
        for i in range(MAX_PER_DRIVER + 5):
            add_notification(db, f'n{i:04d}', driver, 'NORMAL', 't', 'b', f'2026-01-01T00:00:{i // 60:02d}.{i % 60:06d}')
    store.career_transaction(add)
    assert counts(store)[1] == MAX_PER_DRIVER
    ids = [n['id'] for n in repo.notifications(limit=100)]
    assert len(ids) == 100 and ids[0] == f'n{MAX_PER_DRIVER + 4:04d}'
    assert store.query("SELECT COUNT(*) n FROM career_notifications WHERE id='n0000'")[0]['n'] == 0
    with pytest.raises(ValueError):
        store.career_transaction(lambda db: add_notification(db, 'x', driver, 'LOUD', 't', 'b', 'z'))
    read = repo.mark_notification_read(ids[0])
    assert read['read_at'] and repo.mark_notification_read(ids[0])['read_at'] == read['read_at']
    with pytest.raises(ValueError):
        repo.mark_notification_read('missing')


def test_migration_applies_on_v7_database(tmp_path):
    path = tmp_path / 'old.db'
    Store(path).close()
    db = sqlite3.connect(path)
    db.executescript('DROP TABLE career_events; DROP TABLE career_notifications; PRAGMA user_version=7;')
    db.close()
    store = Store(path)
    try:
        assert counts(store) == (0, 0)
    finally:
        store.close()
    db = sqlite3.connect(path)
    assert db.execute('PRAGMA user_version').fetchone()[0] == 8
    db.close()


def test_emit_failure_does_not_raise_from_processor(career, monkeypatch):
    store, repo = career
    session, driver, context = finalized(store, repo)
    runtime = SimpleNamespace(store=store, feature=lambda key: True)
    proc = CareerProcessor(runtime, repo)

    def boom(*args, **kwargs):
        raise RuntimeError('emit exploded')
    monkeypatch.setattr(processor_mod, 'emit_for_scorecard', boom)
    proc._process_session('s1', driver)                          # must not raise
    assert 'emit exploded' in proc.last_error
    assert repo.dashboard()['profile']['total_xp'] == 40        # progression still committed
    monkeypatch.undo()
    proc._process_session('s1', driver)                          # retry writes events exactly once
    n = counts(store)
    assert n[0] == n[1] >= 2
    proc._process_session('s1', driver)
    assert counts(store) == n

    def failing_txn(operation, timeout=10):
        raise RuntimeError('db down')
    store2 = SimpleNamespace(career_transaction=failing_txn)
    assert emit_for_scorecard(store2, {'status': 'eligible', 'driver_id': 'd', 'session_id': 's'}, repo.curve) == 0


def test_api_limit_validation_read_and_reset(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({'http_port': 18872, 'speech_enabled': False, 'hands_free': False})
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1:8000') as c:
        assert c.post('/api/pair', json={}).status_code == 200
        assert c.get('/api/gamification/notifications?limit=0').status_code == 422
        assert c.get('/api/gamification/notifications?limit=101').status_code == 422
        assert c.get('/api/gamification/notifications?limit=100').json() == []
        assert c.post('/api/gamification/notifications/nope/read').status_code == 422
        store = c.app.state.runtime.store
        driver = c.get('/api/gamification/profile').json()['id']
        store.career_transaction(lambda db: add_notification(db, 'n1', driver, 'IMPORTANT', 'Title', 'Body', '2026-01-01T00:00:00'))
        store.career_transaction(lambda db: db.execute("INSERT INTO career_events VALUES('e1',?,'PB_SET','session','s','CALCULATED','{}',NULL,'2026-01-01T00:00:00')", (driver,)))
        listed = c.get('/api/gamification/notifications').json()
        assert [n['id'] for n in listed] == ['n1'] and listed[0]['read_at'] is None
        assert c.post('/api/gamification/notifications/n1/read').json()['read_at']
        assert c.post('/api/gamification/reset', json={'confirmation': 'RESET CAREER'}).status_code == 200
        assert c.get('/api/gamification/notifications').json() == []
        assert counts(store)[0] == 0


def test_antifarm_pure_functions():
    assert duplicate_source(['a', 'b']) == (1.0, 'unique_sources')
    assert duplicate_source([]) == (1.0, 'no_sources')
    factor, reason = duplicate_source(['a', 'a', 'b', 'b'])
    assert factor == 0.5 and reason == 'duplicate_sources:2'
    assert repeated_identical([1, 2, 3, 3, 3], 3) == (0.0, 'identical_last_3')
    assert repeated_identical([1, 2, 3], 5) == (1.0, 'insufficient_history')
    assert repeated_identical([3, 3, 3, 4], 3)[0] == 1.0
    with pytest.raises(ValueError):
        repeated_identical([1], 1)
    assert low_information([90, 91, 92]) == (1.0, 'sufficient_information')
    assert low_information([90, 90, 90, 90]) == (pytest.approx(1 / 3), 'low_information:1/3')
    assert low_information([]) == (0.0, 'no_laps')
    assert low_information([90], 3)[0] == 1.0
    with pytest.raises(ValueError):
        low_information([1], 0)
    factor, reason = combined_factor(duplicate_source(['a', 'a']), low_information([1, 2, 3]))
    assert factor == 0.5 and reason == 'duplicate_sources:1'
    assert combined_factor() == (1.0, 'no_reduction')
    assert events_mod.KINDS == ('PB_SET', 'LEVEL_UP', 'ACHIEVEMENT_UNLOCKED', 'CHALLENGE_COMPLETED', 'SESSION_ENDED')
