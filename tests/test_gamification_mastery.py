"""F011–F025: components, car separation, immutable spatial provenance and repeatability."""
import json

import pytest

from backend.app.gamification.mastery import components_score
from backend.app.gamification.repository import CareerRepository
from backend.app.storage import Store


def session(store, repo, sid, car=42, layout='layout-a', offset=0, spatial=False):
    driver = repo.active_profile_id()
    repo.bind_session(sid, driver, 'live')
    laps = [dict(id=f'{sid}:{i}', number=i+1, duration_ms=90000+i*100+offset,
                 comparable=True, complete=True, partial=False, quality=[], refuel=False) for i in range(5)]
    store.put('session', (sid, '2026-01-01T00:00:00+00:00', '2026-01-01T00:10:00+00:00', 'completed', 'live', '{}', '{}'))
    for lap in laps:
        store.put('lap', (lap['id'], sid, json.dumps(lap)))
        repo.record_lap_context(sid, lap['id'], dict(layout_id=layout, car_id=car, provenance='live', identity_state='locked', integrity=True))
    if spatial:
        for lap in laps[1:]:
            repo.record_spatial_context(sid, {'lap_id': lap['id'], 'reference_lap_id': laps[0]['id'], 'layout_id': layout, 'car_id': car, 'source': 'calculated',
                                            'items': [{'corner_id': 'T1', 'segment_ms': 12000+offset, 'reference_segment_ms': 12000,
                                                       'loss_s': offset/1000, 'confidence': .7}]})
    store.flush()
    return repo.process_session(store.detail(sid), driver, repo.session_context(sid))


def test_components_preserve_unknown_and_reject_invalid_weights():
    result = components_score({'pace': None, 'consistency': 90, 'corners': None, 'training': None, 'strategy': None})
    assert result['overall_score'] is None and result['observed_component_score'] == 90
    assert result['component_coverage'] == .2
    with pytest.raises(ValueError):
        components_score({}, {'pace': -1})


def test_track_and_corner_persistence_idempotency_and_car_baselines(tmp_path):
    store = Store(tmp_path/'db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    try:
        card = session(store, repo, 'one', spatial=True)
        assert card['status'] == 'eligible'
        track = repo.tracks()[0]
        assert track['pb_ms'] == 90000 and track['overall_score'] is None
        corner = repo.corners('layout-a')[0]
        assert corner['sample_count'] == 4 and 0 <= corner['score'] <= 100
        assert corner['confidence'] < .2
        driver = repo.active_profile_id()
        repo.process_session(store.detail('one'), driver, repo.session_context('one'))
        assert repo.corners('layout-a')[0]['sample_count'] == 4
        session(store, repo, 'two', offset=-500)
        assert repo.tracks()[0]['pb_improvement_ms'] == 500
        session(store, repo, 'other-car', car=99, offset=-2000)
        other = next(t for t in repo.tracks() if t['car_id'] == 99)
        assert other['components']['pace'] is None
        assert len(repo.tracks()) == 2
        repo.reset(driver, 'RESET CAREER')
        assert repo.tracks() == [] and repo.corners('layout-a') == []
        assert len(store.detail('one')['laps']) == 5
    finally:
        store.close()


def test_unpersisted_spatial_context_cannot_create_corner_scores(tmp_path):
    store = Store(tmp_path/'db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    try:
        session(store, repo, 'one', spatial=False)
        assert repo.corners('layout-a') == []
    finally:
        store.close()
