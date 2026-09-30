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
from backend.app.gamification.events import MAX_EVENTS_PER_DRIVER, backfill_missing, emit_for_scorecard, event_id
from backend.app.gamification.notifications import UnknownNotification
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


def finalized(store, repo, sid='s1', provenance='live', durations=(90000, 90100), started='2026-01-01T00:00:00+00:00', ended='2026-01-02T00:00:00+00:00'):
    driver = repo.active_profile_id()
    repo.bind_session(sid, driver, provenance)
    laps = [dict(id=f'{sid}-{i}', number=i + 1, complete=True, partial=False, comparable=True,
                 quality=[], refuel=False, duration_ms=d) for i, d in enumerate(durations)]
    store.put('session', (sid, started, ended, 'completed', provenance, '{}', '{}'))
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
    snapshot = counts(store)                            # written in the same transaction as the XP
    assert snapshot[0] == snapshot[1] >= 2              # SESSION_ENDED + first-session achievement
    assert card['evidence']['level_before'] == 1 and card['evidence']['level_after'] >= 1
    assert emit_for_scorecard(store, card) == 0         # idempotent backfill
    assert emit_for_scorecard(store, repo.process_session(session, driver, context)) == 0
    assert backfill_missing(store) == 0
    assert counts(store) == snapshot
    kinds = {r['kind']: r['provenance'] for r in store.query('SELECT kind,provenance FROM career_events')}
    assert {'SESSION_ENDED', 'ACHIEVEMENT_UNLOCKED'} <= set(kinds) and set(kinds.values()) == {'CALCULATED'}


def test_non_live_creates_nothing(career):
    store, repo = career
    session, driver, context = finalized(store, repo, sid='r1', provenance='replay')
    card = repo.process_session(session, driver, context)
    assert card['status'] == 'excluded' and emit_for_scorecard(store, card) == 0
    forged = dict(card, status='eligible', xp_awarded=40)        # even a forged eligible card cannot bypass provenance
    assert emit_for_scorecard(store, forged) == 0
    assert backfill_missing(store) == 0
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
    with pytest.raises(UnknownNotification):
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
    assert db.execute('PRAGMA user_version').fetchone()[0] == 9
    db.close()


