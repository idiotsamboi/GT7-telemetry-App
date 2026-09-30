"""Batch 4a challenge types: F033 session goal, F036 chains, F041 PB boss, F043 find-one-second,
F044 consistency boss, F050 perfect session."""
import json
import sqlite3

import pytest

from backend.app.gamification import challenge_types
from backend.app.gamification.challenges import CHALLENGES_DDL, advance_challenges, transition_challenge
from backend.app.gamification.mastery import MASTERY_DDL
from backend.app.gamification.scoring import evaluate

BASE = [90000 + 100 * i for i in range(10)]          # spread ~0.32% -> grade S, threshold above the floor
TIGHT = [90000, 90010, 90020, 90010, 90000, 90010, 90020, 90010]
NEW_KINDS = {'session_goal', 'chain', 'pb_boss', 'find_one_second', 'consistency_boss', 'perfect_session'}


@pytest.fixture
def db():
    connection = sqlite3.connect(':memory:')
    connection.executescript(CHALLENGES_DDL + MASTERY_DDL)
    connection.execute('CREATE TABLE career_xp_events(id TEXT PRIMARY KEY,guard TEXT UNIQUE,driver_id TEXT,session_id TEXT,source_id TEXT,category TEXT,amount INTEGER,created_at TEXT,evidence TEXT)')
    yield connection
    connection.close()


def session(sid, durations=None, start='2026-09-01T11:00:00+00:00', end='2026-09-01T12:00:00+00:00', provenance='live', spatial=None):
    durations = durations or BASE
    laps = [dict(id=f'{sid}:{i}', number=i + 1, complete=True, partial=False, comparable=True, quality=[], refuel=False, duration_ms=d)
            for i, d in enumerate(durations)]
    summary = dict(id=sid, started=start, ended=end, status='completed', provenance=provenance, laps=laps)
    context = dict(laps={lap['id']: dict(layout_id='layout-a', car_id=123, provenance=provenance, identity_state='locked') for lap in laps},
                   spatial=spatial or {})
    return summary, context


def future(sid, durations=None, spatial=None, start='2026-09-01T12:02:00+00:00', end='2026-09-01T13:00:00+00:00'):
    return session(sid, durations, start, end, spatial=spatial)


def advance(db, data, stamp='2026-09-01T12:00:00+00:00'):
    summary, context = data
    return advance_challenges(db, 'driver', summary['id'], summary, evaluate(summary, context)['evidence'], context, stamp)


def put_mastery(db, pb=90000, laps=10):
    db.execute('INSERT OR REPLACE INTO career_track_mastery VALUES(?,?,?,?,?,?)',
               ('driver', 'layout-a', 123, '2026-09-01T11:00:00+00:00', 'seed',
                json.dumps(dict(layout_id='layout-a', car_id=123, pb_ms=pb, lap_count=laps))))


def put_corners(db):
    for cid, recent in (('c1', [5000, 5100, 5200, 5300]), ('c2', [4000, 4400, 4400, 4400]), ('c3', [6000, 6200, 6200, 6200])):
        db.execute('INSERT OR REPLACE INTO career_corner_mastery VALUES(?,?,?,?,?,?,?)',
                   ('driver', 'layout-a', 123, cid, '2026-09-01T11:00:00+00:00', 'seed',
                    json.dumps(dict(corner_id=cid, name='Turn ' + cid, sample_count=6, recent_segment_ms=recent, consistency=80, confidence=.6, comparison_window_m=50))))


def by_kind(db, kind):
    return [dict(id=r[0], status=r[1], payload=json.loads(r[2]), bucket=r[3]) for r in
            db.execute('SELECT id,status,payload,bucket FROM career_challenges WHERE kind=? ORDER BY bucket', (kind,))]


def accept(db, kind, index=0, stamp='2026-09-01T12:01:00+00:00'):
    item = by_kind(db, kind)[index]
    transition_challenge(db, 'driver', item['id'], 'accept', stamp)
    return item['id']


def rejected(db):
    return {r[0]: r[1] for r in db.execute("SELECT challenge_id,status FROM career_challenge_history WHERE status LIKE 'rejected:%'")}


def xp(db, kind):
    return db.execute('SELECT count(*),coalesce(sum(amount),0) FROM career_xp_events WHERE category=?', ('challenge_' + kind,)).fetchone()


# ------------------------------------------------------------------ gates

