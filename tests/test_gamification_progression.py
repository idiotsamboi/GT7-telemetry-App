"""F005-F010: titles, badges, recent gains, overview, timeline, stats (evidence-backed, live-only)."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.config import Config
from backend.app.gamification import CareerRepository, titles as titles_mod
from backend.app.storage import Store

from tests.test_gamification_foundation import finalized


@pytest.fixture
def career(tmp_path):
    store = Store(tmp_path / 'career.db')
    repo = CareerRepository(store)
    repo.ensure_default_profile()
    yield store, repo
    store.close()


def set_profile(store, repo, **fields):
    cols = ','.join(f'{k}=?' for k in fields)
    store.career_transaction(lambda db: db.execute(f'UPDATE career_profiles SET {cols} WHERE id=?', (*fields.values(), repo.active_profile_id())))


def add_event(store, repo, kind, source_id, evidence, stamp, title=None):
    driver = repo.active_profile_id()
    def op(db):
        db.execute('INSERT INTO career_events VALUES(?,?,?,?,?,?,?,?,?)', (f'{kind}:{source_id}', driver, kind, 'session', source_id, 'CALCULATED', json.dumps(evidence), None, stamp))
        if title:
            db.execute('INSERT INTO career_notifications VALUES(?,?,?,?,?,NULL,?)', (f'{kind}:{source_id}', driver, 'NORMAL', title, 'b', stamp))
    store.career_transaction(op)


def test_title_thresholds_progress_and_equip(career):
    _, repo = career
    by_id = {t['id']: t for t in repo.titles()['titles']}
    assert by_id['novice_driver']['unlocked'] and by_id['novice_driver']['evidence']['provenance'] == 'CALCULATED'
    assert not by_id['consistent_pacesetter']['unlocked'] and by_id['consistent_pacesetter']['evidence'] is None
    assert by_id['consistent_pacesetter']['progress'] == dict(current=0, target=5, fraction=0.0)
    with pytest.raises(ValueError, match='locked'):
        repo.equip_title('Apex Hunter')
    with pytest.raises(ValueError, match='Unknown'):
        repo.equip_title('Nope')
    store, _ = career
    set_profile(store, repo, comparable_laps=100, total_xp=repo.curve.threshold(10))
    by_id = {t['id']: t for t in repo.titles()['titles']}
    assert [k for k, t in by_id.items() if t['unlocked']] == ['novice_driver', 'consistent_pacesetter', 'apex_hunter', 'track_master']
    assert repo.equip_title('apex_hunter') == {'equipped': 'Apex Hunter'}
    assert repo.equip_title('Apex Hunter') == {'equipped': 'Apex Hunter'}   # idempotent
    assert repo.titles()['equipped'] == 'Apex Hunter'
    assert titles_mod.next_title(repo.titles()['titles'])['id'] == 'veteran_racer'


def test_badges_progress_then_earned_with_evidence(career):
    store, repo = career
    badges = {b['id']: b for b in repo.badges()}
    assert not any(b['unlocked'] for b in badges.values())
    assert badges['TEN_LAPS']['progress']['target'] == 10 and badges['TEN_LAPS']['earned_at'] is None
    session, driver, context = finalized(store, repo)
    repo.process_session(session, driver, context)
    add_event(store, repo, 'PB_SET', 'pb1', {'session_id': 's1', 'pb_ms': 90000}, '2026-01-03T00:00:00+00:00')
    badges = {b['id']: b for b in repo.badges()}
    assert badges['FIRST_LAP']['unlocked'] and badges['FIRST_LAP']['evidence']['source'] == 'career_achievements'
    assert badges['FIRST_LAP']['earned_at'] and not badges['TEN_LAPS']['unlocked']
    assert badges['TEN_LAPS']['progress']['current'] == 2
    assert badges['FIRST_PB']['unlocked'] and badges['FIRST_PB']['evidence']['detail']['pb_ms'] == 90000
    grade = badges['CONSISTENCY_S']
    card = store.query("SELECT json_extract(payload,'$.evidence.session_grade') AS g FROM career_scorecards")[0]['g']
    assert grade['unlocked'] == (card == 'S')
    assert repo.badges() == list(badges.values())   # deterministic / idempotent


def test_recent_gains_zero_one_many(career):
    store, repo = career
    empty = repo.recent_gains()
    assert empty['recent_xp'] == 0 and empty['sessions'] == [] and empty['delta_score'] is None and empty['latest_grade'] is None
    for n in range(1, 8):
        session, driver, context = finalized(store, repo, sid=f's{n}', layout=f'layout-{n}', car=100 + n)
        repo.process_session(session, driver, context)
        if n == 1:
            one = repo.recent_gains()
            assert len(one['sessions']) == 1 and one['delta_score'] is None and one['sessions'][0]['skill_deltas'] is None
    many = repo.recent_gains()
    assert many['sessions_evaluated'] == 5 and len(many['sessions']) == 5
    top = many['sessions'][0]
    assert top['session_id'] == 's7' and top['xp_awarded'] == many['recent_xp'] > 0
    assert sum(top['xp_by_category'].values()) == top['xp_awarded'] - 0 or sum(top['xp_by_category'].values()) <= top['xp_awarded']
    assert {'recent_xp', 'sessions_evaluated', 'latest_grade', 'delta_score'} <= set(many)


def test_overview_nulls_without_data_and_populates(career):
    store, repo = career
    o = repo.overview()
    assert o['recent_gains'] is None and o['top_badges'] == [] and o['equipped_title']['id'] == 'novice_driver'
    assert o['next_unlock'] is not None and o['level']['current'] == 1
    session, driver, context = finalized(store, repo)
    repo.process_session(session, driver, context)
    o = repo.overview()
    assert o['recent_gains']['sessions_evaluated'] == 1 and o['top_badges'][0]['id'] == 'FIRST_LAP'


def test_timeline_order_limit_and_cursor(career):
    store, repo = career
    assert repo.timeline()['items'] == [] and repo.timeline()['next_cursor'] is None
    for i in range(5):
        add_event(store, repo, 'PB_SET', f'p{i}', {'i': i}, f'2026-01-0{i + 1}T00:00:00+00:00', title='PB' if i == 4 else None)
    page = repo.timeline(limit=2)
    assert [e['evidence']['i'] for e in page['items']] == [4, 3]
    assert page['items'][0]['title'] == 'PB' and page['items'][1]['title'] == 'Pb Set'
    nxt = repo.timeline(limit=2, cursor=page['next_cursor'])
    assert [e['evidence']['i'] for e in nxt['items']] == [2, 1]
    last = repo.timeline(limit=2, cursor=nxt['next_cursor'])
    assert [e['evidence']['i'] for e in last['items']] == [0] and last['next_cursor'] is None
    for bad in (0, 101, True):
        with pytest.raises(ValueError):
            repo.timeline(limit=bad)
    with pytest.raises(ValueError):
        repo.timeline(cursor='garbage')


def test_stats_counts(career):
    store, repo = career
    zero = repo.stats()
    assert zero['sessions_processed'] == 0 and zero['xp_by_category'] == {} and zero['tracks_visited'] == 0
    for n, layout in enumerate(('a', 'a', 'b'), 1):
        session, driver, context = finalized(store, repo, sid=f's{n}', layout=layout, car=200 + n)
        repo.process_session(session, driver, context)
    add_event(store, repo, 'PB_SET', 'x', {}, '2026-01-01T00:00:00+00:00')
    s = repo.stats()
    assert s['sessions_processed'] == 3 and s['eligible_sessions'] + s['excluded_sessions'] == 3
    assert s['personal_bests'] == 1 and s['comparable_laps'] == repo.active_profile()['comparable_laps']
    assert sum(s['xp_by_category'].values()) == s['total_xp']
    assert s['tracks_visited'] == len(store.query('SELECT DISTINCT layout_id FROM career_track_mastery'))


def test_replay_and_demo_sessions_yield_nothing(career):
    store, repo = career
    for sid, prov in (('r1', 'replay'), ('d1', 'demo')):
        session, driver, context = finalized(store, repo, sid=sid, provenance=prov)
        assert repo.process_session(session, driver, context)['status'] == 'excluded'
    assert repo.recent_gains()['sessions'] == []
    assert repo.stats()['eligible_sessions'] == 0 and repo.stats()['total_xp'] == 0
    assert repo.timeline()['items'] == [] and not any(b['unlocked'] for b in repo.badges())


def test_repo_views_do_not_mutate(career):
    store, repo = career
    session, driver, context = finalized(store, repo)
    repo.process_session(session, driver, context)
    before = (repo.overview(), repo.stats(), repo.timeline(), repo.recent_gains(), repo.titles(), repo.badges())
    after = (repo.overview(), repo.stats(), repo.timeline(), repo.recent_gains(), repo.titles(), repo.badges())
    assert before == after
    assert repo.dashboard()['titles']['titles'][0]['id'] == 'novice_driver'


def test_api_overview_timeline_stats_validation(tmp_path):
    Config(tmp_path).save({'http_port': 18872, 'speech_enabled': False, 'hands_free': False})
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1:8000') as c:
        assert c.get('/api/gamification/overview').status_code == 401
        assert c.post('/api/pair', json={}).status_code == 200
        o = c.get('/api/gamification/overview').json()
        assert o['recent_gains'] is None and o['equipped_title']['name'] == 'Novice Driver'
        assert c.get('/api/gamification/stats').json()['sessions_processed'] == 0
        assert c.get('/api/gamification/timeline?limit=5').json()['items'] == []
        assert c.get('/api/gamification/timeline?limit=0').status_code == 422
        assert c.get('/api/gamification/timeline?limit=101').status_code == 422
        assert c.get('/api/gamification/timeline?cursor=bad').status_code == 422
        assert c.post('/api/gamification/titles/equip?title_name=Master%20Driver').status_code == 422
        assert c.post('/api/gamification/titles/equip?title_name=Novice%20Driver').json() == {'equipped': 'Novice Driver'}
