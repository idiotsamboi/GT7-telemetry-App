"""Career transfer retains original evidence without importing live reward authority."""
import copy

import pytest

from backend.app.gamification.repository import CareerRepository
try:
    from tests.test_gamification_mastery import session
except ImportError:
    from test_gamification_mastery import session


def test_archive_round_trip_is_isolated_and_cannot_earn_live_rewards(tmp_path):
    store = Store(tmp_path/'db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    try:
        session(store, repo, 'original', spatial=True)
        bundle = repo.export()
        assert bundle['format'] == 'gt7-driver-career' and bundle['telemetry_included'] is False
        assert bundle['profile']['total_xp'] == sum(e['amount'] for e in bundle['records']['career_xp_events'])
        imported = repo.import_bundle(bundle)
        archive = repo.dashboard(imported['id'])
        assert archive['integrity']['scope'] == 'imported_profile'
        assert archive['profile']['total_xp'] == bundle['profile']['total_xp']
        assert archive['scorecards'][0]['status'] == 'imported'
        assert repo.export(imported['id']) == bundle
        repo.select_profile(imported['id'])
        result = session(store, repo, 'new-recording', offset=40)
        assert result['status'] == 'excluded' and result['xp_awarded'] == 0
        assert 'imported_profile_archive' in result['exclusions']
        assert repo.dashboard()['profile']['total_xp'] == bundle['profile']['total_xp']
        assert len(store.detail('original')['laps']) == 5
    finally:
        store.close()


def test_invalid_archive_is_atomic_and_does_not_create_profile(tmp_path):
    store = Store(tmp_path/'db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    try:
        session(store, repo, 'baseline')
        bundle = repo.export()
        bad = copy.deepcopy(bundle)
        bad['profile']['total_xp'] += 1000
        with pytest.raises(ValueError, match='ledger'):
            repo.import_bundle(bad)
        assert len(repo.list_profiles()) == 1
        bad = copy.deepcopy(bundle)
        bad['records']['career_skills'][0]['score'] = float('nan')
        with pytest.raises(ValueError):
            repo.import_bundle(bad)
        assert len(repo.list_profiles()) == 1
    finally:
        store.close()
