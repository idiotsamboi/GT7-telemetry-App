"""F016-F020: strategy/training components, corner coverage, missions and idempotent level rewards."""
import json

from backend.app.gamification.mastery import components_score
from backend.app.gamification.repository import CareerRepository
from backend.app.gamification.rewards import LEVEL_XP, reward_id
from backend.app.gamification.track_components import (
    corner_coverage, discovery_level, mission_component, strategy_component, training_component)
from backend.app.storage import Store


def run(store, repo, sid, n=5, fuel=None, layout='layout-a', car=42, provenance='live', identity='locked', extra=None, offset=0):
    driver = repo.active_profile_id()
    repo.bind_session(sid, driver, provenance)
    laps = [dict(id=f'{sid}:{i}', number=i+1, duration_ms=90000+i*100+offset, comparable=True, complete=True, partial=False,
                 quality=[], refuel=False, fuel_used_l=(fuel[i % len(fuel)] if fuel else None)) for i in range(n)]
    store.put('session', (sid, '2026-01-01T00:00:00+00:00', '2026-01-01T00:10:00+00:00', 'completed', provenance, '{}', '{}'))
    for lap in laps:
        store.put('lap', (lap['id'], sid, json.dumps(lap)))
        repo.record_lap_context(sid, lap['id'], dict(layout_id=layout, car_id=car, provenance=provenance, identity_state=identity, integrity=True))
    store.flush()
    ctx = repo.session_context(sid)
    ctx.update(extra or {})
    return repo.process_session(store.detail(sid), driver, ctx)


