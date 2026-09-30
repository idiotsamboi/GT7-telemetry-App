import json
import sqlite3

import pytest

from backend.app.gamification.challenges import CHALLENGES_DDL, advance_challenges, list_challenges, transition_challenge
from backend.app.gamification.mastery import MASTERY_DDL
from backend.app.gamification.scoring import evaluate


@pytest.fixture
def db():
    connection = sqlite3.connect(':memory:')
    connection.executescript(CHALLENGES_DDL + MASTERY_DDL)
    connection.execute('CREATE TABLE career_xp_events(id TEXT PRIMARY KEY,guard TEXT UNIQUE,driver_id TEXT,session_id TEXT,source_id TEXT,category TEXT,amount INTEGER,created_at TEXT,evidence TEXT)')
    yield connection
    connection.close()


def session(sid, start='2026-09-01T11:00:00+00:00', end='2026-09-01T12:00:00+00:00', count=3, durations=None):
    laps = [dict(id=f'{sid}:{i}', number=i+1, complete=True, partial=False, comparable=True,
                 quality=[], refuel=False, duration_ms=(durations or [90000] * count)[i]) for i in range(count)]
    result = dict(id=sid, started=start, ended=end, status='completed', provenance='live', laps=laps)
    context = dict(laps={lap['id']: dict(layout_id='layout-a', car_id=123, provenance='live', identity_state='locked') for lap in laps})
    return result, context


def advance(db, data, stamp='2026-09-01T12:00:00+00:00', source=None, evidence=None):
    summary, context = data
    return advance_challenges(db, 'driver', source or summary['id'], summary,
                              evidence if evidence is not None else evaluate(summary, context)['evidence'], context, stamp)


def rows(db):
    return {row[1]: dict(id=row[0], status=row[2], payload=json.loads(row[3]))
            for row in db.execute('SELECT id,kind,status,payload FROM career_challenges')}


def offer_and_accept(db, kinds=('daily', 'weekly', 'permanent')):
    assert advance(db, session('baseline')) == 0
    offers = rows(db)
    for kind in kinds:
        transition_challenge(db, 'driver', offers[kind]['id'], 'accept', '2026-09-01T12:01:00+00:00')
    return offers


def future(sid='future', count=3):
    return session(sid, start='2026-09-01T12:02:00+00:00', end='2026-09-01T13:00:00+00:00', count=count)


def test_offers_are_explainable_frozen_and_capped(db):
    baseline = session('baseline', durations=[90000, 91000, 92000])
    assert advance(db, baseline) == 0
    offered = rows(db)
    assert set(offered) == {'daily', 'weekly', 'permanent'}
    weekly = offered['weekly']['payload']
    assert weekly['requirements']['tolerance_pct'] == pytest.approx(.989, abs=.0001)
    assert weekly['why'] and weekly['confidence'] > 0 and weekly['difficulty'] == 'stretch'
    assert weekly['progress'] == 0 and weekly['reward_xp'] > 0
    changed = session('other')
    for evidence in changed[1]['laps'].values(): evidence['layout_id'] = 'layout-b'
    advance(db, changed)
    assert rows(db) == offered
    assert db.execute('SELECT count(*) FROM career_challenge_history').fetchone()[0] == 3


def test_explicit_acceptance_and_only_future_sessions(db):
    advance(db, session('baseline'))
    assert advance(db, future(), stamp='2026-09-01T13:00:00+00:00') == 0
    assert all(row['payload']['progress'] == 0 for row in rows(db).values())
    offered = rows(db)
    for row in offered.values():
        transition_challenge(db, 'driver', row['id'], 'accept', '2026-09-01T13:01:00+00:00')
    # A session that started before acceptance cannot be used after acceptance.
    assert advance(db, future('overlap'), stamp='2026-09-01T13:02:00+00:00') == 0
    assert advance(db, session('baseline'), stamp='2026-09-01T13:02:00+00:00') == 0
    assert all(row['payload']['progress'] == 0 for row in rows(db).values())


def test_completion_idempotency_and_independent_xp_total(db):
    offer_and_accept(db)
    data = future()
    assert advance(db, data, stamp='2026-09-01T13:00:00+00:00') == 60
    state = rows(db)
    assert state['daily']['status'] == state['weekly']['status'] == 'completed'
    assert state['permanent']['payload']['progress'] == 15
    assert advance(db, data, stamp='2026-09-01T13:01:00+00:00') == 0
    assert advance(db, data, stamp='2026-09-01T13:02:00+00:00', source='renamed-source') == 0
    assert rows(db)['permanent']['payload']['progress'] == 15
    assert db.execute('SELECT sum(amount) FROM career_xp_events').fetchone()[0] == 60
    assert db.execute('SELECT count(*) FROM career_xp_events').fetchone()[0] == 2


def test_skip_abandon_and_expiry_are_distinct_terminal_history(db):
    offer_and_accept(db, kinds=('weekly',))
    items = rows(db)
    assert transition_challenge(db, 'driver', items['daily']['id'], 'skip', '2026-09-01T12:02:00+00:00')['status'] == 'skipped'
    assert transition_challenge(db, 'driver', items['weekly']['id'], 'skip', '2026-09-01T12:02:00+00:00')['status'] == 'abandoned'
    with pytest.raises(ValueError):
        transition_challenge(db, 'driver', items['daily']['id'], 'accept', '2026-09-01T12:03:00+00:00')
    advance(db, future(), stamp='2026-09-01T13:00:00+00:00')
    assert len(rows(db)) == 3  # skipped offers cannot be farmed by regeneration
    history = [row[0] for row in db.execute('SELECT status FROM career_challenge_history')]
    assert 'skipped' in history and 'abandoned' in history


