import json

import pytest

from backend.app.core.errors import AppError, ResultCode
from backend.app.storage import Store
from backend.app.storage.models import SessionQuery
from backend.app.storage.repositories import PURGE_CONFIRMATION, SqliteSessionRepository


def seed_session(store, sid, started, *, ended='x', provenance='live', laps=('l1',), samples=0, meta=None):
    ended = None if ended is None else (started[:10] + 'T23:00:00+00:00' if ended == 'x' else ended)
    store.put('session', (sid, started, ended, 'completed' if ended else 'driving', provenance, json.dumps(meta or {}), json.dumps({'ok': True})))
    for lap in laps:
        store.put('lap', (f'{sid}-{lap}', sid, json.dumps({'id': f'{sid}-{lap}', 'number': 1, 'duration_ms': 90000})))
    for i in range(samples):
        lap = laps[i % len(laps)] if laps else None
        payload = {'mono': float(i), 'utc': f'2026-01-01T00:00:{i % 60:02d}+00:00', 'lap_id': f'{sid}-{lap}',
                   'values': {'speed_kmh': float(i % 100), 'rpm': 5000 + i, 'throttle': 0.5, 'position': [1, 2, 3]}}
        store.put('sample', (sid, f'{sid}-{lap}', float(i), i, json.dumps(payload)))


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / 'db')
    yield s
    s.close()


@pytest.fixture
def repo(store):
    return SqliteSessionRepository(store)


def test_list_is_index_only_paged_and_filtered(store, repo):
    for i in range(5):
        seed_session(store, f's{i}', f'2026-01-0{i + 1}T00:00:00+00:00', provenance='demo' if i == 4 else 'live', laps=('a', 'b'), samples=4)
    store.flush()
    store.put('archive', ('2026-02-01T00:00:00+00:00', 's0'))
    store.flush()
    first = repo.list(SessionQuery(limit=2))
    assert [s.id for s in first.items] == ['s4', 's3'] and first.total == 4 and first.next_cursor
    assert first.items[0].lap_count == 2 and not hasattr(first.items[0], 'samples')
    second = repo.list(SessionQuery(limit=2, cursor=first.next_cursor))
    assert [s.id for s in second.items] == ['s2', 's1'] and second.next_cursor is None
    assert [s.id for s in repo.list(SessionQuery(offset=1, limit=1)).items] == ['s3']
    assert [s.id for s in repo.list(SessionQuery(provenance='demo')).items] == ['s4']
    assert 's0' in [s.id for s in repo.list(SessionQuery(include_archived=True)).items]
    assert repo.list(SessionQuery(limit=10_000)).limit == 200
    json.dumps(first.to_public())
    with pytest.raises(AppError):
        repo.list(SessionQuery(cursor='not-a-cursor'))


def test_get_has_laps_and_report_but_no_samples(store, repo):
    seed_session(store, 's', '2026-01-01T00:00:00+00:00', laps=('a', 'b'), samples=3)
    store.flush()
    d = repo.get('s')
    assert [l['id'] for l in d.laps] == ['s-a', 's-b'] and d.report == {'ok': True} and d.protected is False
    assert 'samples' not in d.to_public()
    assert repo.get('missing') is None


def test_samples_projection_paging_and_lap_filter(store, repo):
    seed_session(store, 's', '2026-01-01T00:00:00+00:00', laps=('a', 'b'), samples=25)
    store.flush()
    page = repo.samples('s', channels=['speed_kmh', 'nope'], limit=10)
    assert len(page.items) == 10 and page.next_cursor
    assert set(page.items[0].values) == {'speed_kmh'} and page.items[0].mono == 0.0 and page.items[0].utc
    collected = list(page.items)
    while page.next_cursor:
        page = repo.samples('s', after=page.next_cursor, channels=['speed_kmh'], limit=10)
        collected += page.items
    assert [r.record_id for r in collected] == sorted(r.record_id for r in collected) and len(collected) == 25
    lap_a = repo.samples('s', lap_id='s-a')
    assert len(lap_a.items) == 13 and set(lap_a.items[0].values) >= {'rpm', 'position'}


def test_lap_series_keeps_peaks(store, repo):
    store.put('session', ('s', '2026-01-01T00:00:00+00:00', 'e', 'completed', 'live', '{}', '{}'))
    for i in range(4000):
        speed = 100.0 + (i % 7) * 0.1
        if i == 2503:
            speed = 300.0
        if i == 1777:
            speed = 5.0
        payload = {'mono': float(i), 'utc': 'u', 'values': {'speed_kmh': speed, 'position': [0, 0, 0]}}
        store.put('sample', ('s', 'L', float(i), i, json.dumps(payload)))
    store.flush()
    series = repo.lap_series('s', 'L', ['speed_kmh', 'position'], points=100)
    speed = series.series['speed_kmh']
    assert series.source_samples == 4000 and len(speed['v']) <= 100
    assert max(speed['v']) == 300.0 and min(speed['v']) == 5.0          # extrema survive downsampling
    assert speed['t'] == sorted(speed['t'])
    assert len(series.series['position']['v']) <= 100
    small = repo.lap_series('s', 'nolap', ['speed_kmh'])
    assert small.source_samples == 0 and small.series['speed_kmh'] == {'t': [], 'v': []}


def test_meta_protect_archive_and_purge_rules(store, repo):
    seed_session(store, 'done', '2026-01-01T00:00:00+00:00', samples=3, meta={'name': 'a'})
    seed_session(store, 'live', '2026-01-02T00:00:00+00:00', ended=None, samples=2)
    store.flush()
    repo.update_meta('done', {'name': 'b'})
    assert repo.get('done').meta == {'name': 'b'}
    repo.protect('done')
    assert repo.get('done').protected and repo.get('done').meta == {'name': 'b'}
    with pytest.raises(AppError) as bad:
        repo.purge('done', confirm='yes')
    assert bad.value.code == ResultCode.INVALID_INPUT
    for sid, expected in (('live', 'active'), ('done', 'Protected')):
        with pytest.raises(AppError) as err:
            repo.purge(sid, confirm=PURGE_CONFIRMATION)
        assert err.value.code == ResultCode.INVALID_STATE and expected in err.value.detail
    repo.protect('done', False)
    with pytest.raises(AppError) as err:
        repo.purge('done', confirm=PURGE_CONFIRMATION)
    assert 'Archive' in err.value.detail                       # must be archived first
    repo.archive('live')
    assert repo.get('live').archived_at is None                # active session is never archived
    repo.archive('done')
    assert repo.get('done').archived_at
    assert repo.purge('done', confirm=PURGE_CONFIRMATION) is True
    assert repo.get('done') is None and store.query("SELECT COUNT(*) n FROM samples WHERE session='done'")[0]['n'] == 0
    assert repo.get('live') is not None
    with pytest.raises(AppError) as missing:
        repo.protect('gone')
    assert missing.value.code == ResultCode.NOT_FOUND


def test_annotations_passthrough(store, repo):
    seed_session(store, 's', '2026-01-01T00:00:00+00:00')
    store.put('annotation', ('s', None, json.dumps({'message': 'm'}), 'bookmark'))
    store.flush()
    assert repo.annotations('s')[0]['kind'] == 'bookmark'
