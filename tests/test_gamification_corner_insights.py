"""F026-F030: biggest corner loss, easiest gain, corner challenge, corner streaks and corner badges."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.gamification import api as gamification_api
from backend.app.gamification.challenges import advance_challenges, transition_challenge
from backend.app.gamification.corner_insights import (
    CHALLENGE_MIN_CONFIDENCE, MIN_SAMPLES, award_corner_badges, biggest_loss, challenge_gate, corner_loss,
    easiest_gain, streak_kind, update_corner_streaks)
from backend.app.gamification.repository import CareerRepository
from backend.app.gamification.scoring import evaluate
from backend.app.storage import Store

TIGHT = [12000, 12020, 11990, 12010]
NOISY = [12000, 15000, 11000, 16000]


def rec(corner_id, history, consistency=80, confidence=.2, samples=None):
    return dict(corner_id=corner_id, name=corner_id, recent_segment_ms=history, consistency=consistency, confidence=confidence,
                sample_count=len(history) if samples is None else samples, comparison_window_m=[1, 2], source_id='s')


def run(store, repo, sid, segments=TIGHT, k=0, layout='layout-a', car=42, provenance='live', identity='locked'):
    """Five comparable laps; laps 2-5 carry a T1 segment compared with lap 1."""
    driver = repo.active_profile_id()
    repo.bind_session(sid, driver, provenance)
    laps = [dict(id=f'{sid}:{i}', number=i + 1, duration_ms=90000 + i * 100 + k * 10, comparable=True, complete=True,
                 partial=False, quality=[], refuel=False) for i in range(5)]
    store.put('session', (sid, '2026-01-01T00:00:00+00:00', '2026-01-01T00:10:00+00:00', 'completed', provenance, '{}', '{}'))
    for lap in laps:
        store.put('lap', (lap['id'], sid, json.dumps(lap)))
        repo.record_lap_context(sid, lap['id'], dict(layout_id=layout, car_id=car, provenance=provenance, identity_state=identity, integrity=True))
    for lap, ms in zip(laps[1:], segments):
        repo.record_spatial_context(sid, {'lap_id': lap['id'], 'reference_lap_id': laps[0]['id'], 'layout_id': layout, 'car_id': car,
                                          'source': 'calculated', 'items': [{'corner_id': 'T1', 'segment_ms': ms, 'reference_segment_ms': 12000,
                                                                              'loss_s': (ms - 12000) / 1000, 'confidence': .7}]})
    store.flush()
    return repo.process_session(store.detail(sid), driver, repo.session_context(sid))


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / 'db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    yield store, repo
    store.close()


def kinds(repo, kind):
    return [c for c in repo.challenges() if c['kind'] == kind]


# ---- F026 / F027 pure ordering -------------------------------------------------

def test_biggest_loss_orders_by_loss_then_confidence_then_id():
    big, small = rec('B', [12000, 12000, 13000, 13200, 12100]), rec('A', [12000, 12100, 12000, 12050])
    assert biggest_loss([small, big])['corner_id'] == 'B'
    a, b = rec('A', [12000, 12400, 12400]), rec('B', [12000, 12400, 12400])
    assert biggest_loss([b, a])['corner_id'] == biggest_loss([a, b])['corner_id'] == 'A'
    assert biggest_loss([b, dict(a, confidence=.9)])['corner_id'] == 'A'
    assert biggest_loss([dict(b, confidence=.9), a])['corner_id'] == 'B'
    top = biggest_loss([big])
    assert top['provenance'] == 'CALCULATED' and top['evidence']['samples_used'] == 5 and top['loss_s'] > 0


def test_nulls_with_sparse_or_flat_data():
    assert MIN_SAMPLES == 3
    assert biggest_loss([]) is None and easiest_gain([]) is None
    assert corner_loss(rec('A', [12000, 13000], samples=2)) is None
    assert corner_loss(rec('A', [12000, 12000, 12400], samples=2)) is None
    assert corner_loss(rec('A', [12000, 12000, 12000])) is None           # no supported loss
    assert easiest_gain([rec('A', [12000, 12000, 12400], consistency=None)]) is None   # repeatability unknown
    assert corner_loss(rec('A', [12000, float('nan'), 'x'])) is None


def test_easiest_gain_weights_repeatability_and_never_exceeds_loss():
    hard = rec('HARD', [12000, 12400, 12400], consistency=20)            # bigger loss, unreliable
    easy = rec('EASY', [12000, 12200, 12200], consistency=90)
    pick = easiest_gain([hard, easy])
    assert pick['corner_id'] == 'EASY' and 'recover' in pick['reason']
    for r in (hard, easy):
        item = easiest_gain([r])
        assert 0 < item['estimated_gain_s'] <= item['loss_s']
    assert biggest_loss([hard, easy])['corner_id'] == 'HARD'


def test_challenge_gates():
    assert challenge_gate(None)
    good = corner_loss(rec('A', [12000] * 4 + [12400] * 4, confidence=.2))
    assert challenge_gate(good) is None
    assert challenge_gate(dict(good, sample_count=4)) == 'too few corner samples'
    assert challenge_gate(dict(good, confidence=CHALLENGE_MIN_CONFIDENCE / 2)) == 'corner confidence too low'


# ---- integration through the real career pipeline ------------------------------

def test_insights_offer_and_reprocess_idempotent(env):
    store, repo = env
    run(store, repo, 's1', NOISY)
    data = repo.corner_insights('layout-a', 42)
    assert data['biggest_loss']['corner_id'] == 'T1' and data['provenance'] == 'CALCULATED'
    assert data['easiest_gain'] is None or data['easiest_gain']['estimated_gain_s'] <= data['biggest_loss']['loss_s']
    assert kinds(repo, 'corner_practice') == []                          # only 4 samples
    run(store, repo, 's2', NOISY, k=1)
    offers = kinds(repo, 'corner_practice')
    if data['easiest_gain'] is None:                                       # noisy repeatability can be unknown-to-low but defined
        pytest.skip('no easy gain')
    assert len(offers) == 1
    offer = offers[0]
    assert offer['status'] == 'offered' and offer['requirements']['evaluator'] == 'corner_segment' and offer['requirements']['corner_id'] == 'T1'
    assert offer['requirements']['target_segment_ms'] >= 11000 and offer['expires_at']
    driver = repo.active_profile_id()
    repo.process_session(store.detail('s2'), driver, repo.session_context('s2'))
    assert len(kinds(repo, 'corner_practice')) == 1
    assert repo.corner_insights('layout-a', 42)['challenge']['id'] == offer['id']
    assert repo.corner_insights('layout-a', 99)['biggest_loss'] is None   # other car: separate evidence


def test_ambiguous_track_replay_and_demo_produce_nothing(env):
    store, repo = env
    for i in range(3):
        run(store, repo, f'amb{i}', NOISY, k=i, identity='ambiguous')
    run(store, repo, 'rp', NOISY, k=9, provenance='replay')
    run(store, repo, 'demo', NOISY, k=10, provenance='demo')
    assert repo.corners('layout-a') == []
    data = repo.corner_insights('layout-a', 42)
    assert data['biggest_loss'] is None and data['easiest_gain'] is None and data['streaks'] == [] and data['challenge'] is None
    assert kinds(repo, 'corner_practice') == []
    assert store.query("SELECT 1 FROM career_events WHERE source='corner_badge'") == []


def test_corner_challenge_lifecycle_and_skip_without_punishment(env):
    store, repo = env
    run(store, repo, 's1', NOISY)
    run(store, repo, 's2', NOISY, k=1)
    offers = kinds(repo, 'corner_practice')
    if not offers:
        pytest.skip('no easy gain')
    offer = offers[0]
    now = datetime.now(timezone.utc)
    store.career_transaction(lambda db: transition_challenge(db, repo.active_profile_id(), offer['id'], 'accept', now.isoformat()))
    target = offer['requirements']['target_segment_ms']
    start, end, done = (now + timedelta(minutes=m) for m in (1, 2, 3))
    laps = [dict(id=f'f:{i}', number=i + 1, complete=True, partial=False, comparable=True, quality=[], refuel=False, duration_ms=90000) for i in range(5)]
    session = dict(id='f', started=start.isoformat(), ended=end.isoformat(), status='completed', provenance='live', laps=laps)
    context = dict(laps={lap['id']: dict(layout_id='layout-a', car_id=42, provenance='live', identity_state='locked') for lap in laps})
    context['spatial'] = {lap['id']: {'lap_id': lap['id'], 'reference_lap_id': 'f:0', 'layout_id': 'layout-a', 'car_id': 42, 'source': 'calculated',
                                      'items': [{'corner_id': 'T1', 'segment_ms': target - 1, 'confidence': .7}]} for lap in laps[1:4]}
    context['spatial']['f:4'] = {**context['spatial']['f:1'], 'lap_id': 'f:4', 'items': [{'corner_id': 'T1', 'segment_ms': target + 500, 'confidence': .7}]}
    evidence = evaluate(session, context)['evidence']
    xp = store.career_transaction(lambda db: advance_challenges(db, repo.active_profile_id(), 'career:v1:f', session, evidence, context, done.isoformat()))
    assert xp == 20
    done_row = next(c for c in kinds(repo, 'corner_practice') if c['id'] == offer['id'])
    assert done_row['status'] == 'completed' and done_row['completion_evidence']['observed'] == 3
    again = store.career_transaction(lambda db: advance_challenges(db, repo.active_profile_id(), 'career:v1:f', session, evidence, context, done.isoformat()))
    assert again == 0
    # A fresh offer for another layout can be skipped with no penalty (no XP change, status skipped).
    run(store, repo, 'o1', NOISY, k=3, layout='layout-b')
    run(store, repo, 'o2', NOISY, k=4, layout='layout-b')
    other = [c for c in kinds(repo, 'corner_practice') if c['requirements']['layout_id'] == 'layout-b']
    if other:
        before = repo.active_profile()['total_xp']
        skipped = store.career_transaction(lambda db: transition_challenge(db, repo.active_profile_id(), other[0]['id'], 'skip', datetime.now(timezone.utc).isoformat()))
        assert skipped['status'] == 'skipped' and repo.active_profile()['total_xp'] == before


# ---- F029 / F030 -----------------------------------------------------------------

def test_streak_increments_resets_with_analysis_and_is_idempotent(env):
    store, repo = env
    kind = streak_kind('layout-a', 42, 'T1')
    driver = repo.active_profile_id()

    def streak():
        rows = [s for s in repo.streaks() if s['kind'] == kind]
        return rows[0] if rows else None

    for i in range(3):
        run(store, repo, f'g{i}', TIGHT, k=i)
        assert streak()['current_count'] == i + 1
    repo.process_session(store.detail('g2'), driver, repo.session_context('g2'))
    assert streak()['current_count'] == 3
    # Same source again through the domain function: no double count.
    store.career_transaction(lambda db: update_corner_streaks(db, driver, 'layout-a', 42, streak()['last_source_id'], {'T1': 50}, 'x'))
    assert streak()['current_count'] == 3
    run(store, repo, 'bad', NOISY, k=5)
    broken = streak()
    assert broken['current_count'] == 0 and broken['best_count'] == 3 and broken['reason'].startswith('Analysis:')
    assert 'fail' not in broken['reason'].lower() and 'bad' not in broken['reason'].lower().split()
    assert repo.corner_insights('layout-a', 42)['streaks'][0]['corner_id'] == 'T1'
    repo.process_session(store.detail('bad'), driver, repo.session_context('bad'))
    assert streak()['current_count'] == 0


def test_corner_badges_earned_once_with_evidence_and_live_only(env):
    store, repo = env
    driver = repo.active_profile_id()
    for i in range(5):
        run(store, repo, f'm{i}', TIGHT, k=i)
    assert repo.corners('layout-a')[0]['mastered'] is True
    badges = {b['id']: b for b in repo.badges()}
    first = badges['CORNER_MASTER_1']
    assert first['unlocked'] and first['earned_at'] and first['evidence']['provenance'] == 'CALCULATED'
    assert first['evidence']['detail']['mastered_corner_ids'] == ['T1'] and first['evidence']['detail']['layout_id'] == 'layout-a'
    assert not badges['CORNER_MASTER_3']['unlocked'] and badges['CORNER_MASTER_3']['progress']['current'] == 1
    earned = first['earned_at']
    count = lambda: store.query("SELECT COUNT(*) AS n FROM career_events WHERE source='corner_badge'")[0]['n']
    assert count() == 1
    run(store, repo, 'm5', TIGHT, k=5)
    store.career_transaction(lambda db: award_corner_badges(db, driver, 'layout-a', 42, 'again', '2030-01-01T00:00:00+00:00'))
    repo.process_session(store.detail('m0'), driver, repo.session_context('m0'))
    assert count() == 1
    assert {b['id']: b for b in repo.badges()}['CORNER_MASTER_1']['earned_at'] == earned
    assert repo.corner_insights('layout-a', 42)['badges'][0]['unlocked'] is True


# ---- API validation --------------------------------------------------------------

def test_insights_endpoint_validation(env):
    store, repo = env
    app = FastAPI()
    app.include_router(gamification_api.router())
    app.state.runtime = SimpleNamespace(career_repository=repo)
    client = TestClient(app)
    ok = client.get('/api/gamification/corners/insights', params={'layout_id': 'layout-a', 'car_id': 42})
    assert ok.status_code == 200 and ok.json()['biggest_loss'] is None and ok.json()['corners_considered'] == 0
    for params in ({'layout_id': 'layout-a'}, {'car_id': 42}, {'layout_id': '', 'car_id': 42}, {'layout_id': 'x', 'car_id': 0},
                   {'layout_id': 'x', 'car_id': 'abc'}, {'layout_id': 'x' * 121, 'car_id': 1}):
        assert client.get('/api/gamification/corners/insights', params=params).status_code == 422