def test_expired_challenge_cannot_reward_or_be_accepted(db):
    items = offer_and_accept(db, kinds=('daily',))
    assert advance(db, future(), stamp='2026-09-02T00:00:00+00:00') == 0
    status = db.execute('SELECT status FROM career_challenges WHERE id=?', (items['daily']['id'],)).fetchone()[0]
    assert status == 'expired'
    with pytest.raises(ValueError):
        transition_challenge(db, 'driver', items['daily']['id'], 'accept', '2026-09-02T00:01:00+00:00')


@pytest.mark.parametrize('problem', ['replay', 'demo', 'mixed', 'unknown', 'partial', 'insufficient', 'integrity'])
def test_untrusted_or_insufficient_evidence_never_creates_offers(db, problem):
    data = session('baseline', count=1 if problem == 'insufficient' else 3)
    summary, context = data
    if problem in ('replay', 'demo'): summary['provenance'] = problem
    if problem == 'mixed': context['laps']['baseline:0']['car_id'] = 456
    if problem == 'unknown': context['laps']['baseline:0']['layout_id'] = 'unknown'
    if problem == 'partial':
        for lap in summary['laps']: lap['partial'] = True
    if problem == 'integrity': context['integrity'] = False
    assert advance(db, data) == 0
    assert rows(db) == {}


def test_two_laps_enough_for_career_but_not_challenge_baseline(db):
    data = session('small', count=2)
    assert evaluate(*data)['status'] == 'eligible'
    assert advance(db, data) == 0 and rows(db) == {}


def test_mismatched_context_replay_and_injected_evidence_cannot_advance(db):
    offer_and_accept(db)
    for mutation in ('replay', 'layout', 'car', 'injection'):
        data = future(mutation)
        summary, context = data
        evidence = evaluate(summary, context)['evidence']
        if mutation == 'replay': summary['provenance'] = 'replay'
        if mutation in ('layout', 'car'):
            for item in context['laps'].values(): item['layout_id' if mutation == 'layout' else 'car_id'] = 'layout-b' if mutation == 'layout' else 456
            evidence = evaluate(summary, context)['evidence']
        if mutation == 'injection': evidence['comparable_laps'] = 999
        assert advance(db, data, stamp='2026-09-01T13:00:00+00:00', evidence=evidence) == 0
    assert all(row['payload']['progress'] == 0 for row in rows(db).values())


def test_streak_does_not_bridge_lap_number_gaps(db):
    offer_and_accept(db, kinds=('weekly',))
    data = future()
    data[0]['laps'][1]['number'] = 8
    data[0]['laps'][2]['number'] = 9
    assert advance(db, data, stamp='2026-09-01T13:00:00+00:00') == 0
    assert rows(db)['weekly']['payload']['current'] == 2


def test_permanent_reward_once_and_progress_clamped(db):
    offer_and_accept(db, kinds=('permanent',))
    assert advance(db, future(count=30), stamp='2026-09-01T13:00:00+00:00') == 60
    assert rows(db)['permanent']['payload']['progress'] == 100
    assert advance(db, future('more', count=30), stamp='2026-09-01T13:00:00+00:00') == 0


def test_ownership_actions_and_acceptance_timestamp_are_server_controlled(db):
    offered = offer_and_accept(db, kinds=())
    challenge_id = offered['daily']['id']
    for action in ('award', 'progress', 'complete'):
        with pytest.raises(ValueError): transition_challenge(db, 'driver', challenge_id, action, '2026-09-01T12:02:00+00:00')
    with pytest.raises(ValueError): transition_challenge(db, 'other', challenge_id, 'accept', '2026-09-01T12:02:00+00:00')
    first = transition_challenge(db, 'driver', challenge_id, 'accept', '2026-09-01T12:02:00+00:00')
    again = transition_challenge(db, 'driver', challenge_id, 'accept', '2026-09-01T12:03:00+00:00')
    assert first['accepted_at'] == again['accepted_at']


def test_award_rollback_is_atomic(db):
    offer_and_accept(db)
    db.commit()
    db.execute('SAVEPOINT career_job')
    assert advance(db, future(), stamp='2026-09-01T13:00:00+00:00') == 60
    db.execute('ROLLBACK TO career_job')
    assert db.execute('SELECT count(*) FROM career_xp_events').fetchone()[0] == 0
    assert all(row['payload']['progress'] == 0 for row in rows(db).values())


def test_listing_projects_expiry_without_new_telemetry(db):
    old = session('old', start='2020-01-01T10:00:00+00:00', end='2020-01-01T11:00:00+00:00')
    advance(db, old, stamp='2020-01-01T11:00:00+00:00')

    class ReadStore:
        def query(self, sql, args):
            cursor = db.execute(sql, args)
            return [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]

    listed = {row['kind']: row for row in list_challenges(ReadStore(), 'driver')}
    assert listed['daily']['status'] == listed['weekly']['status'] == 'expired'
    assert listed['permanent']['status'] == 'offered'
    assert list_challenges(ReadStore(), 'another-driver') == []