def fresh(tmp_path):
    store = Store(tmp_path / 'db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    return store, repo


def fuel_laps(*values):
    return [dict(comparable=True, refuel=False, fuel_used_l=x) for x in values]


def test_strategy_component_math_nulls_and_bounds():
    assert strategy_component(None, fuel_laps(2.0, 2.0))['score'] is None
    assert strategy_component(None, fuel_laps(None, None, None))['provenance'] == 'UNAVAILABLE'
    perfect = strategy_component(None, fuel_laps(2.0, 2.0, 2.0))
    assert perfect['score'] == 100 and 0 <= perfect['confidence'] <= 1
    noisy = strategy_component(None, fuel_laps(1.0, 3.0, 2.0, 5.0))
    assert 0 <= noisy['score'] < 50
    assert strategy_component([2.0, 2.0], fuel_laps(2.0))['score'] == 100     # accumulates across sessions
    assert strategy_component(None, [dict(comparable=True, refuel=True, fuel_used_l=2.0)] * 4)['score'] is None


def test_training_coverage_levels_and_mission_target():
    assert training_component(None)['score'] is None
    assert training_component({'laps_saved': 0, 'percent': 50})['score'] is None
    assert training_component({'laps_saved': 3, 'percent': 140})['score'] == 100
    assert corner_coverage([{'sample_count': 5}, {'sample_count': 1}], None)['available'] is False
    cov = corner_coverage([{'sample_count': 5}, {'sample_count': 1}], 4)
    assert cov['percentage'] == 25.0 and cov['catalogued'] == 4
    base = dict(lap_count=12, observed_component_score=70, overall_score=None, confidence=.4)
    assert discovery_level(base) == 'Learning'
    assert discovery_level(dict(base, lap_count=2, observed_component_score=5), 'Familiar') == 'Familiar'   # hysteresis
    assert mission_component(dict(layout_id='l', car_id=1, confidence=.5, components={'pace': 80, 'consistency': 40})) == 'consistency'
    assert mission_component(dict(layout_id='l', car_id=1, confidence=.1, components={'pace': 80})) is None
    assert mission_component(dict(layout_id=None, car_id=1, confidence=.9, components={'pace': 80})) is None
    assert components_score({'pace': 50, 'consistency': 50, 'corners': 50, 'training': 50, 'strategy': 50})['overall_score'] == 50


def test_components_plugged_into_mastery_and_rewards_idempotent(tmp_path):
    store, repo = fresh(tmp_path)
    try:
        ctx = {'training': {'layout-a': {'laps_saved': 4, 'percent': 60.0, 'complete': False}}, 'corner_catalogue': {'layout-a': 5}}
        card = run(store, repo, 's1', n=5, fuel=[2.0, 2.02, 1.98, 2.0, 2.01], extra=ctx)
        assert card['status'] == 'eligible'
        track = repo.tracks()[0]
        assert track['components']['strategy'] is not None and 0 <= track['components']['strategy'] <= 100
        assert track['components']['training'] == 60.0
        assert track['mastery_level'] == 'Recognized'
        assert track['corner_coverage']['catalogued'] == 5 and track['corner_coverage']['percentage'] == 0.0
        assert 0 <= track['confidence'] <= 1 and 0 <= track['score_confidence'] <= track['confidence']
        xp = store.query("SELECT amount FROM career_xp_events WHERE category='TRACK_MASTERY'")
        assert [r['amount'] for r in xp] == [LEVEL_XP['Recognized']]
        assert store.query("SELECT 1 FROM career_events WHERE kind='MASTERY_CHANGED'")
        driver = repo.active_profile_id()
        total = repo.active_profile()['total_xp']
        repo.process_session(store.detail('s1'), driver, repo.session_context('s1'))   # reprocess
        assert len(store.query("SELECT 1 FROM career_xp_events WHERE category='TRACK_MASTERY'")) == 1
        assert repo.active_profile()['total_xp'] == total
        run(store, repo, 's2', n=5, offset=7)                                                   # 10 laps -> Learning
        levels = sorted(r['amount'] for r in store.query("SELECT amount FROM career_xp_events WHERE category='TRACK_MASTERY'"))
        assert levels == [LEVEL_XP['Recognized'], LEVEL_XP['Learning']]
        assert store.query('SELECT 1 FROM career_xp_events WHERE id=?', (reward_id(driver, 'layout-a', 42, 'Learning'),))
    finally:
        store.close()


def test_null_components_when_fuel_or_training_unavailable(tmp_path):
    store, repo = fresh(tmp_path)
    try:
        run(store, repo, 's1', n=5)
        track = repo.tracks()[0]
        assert track['components']['strategy'] is None and track['components']['training'] is None
        assert track['overall_score'] is None and track['corner_coverage']['available'] is False
    finally:
        store.close()


def test_replay_and_demo_never_reward_or_track(tmp_path):
    store, repo = fresh(tmp_path)
    try:
        for prov in ('replay', 'demo'):
            run(store, repo, prov, n=12, provenance=prov)
        assert repo.tracks() == []
        assert store.query("SELECT 1 FROM career_xp_events WHERE category='TRACK_MASTERY'") == []
        assert store.query("SELECT 1 FROM career_events WHERE kind='MASTERY_CHANGED'") == []
    finally:
        store.close()


def test_missions_offered_for_weakest_and_not_when_ambiguous_or_low_confidence(tmp_path):
    store, repo = fresh(tmp_path)
    try:
        run(store, repo, 'few', n=3)                              # confidence .15: no mission
        assert [c for c in repo.challenges() if c['kind'] == 'track_mission'] == []
        run(store, repo, 'amb', n=8, layout='layout-b', identity='ambiguous')
        assert [c for c in repo.challenges() if c['kind'] == 'track_mission'] == []
        run(store, repo, 'many', n=8, layout='layout-c')
        missions = [c for c in repo.challenges() if c['kind'] == 'track_mission']
        assert len(missions) == 1 and missions[0]['component'] in ('pace', 'consistency')
        assert missions[0]['requirements']['layout_id'] == 'layout-c'
        run(store, repo, 'many2', n=8, layout='layout-c', offset=9)
        assert len([c for c in repo.challenges() if c['kind'] == 'track_mission' and c['requirements']['layout_id'] == 'layout-c']) == 1
    finally:
        store.close()
