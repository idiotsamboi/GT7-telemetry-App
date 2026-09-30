import json
import sqlite3
import threading
from concurrent.futures import Future

import pytest
from backend.app.storage import Store
from backend.app.gamification import CareerRepository
from backend.app.gamification.scoring import LevelCurve, evaluate, update_skill


@pytest.fixture
def career(tmp_path):
    store = Store(tmp_path / 'career.db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    yield store, repo
    store.close()


def finalized(store, repo, sid='s1', provenance='live', layout='layout-a', car=123):
    driver = repo.active_profile_id()
    repo.bind_session(sid, driver, provenance)
    laps = [dict(id=f'{sid}-{i}', complete=True, partial=False, comparable=True,
                 quality=[], refuel=False, duration_ms=90000+i*100) for i in range(2)]
    store.put('session', (sid, '2026-01-01', '2026-01-02', 'completed', provenance, '{}', '{}'))
    for lap in laps:
        store.put('lap', (lap['id'], sid, json.dumps(lap)))
        repo.record_lap_context(sid, lap['id'], dict(layout_id=layout, car_id=car, provenance=provenance, identity_state='locked'))
    store.flush()
    return store.detail(sid), driver, repo.session_context(sid)


def test_curve_and_evidence_weighting():
    curve = LevelCurve()
    assert curve.threshold(1) == 0 and curve.threshold(2) == 100
    assert curve.progress(99)['current'] == 1
    assert curve.progress(100)['current'] == 2
    assert curve.progress(curve.threshold(100))['next_level_xp'] is None
    assert all(curve.threshold(n) < curve.threshold(n+1) for n in range(1, 100))
    score, confidence, count = update_skill(None, 0, 80, 2)
    assert (score, confidence, count) == (80, .05, 2)
    assert update_skill(100, 100, 0, 2000)[0] > 80
    with pytest.raises(ValueError): LevelCurve(scale=0)
    with pytest.raises(ValueError): update_skill(None, 0, float('nan'), 1)


def test_happy_path_idempotent_atomic_and_unknown_skills(career):
    store, repo = career
    session, driver, context = finalized(store, repo)
    result = repo.process_session(session, driver, context)
    assert result['status'] == 'eligible' and result['xp_awarded'] == 40
    assert repo.process_session(session, driver, context) == result
    dashboard = repo.dashboard()
    assert dashboard['profile']['total_xp'] == 40
    assert dashboard['profile']['eligible_sessions'] == 1
    assert dashboard['profile']['comparable_laps'] == 2
    assert len(dashboard['recent_events']) == 2
    assert {a['definition_id'] for a in dashboard['achievements']} == {'first_comparable_session_v1', 'FIRST_LAP'}
    assert dashboard['skills'][0]['score'] > 99
    assert all(s['score'] is None and s['confidence'] == 0 for s in dashboard['skills'][1:])
    assert repo.pending_sessions() == []


@pytest.mark.parametrize('provenance', ['replay', 'demo', 'import', 'unknown'])
def test_nonlive_analysis_no_reward(career, provenance):
    store, repo = career
    session, driver, context = finalized(store, repo, provenance=provenance)
    # Changing only the CPU work item's claim cannot launder persisted provenance.
    session['provenance'] = 'live'
    result = repo.process_session(session, driver, context)
    assert result['status'] == 'excluded' and result['xp_awarded'] == 0
    assert 'non_live_source' in result['exclusions']
    assert repo.history() == [] and repo.achievements() == []


@pytest.mark.parametrize('change,reason', [
    ('missing_context', 'missing_authoritative_lap_identity'),
    ('mixed_layout', 'mixed_layout_or_car'),
    ('poor_lap', 'insufficient_comparable_laps'),
    ('partial', 'insufficient_comparable_laps'),
    ('unknown_duration', 'insufficient_comparable_laps'),
    ('unknown_car', 'missing_authoritative_lap_identity'),
    ('capture_gap', 'incomplete_capture'),
])
def test_conservative_exclusions(career, change, reason):
    store, repo = career
    session, driver, context = finalized(store, repo)
    key = session['laps'][0]['id']
    if change == 'missing_context': context['laps'].pop(key)
    if change == 'mixed_layout': context['laps'][key]['layout_id'] = 'other'
    if change == 'poor_lap': session['laps'][0]['quality'] = ['telemetry gap']
    if change == 'partial': session['laps'][0]['partial'] = True
    if change == 'unknown_duration': session['laps'][0]['duration_ms'] = None
    if change == 'unknown_car': context['laps'][key]['car_id'] = None
    if change == 'capture_gap': context['integrity'] = False
    result = repo.process_session(session, driver, context)
    assert result['status'] == 'excluded' and reason in result['exclusions']
    assert repo.active_profile()['total_xp'] == 0


def test_profile_attribution_and_immutable_context(career):
    store, repo = career
    session, original, context = finalized(store, repo)
    other = repo.create_profile('Other')
    repo.select_profile(other['id'])
    assert repo.bind_session(session['id'], other['id'], 'live')['driver_id'] == original
    with pytest.raises(ValueError): repo.process_session(session, other['id'], context)
    assert repo.process_session(session, original, context)['xp_awarded'] == 40
    assert repo.dashboard()['profile']['total_xp'] == 0
    assert repo.dashboard(original)['profile']['total_xp'] == 40


def test_rollback_career_savepoint_preserves_neighbor_samples(career):
    store, repo = career
    def broken(db):
        db.execute("UPDATE career_profiles SET total_xp=999")
        raise ValueError('forced failure')
    # Block writer to deterministically place all three jobs in the next batch.
    started = threading.Event(); release = threading.Event()
    blocker = Future()
    store.q.put(('career', (lambda db: (started.set(), release.wait(3)), blocker), 0))
    assert started.wait(2)
    future = Future()
    store.put('sample', ('session', None, 1, 1, '{}'))
    store.q.put(('career', (broken, future), 0))
    store.put('sample', ('session', None, 2, 2, '{}'))
    release.set()
    with pytest.raises(ValueError, match='forced failure'): future.result(5)
    store.flush()
    assert len(store.query('SELECT * FROM samples')) == 2
    assert repo.active_profile()['total_xp'] == 0
    assert store.failed_rows == 0 and store.failed_other == 1


def test_success_not_acknowledged_before_whole_batch_commit(career):
    store, repo = career
    started = threading.Event(); release = threading.Event(); blocker = Future()
    store.q.put(('career', (lambda db: (started.set(), release.wait(3)), blocker), 0))
    assert started.wait(2)
    future = Future()
    store.q.put(('career', (lambda db: db.execute('UPDATE career_profiles SET total_xp=999').rowcount, future), 0))
    store.put('sample', ('session', None, 1, None, '{}'))  # NOT NULL failure after career job
    release.set()
    with pytest.raises(sqlite3.IntegrityError): future.result(5)
    assert repo.active_profile()['total_xp'] == 0


def test_retry_after_failed_reward_transaction(career):
    store, repo = career
    session, driver, context = finalized(store, repo)
    store.career_transaction(lambda db: db.execute("CREATE TRIGGER fail_career BEFORE INSERT ON career_scorecards BEGIN SELECT RAISE(FAIL, 'forced rollback'); END").rowcount)
    with pytest.raises(sqlite3.IntegrityError): repo.process_session(session, driver, context)
    assert repo.history() == [] and repo.active_profile()['total_xp'] == 0
    assert len(repo.pending_sessions()) == 1
    store.career_transaction(lambda db: db.execute('DROP TRIGGER fail_career').rowcount)
    assert repo.process_session(session, driver, context)['xp_awarded'] == 40


def test_reopen_durable_pending_and_completed_idempotency(tmp_path):
    path = tmp_path / 'career.db'
    store = Store(path); repo = CareerRepository(store); repo.ensure_default_profile()
    session, driver, context = finalized(store, repo)
    store.close()
    store = Store(path); repo = CareerRepository(store)
    try:
        assert repo.pending_sessions()[0]['driver_id'] == driver
        assert repo.session_context(session['id']) == context
        repo.process_session(store.detail(session['id']), driver, context)
    finally: store.close()
    store = Store(path); repo = CareerRepository(store)
    try:
        assert repo.pending_sessions() == []
        repo.process_session(store.detail(session['id']), driver, context)
        assert repo.active_profile()['total_xp'] == 40
    finally: store.close()


def test_reset_keeps_guards_and_telemetry(career):
    store, repo = career
    session, driver, context = finalized(store, repo)
    repo.process_session(session, driver, context)
    with pytest.raises(ValueError): repo.reset(driver, 'yes')
    repo.reset(driver, 'RESET CAREER')
    repo.process_session(session, driver, context)
    assert repo.active_profile()['total_xp'] == 0 and repo.history() == []
    assert store.detail(session['id']) is not None


def test_settings_and_unbound_sessions(career):
    store, repo = career
    repo.update_settings({'enabled': False})
    session, driver, context = finalized(store, repo)
    repo.update_settings({'enabled': True})
    assert 'career_disabled_at_start' in repo.process_session(session, driver, context)['exclusions']
    with pytest.raises(ValueError): repo.update_settings({'enabled': 'true'})
    with pytest.raises(ValueError): repo.process_session(dict(session, id='unbound'), driver, context)


def test_bounded_and_missing_data_never_scores_zero():
    session = dict(provenance='live', ended='now', status='completed', laps=[])
    result = evaluate(session, {})
    assert result['evidence']['consistency_score'] is None
    session['laps'] = [dict(comparable=False)] * 2001
    assert 'lap_limit_exceeded' in evaluate(session, {})['exclusions']


def test_cloned_summary_suppression_and_disabled_recheck(career):
    store, repo = career
    session, driver, context = finalized(store, repo)
    assert repo.process_session(session, driver, context)['status'] == 'eligible'
    cloned, driver, cloned_context = finalized(store, repo, sid='cloned')
    result = repo.process_session(cloned, driver, cloned_context)
    assert result['status'] == 'excluded' and 'duplicate_session_evidence' in result['exclusions']
    other, driver, other_context = finalized(store, repo, sid='other', layout='other')
    repo.update_settings({'enabled': False})
    assert 'career_disabled' in repo.process_session(other, driver, other_context)['exclusions']