def test_gates_reject_with_persisted_reasons_and_no_offers(db):
    advance(db, session('thin', [90000, 90100, 90200]))
    assert not any(by_kind(db, kind) for kind in NEW_KINDS)
    reasons = rejected(db)
    assert reasons['reject:session_goal:thin'] == 'rejected:too_few_samples'
    assert reasons['reject:consistency_boss:thin'] == 'rejected:too_few_samples'
    assert reasons['reject:pb_boss:thin'] == 'rejected:low_confidence'      # 3 laps: confidence below the gate
    advance(db, session('thin', [90000, 90100, 90200]))                            # reprocess: no duplicate rows
    assert len(rejected(db)) == len(reasons)


def test_pb_boss_needs_five_comparable_history_laps(db):
    put_mastery(db, laps=4)
    advance(db, session('base'))
    assert by_kind(db, 'pb_boss') == []
    assert rejected(db)['reject:pb_boss:base'] == 'rejected:too_few_samples'


@pytest.mark.parametrize('provenance', ['replay', 'demo', 'synthetic', 'imported'])
def test_non_live_sources_never_offered_progressed_or_rewarded(db, provenance):
    put_mastery(db)
    assert advance(db, session('nonlive', provenance=provenance)) == 0
    assert db.execute('SELECT count(*) FROM career_challenges').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM career_xp_events').fetchone()[0] == 0


def test_live_progress_ignores_replay_session(db):
    advance(db, session('base'))
    accept(db, 'session_goal')
    assert advance(db, session('rep', provenance='replay', start='2026-09-01T12:02:00+00:00', end='2026-09-01T13:00:00+00:00'), '2026-09-01T13:00:00+00:00') == 0
    assert by_kind(db, 'session_goal')[0]['status'] == 'accepted'


def test_ambiguous_track_rejected(db):
    summary, context = session('amb')
    for lap in context['laps'].values():
        lap['layout_id'] = 'unknown'
    assert advance(db, (summary, context)) == 0
    assert not any(by_kind(db, kind) for kind in NEW_KINDS)


# ------------------------------------------------------------------ F033

def test_session_goal_frozen_completes_once_and_reprocess_is_noop(db):
    advance(db, session('base'))
    goal = by_kind(db, 'session_goal')[0]
    assert goal['payload']['requirements']['target_median_ms'] == pytest.approx(median_target(BASE))
    assert goal['payload']['provenance'] == 'CALCULATED'
    assert goal['payload']['reward_xp'] == 20
    accept(db, 'session_goal')
    slow = future('slow', [91000] * 8)
    assert advance(db, slow, '2026-09-01T13:00:00+00:00') == 0
    assert by_kind(db, 'session_goal')[0]['status'] == 'accepted'
    fast = future('fast', [89500] * 8, start='2026-09-01T13:05:00+00:00', end='2026-09-01T14:00:00+00:00')
    assert advance(db, fast, '2026-09-01T14:00:00+00:00') == 20
    assert advance(db, fast, '2026-09-01T14:00:00+00:00') == 0
    assert xp(db, 'session_goal') == (1, 20)
    assert by_kind(db, 'session_goal')[0]['payload']['requirements']['target_median_ms'] == goal['payload']['requirements']['target_median_ms']
    again = advance(db, session('base'), '2026-09-02T12:00:00+00:00')                 # baseline can not repay itself
    assert again == 0


