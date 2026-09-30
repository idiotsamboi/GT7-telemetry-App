import json
import os

import pytest

from backend.app.analysis_cache import AnalysisCache, settings_hash, source_hash
from backend.app.core.version import ANALYSIS_VERSION
from backend.app.storage import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / 'db')
    s.put('session', ('s', '2026-01-01T00:00:00+00:00', 'e', 'completed', 'live', '{}', '{}'))
    s.put('lap', ('l1', 's', '{}'))
    for i in range(5):
        s.put('sample', ('s', 'l1', float(i), i, json.dumps({'mono': float(i), 'values': {}})))
    s.flush()
    yield s
    s.close()


def test_put_get_roundtrip_and_key_parts(tmp_path):
    cache = AnalysisCache(tmp_path)
    assert (tmp_path / 'cache' / 'analysis').is_dir()
    assert cache.get('s', 'h1') is None
    assert cache.put('s', 'h1', {'a': [1, 2]}, settings='x')
    assert cache.get('s', 'h1', settings='x') == {'a': [1, 2]}
    assert cache.get('s', 'h1', settings='other') is None           # settings change -> miss
    assert cache.get('s', 'h2', settings='x') is None                # source change -> miss
    assert cache.get('s', 'h1', settings='x', version=ANALYSIS_VERSION + 1) is None
    assert cache.get('t', 'h1', settings='x') is None
    stats = cache.stats()
    assert stats['entries'] == 1 and stats['hits'] == 1 and stats['misses'] == 5


def test_stale_after_new_samples(store, tmp_path):
    cache = AnalysisCache(tmp_path)
    before = source_hash(store, 's')
    assert before == source_hash(store, 's')                         # stable
    cache.put('s', before, {'v': 1})
    assert cache.get('s', before) == {'v': 1}
    store.put('sample', ('s', 'l1', 9.0, 9, json.dumps({'mono': 9.0, 'values': {}})))
    store.flush()
    after = source_hash(store, 's')
    assert after != before and cache.get('s', after) is None         # new samples invalidate by construction
    store.put('lap', ('l2', 's', '{}'))
    store.flush()
    assert source_hash(store, 's') not in (before, after)            # new lap too
    assert source_hash(store, 'empty') == source_hash(store, 'empty')


def test_eviction_keeps_under_bound_lru(tmp_path):
    cache = AnalysisCache(tmp_path, max_bytes=2000)
    blob = 'x' * 800                                                 # ~850 bytes per entry: two fit, three do not
    cache.put('s', 'h0', blob)
    cache.put('s', 'h1', blob)
    files = {json.loads(p.read_text())['key'][1]: p for p in cache.dir.glob('*.json')}
    now = os.path.getmtime(files['h1'])
    os.utime(files['h0'], (now - 60, now - 60))                      # h0 oldest, h1 newer
    os.utime(files['h1'], (now - 30, now - 30))
    assert cache.get('s', 'h0') == blob                              # a read refreshes h0, making h1 the LRU entry
    cache.put('s', 'h2', blob)
    stats = cache.stats()
    assert stats['bytes'] <= 2000 and stats['evictions'] == 1 and stats['entries'] == 2
    assert cache.get('s', 'h1') is None
    assert cache.get('s', 'h0') == blob and cache.get('s', 'h2') == blob
    assert not cache.put('s', 'huge', 'y' * 5000)                    # bigger than the whole bound: refused
    assert cache.stats()['bytes'] <= 2000


def test_invalidate_clear_and_atomic_writes(tmp_path):
    cache = AnalysisCache(tmp_path)
    cache.put('a', '1', 1)
    cache.put('a', '2', 2)
    cache.put('b', '1', 3)
    assert cache.invalidate('a') == 2 and cache.get('b', '1') == 3
    (cache.dir / 'x.json').write_text('{not json')                   # corrupt entry reads as a miss, not an error
    assert cache.clear() >= 2 and cache.stats()['entries'] == 0
    cache.put('a', '1', 1)
    assert not list(cache.dir.glob('*.tmp'))                         # temp files never left behind
    assert settings_hash({'a': 1, 'b': 2}) == settings_hash({'b': 2, 'a': 1})