def fail_builds(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('event build exploded')
    monkeypatch.setattr(events_mod, 'build_events', boom)


def test_event_build_failure_keeps_xp_and_recovery_backfills_once(career, monkeypatch):
    store, repo = career
    session, driver, context = finalized(store, repo)
    runtime = SimpleNamespace(store=store, feature=lambda key: True)
    proc = CareerProcessor(runtime, repo)
    with monkeypatch.context() as m:                              # crash-between-commit-and-emit equivalent
        fail_builds(m)
        proc._process_session('s1', driver)                       # must not raise, must not roll back XP
    assert repo.dashboard()['profile']['total_xp'] == 40
    assert store.query("SELECT status FROM career_scorecards")[0]['status'] == 'eligible'
    assert counts(store) == (0, 0)
    proc._recover()                                               # recovery scan backfills the lost event set
    n = counts(store)
    assert n[0] == n[1] >= 2
    assert store.query("SELECT COUNT(*) n FROM career_events WHERE kind='SESSION_ENDED'")[0]['n'] == 1
    proc._recover()
    proc._process_session('s1', driver)
    assert counts(store) == n and repo.dashboard()['profile']['total_xp'] == 40


def test_level_up_uses_stored_levels_when_another_session_processed_between(career, monkeypatch):
    store, repo = career
    need = repo.curve.threshold(2)
    store.career_transaction(lambda db: db.execute('UPDATE career_profiles SET total_xp=?', (need - 10,)))
    s1, driver, c1 = finalized(store, repo, 's1', durations=(90000, 90100))
    with monkeypatch.context() as m:
        fail_builds(m)
        card1 = repo.process_session(s1, driver, c1)
    assert (card1['evidence']['level_before'], card1['evidence']['level_after']) == (1, 2)
    s2, _, c2 = finalized(store, repo, 's2', durations=(91000, 91100), started='2026-01-03T00:00:00+00:00', ended='2026-01-04T00:00:00+00:00')
    card2 = repo.process_session(s2, driver, c2)
    assert card2['evidence']['level_before'] == card2['evidence']['level_after'] == 2
    assert repo.dashboard()['profile']['total_xp'] >= need + 30        # current level is now 2 regardless
    assert backfill_missing(store) >= 2
    assert backfill_missing(store) == 0
    ups = store.query("SELECT source_id,evidence FROM career_events WHERE kind='LEVEL_UP'")
    assert [(u['source_id'], json.loads(u['evidence'])['from'], json.loads(u['evidence'])['to']) for u in ups] == [('career:v1:s1:L2', 1, 2)]
    assert counts(store)[0] == counts(store)[1]


def test_pb_set_positive(career):
    store, repo = career
    s1, driver, c1 = finalized(store, repo, 's1', durations=(90000, 90100))
    repo.process_session(s1, driver, c1)
    assert store.query("SELECT COUNT(*) n FROM career_events WHERE kind='PB_SET'")[0]['n'] == 0
    s2, _, c2 = finalized(store, repo, 's2', durations=(89000, 89100), started='2026-01-03T00:00:00+00:00', ended='2026-01-04T00:00:00+00:00')
    repo.process_session(s2, driver, c2)
    pb = store.query("SELECT evidence,provenance FROM career_events WHERE kind='PB_SET'")
    assert len(pb) == 1 and pb[0]['provenance'] == 'CALCULATED'
    evidence = json.loads(pb[0]['evidence'])
    assert evidence['improvement_ms'] == 1000 and evidence['pb_ms'] == 89000 and evidence['session_id'] == 's2'


def test_challenge_completed_positive(career):
    store, repo = career
    s1, driver, c1 = finalized(store, repo, 's1', durations=(90000, 90100, 90200))
    repo.process_session(s1, driver, c1)
    offered = {c['kind']: c for c in repo.challenges()}
    assert 'daily' in offered
    repo.challenge_action(offered['daily']['id'], 'accept')
    store.career_transaction(lambda db: db.execute("UPDATE career_challenges SET accepted_at='2025-12-31T00:00:00+00:00'"))
    s2, _, c2 = finalized(store, repo, 's2', durations=(89000, 89100, 89200), started='2026-01-03T00:00:00+00:00', ended='2026-01-04T00:00:00+00:00')
    repo.process_session(s2, driver, c2)
    done = store.query("SELECT source_id,evidence FROM career_events WHERE kind='CHALLENGE_COMPLETED'")
    assert len(done) == 1 and done[0]['source_id'] == 'career:v1:s2:challenge_daily'
    assert json.loads(done[0]['evidence'])['category'] == 'challenge_daily'
    assert counts(store)[0] == counts(store)[1]


def test_event_retention_bounded_per_driver(career):
    store, repo = career
    driver = repo.active_profile_id()
    def seed(db):
        for i in range(MAX_EVENTS_PER_DRIVER + 10):
            db.execute("INSERT INTO career_events VALUES(?,?,'PB_SET','session',?,'CALCULATED','{}',NULL,?)", (f'old{i:05d}', driver, f'x{i}', f'2025-01-01T00:00:{i // 60:02d}.{i % 60:06d}'))
        db.execute("INSERT INTO career_events VALUES('other','someone-else','PB_SET','session','y','CALCULATED','{}',NULL,'2025-01-01')")
    store.career_transaction(seed)
    session, _, context = finalized(store, repo)
    repo.process_session(session, driver, context)
    n = store.query('SELECT COUNT(*) n FROM career_events WHERE driver_id=?', (driver,))[0]['n']
    assert n == MAX_EVENTS_PER_DRIVER
    assert store.query("SELECT COUNT(*) n FROM career_events WHERE kind='SESSION_ENDED'")[0]['n'] == 1     # newest kept
    assert store.query("SELECT COUNT(*) n FROM career_events WHERE id='other'")[0]['n'] == 1                # other drivers untouched
    assert store.query("SELECT COUNT(*) n FROM career_events WHERE id='old00000'")[0]['n'] == 0


def test_api_limit_validation_read_and_reset(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({'http_port': 18872, 'speech_enabled': False, 'hands_free': False})
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1:8000') as c:
        assert c.post('/api/pair', json={}).status_code == 200
        assert c.get('/api/gamification/notifications?limit=0').status_code == 422
        assert c.get('/api/gamification/notifications?limit=101').status_code == 422
        assert c.get('/api/gamification/notifications?limit=100').json() == []
        assert c.post('/api/gamification/notifications/nope/read').status_code == 404
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
    assert events_mod.KINDS == ('PB_SET', 'LEVEL_UP', 'ACHIEVEMENT_UNLOCKED', 'CHALLENGE_COMPLETED', 'SESSION_ENDED', 'MASTERY_CHANGED')