def median_target(durations):
    ordered = sorted(durations)
    center = (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    return round(center * (1 - challenge_types.SESSION_GOAL_GAIN), 1)


# ------------------------------------------------------------------ F041

def test_pb_boss_frozen_target_and_completion(db):
    put_mastery(db)
    advance(db, session('base'))
    boss = by_kind(db, 'pb_boss')[0]
    assert boss['payload']['requirements']['target_lap_ms'] == 89775.0            # PB - max(100 ms, 0.25%)
    assert boss['payload']['evidence']['history_laps'] == 10
    accept(db, 'pb_boss')
    put_mastery(db, pb=89000)                                                     # PB moves; target stays frozen
    assert advance(db, future('miss', [89800] * 8), '2026-09-01T13:00:00+00:00') == 0
    hit = future('hit', [90000, 89700] + [90000] * 6, start='2026-09-01T13:05:00+00:00', end='2026-09-01T14:00:00+00:00')
    assert advance(db, hit, '2026-09-01T14:00:00+00:00') == 40
    assert advance(db, hit, '2026-09-01T14:00:00+00:00') == 0
    assert xp(db, 'pb_boss') == (1, 40)
    assert by_kind(db, 'pb_boss')[0]['payload']['requirements']['target_lap_ms'] == 89775.0


def test_pb_boss_window_limits_laps(db):
    put_mastery(db)
    advance(db, session('base'))
    accept(db, 'pb_boss')
    late = future('late', [90000] * 10 + [89000, 89000])                          # fast laps only after the window
    assert advance(db, late, '2026-09-01T13:00:00+00:00') == 0


# ------------------------------------------------------------------ F044

def test_consistency_boss(db):
    advance(db, session('base'))
    boss = by_kind(db, 'consistency_boss')[0]
    threshold = boss['payload']['requirements']['max_spread_fraction']
    assert 0.002 <= threshold < 0.0032 and boss['payload']['requirements']['min_laps'] == 8
    accept(db, 'consistency_boss')
    assert advance(db, future('loose', BASE), '2026-09-01T13:00:00+00:00') == 0     # same spread as baseline: not below
    assert advance(db, future('short', TIGHT[:6], start='2026-09-01T13:05:00+00:00', end='2026-09-01T13:30:00+00:00'), '2026-09-01T13:30:00+00:00') == 0
    tight = future('tight', TIGHT, start='2026-09-01T13:35:00+00:00', end='2026-09-01T14:00:00+00:00')
    assert advance(db, tight, '2026-09-01T14:00:00+00:00') == 35
    assert advance(db, tight, '2026-09-01T14:00:00+00:00') == 0
    assert xp(db, 'consistency_boss') == (1, 35)


def test_consistency_boss_rejected_when_already_at_floor(db):
    advance(db, session('flat', TIGHT))
    assert by_kind(db, 'consistency_boss') == []
    assert rejected(db)['reject:consistency_boss:flat'] == 'rejected:low_confidence'


# ------------------------------------------------------------------ F050

def test_perfect_session_is_application_calculated_and_grade_based(db):
    wide = [90000, 91500, 88500, 92000, 89000, 91000, 88800]                      # lower grade baseline
    advance(db, session('base', wide))
    offer = by_kind(db, 'perfect_session')[0]
    grade = offer['payload']['evidence']['baseline_grade']
    target = offer['payload']['requirements']['target_grade']
    assert 'application-calculated' in offer['payload']['title'].lower() and 'incident' in offer['payload']['why']
    assert challenge_types.GRADES.index(target) == min(challenge_types.GRADES.index(grade) + 1, 4)
    accept(db, 'perfect_session')
    assert advance(db, future('bad', wide), '2026-09-01T13:00:00+00:00') == 0
    good = future('good', [90000 + (i % 2) * 20 for i in range(8)], start='2026-09-01T13:05:00+00:00', end='2026-09-01T14:00:00+00:00')
    assert advance(db, good, '2026-09-01T14:00:00+00:00') == 40
    assert advance(db, good, '2026-09-01T14:00:00+00:00') == 0
    assert xp(db, 'perfect_session') == (1, 40)


# ------------------------------------------------------------------ F043

def test_find_one_second_never_exceeds_supported_loss_and_sums_verified_gains(db):
    put_corners(db)
    advance(db, session('base'))
    challenge = by_kind(db, 'find_one_second')[0]
    steps = challenge['payload']['requirements']['steps']
    assert len(steps) == 3 and challenge['payload']['target'] <= 1.0
    for step in steps:
        assert step['gain_s'] <= step['supported_loss_s'] * challenge_types.FIND_SECOND_CAPTURE + 1e-9
        assert step['target_segment_ms'] >= step['best_segment_ms']
    assert challenge['payload']['target'] <= challenge['payload']['evidence']['supported_loss_s']
    assert challenge['payload']['provenance'] == 'CALCULATED'
    accept(db, 'find_one_second')
    targets = {s['corner_id']: s['target_segment_ms'] for s in steps}

    def spatial(sid, corners):
        return {f'{sid}:0': dict(reference_lap_id=f'{sid}:1', source='calculated', layout_id='layout-a', car_id=123,
                                 items=[dict(corner_id=c, segment_ms=targets[c], confidence=.8) for c in corners])}
    first = future('s1', spatial=spatial('s1', ['c2']))
    assert advance(db, first, '2026-09-01T13:00:00+00:00') == 0
    partial = by_kind(db, 'find_one_second')[0]
    assert partial['status'] == 'accepted' and 0 < partial['payload']['progress'] < 100
    assert partial['payload']['current'] == pytest.approx(next(s['gain_s'] for s in steps if s['corner_id'] == 'c2'))
    rest = future('s2', spatial=spatial('s2', ['c1', 'c2', 'c3']), start='2026-09-01T13:05:00+00:00', end='2026-09-01T14:00:00+00:00')
    assert advance(db, rest, '2026-09-01T14:00:00+00:00') == 50
    assert advance(db, rest, '2026-09-01T14:00:00+00:00') == 0
    assert xp(db, 'find_one_second') == (1, 50)
    assert by_kind(db, 'find_one_second')[0]['payload']['progress'] == 100


def test_find_one_second_needs_two_supported_corners(db):
    put_corners(db)
    db.execute("DELETE FROM career_corner_mastery WHERE corner_id IN ('c2','c3')")
    advance(db, session('base'))
    assert by_kind(db, 'find_one_second') == []
    assert rejected(db)['reject:find_one_second:base'] == 'rejected:too_few_samples'


# ------------------------------------------------------------------ F036

def test_chain_orders_steps_and_unlocks_only_on_completion(db):
    put_mastery(db)
    advance(db, session('base'))
    steps = by_kind(db, 'chain')
    assert len(steps) == 1 and steps[0]['payload']['chain']['step'] == 1 and steps[0]['payload']['chain']['length'] == 3
    accept(db, 'chain')
    assert advance(db, future('c1', [90000] * 2), '2026-09-01T13:00:00+00:00') == 0      # only 2 laps: step 1 incomplete
    assert len(by_kind(db, 'chain')) == 1
    done = future('c2', [90000, 90010, 90020], start='2026-09-01T13:05:00+00:00', end='2026-09-01T14:00:00+00:00')
    assert advance(db, done, '2026-09-01T14:00:00+00:00') == 10
    assert advance(db, done, '2026-09-01T14:00:00+00:00') == 0                           # idempotent
    chain = by_kind(db, 'chain')
    assert [c['payload']['chain']['step'] for c in chain] == [1, 2] and [c['status'] for c in chain] == ['completed', 'offered']
    assert chain[1]['payload']['chain']['prerequisite_id'] == chain[0]['id']
    # step 2 is not progressed until accepted
    step2_session = future('c3', [90000, 90010, 90020], start='2026-09-01T14:05:00+00:00', end='2026-09-01T15:00:00+00:00')
    assert advance(db, step2_session, '2026-09-01T15:00:00+00:00') == 0
    assert by_kind(db, 'chain')[1]['status'] == 'offered'
    accept(db, 'chain', 1, '2026-09-01T15:01:00+00:00')
    last = future('c4', [90000, 90010, 90020], start='2026-09-01T15:05:00+00:00', end='2026-09-01T16:00:00+00:00')
    assert advance(db, last, '2026-09-01T16:00:00+00:00') == 20
    chain = by_kind(db, 'chain')
    assert [c['payload']['chain']['step'] for c in chain] == [1, 2, 3]
    assert chain[2]['status'] == 'offered' and chain[2]['payload']['requirements']['evaluator'] == 'pb_beat'
    assert chain[2]['payload']['requirements']['target_lap_ms'] == 89775.0
    assert xp(db, 'chain') == (2, 30)


def test_skipping_a_chain_step_ends_the_chain_without_penalty(db):
    advance(db, session('base'))
    assert by_kind(db, 'chain')[0]['payload']['chain']['length'] == 2                 # no PB history: 2-step chain
    accept(db, 'chain')
    done = future('c2', [90000, 90010, 90020])
    advance(db, done, '2026-09-01T13:00:00+00:00')
    step2 = by_kind(db, 'chain')[1]
    transition_challenge(db, 'driver', step2['id'], 'skip', '2026-09-01T13:01:00+00:00')
    for n in range(3):
        advance(db, future(f'later{n}', [90000, 90010, 90020], start=f'2026-09-0{2 + n}T12:00:00+00:00', end=f'2026-09-0{2 + n}T13:00:00+00:00'),
                f'2026-09-0{2 + n}T13:00:00+00:00')
    assert [c['status'] for c in by_kind(db, 'chain')] == ['completed', 'skipped']
    assert xp(db, 'chain') == (1, 10)


def test_registry_lists_all_new_types():
    assert set(challenge_types.TYPES) == NEW_KINDS
    assert {'session_median', 'pb_beat', 'spread_below', 'session_grade', 'corner_set'} <= set(challenge_types.EVALUATORS)
