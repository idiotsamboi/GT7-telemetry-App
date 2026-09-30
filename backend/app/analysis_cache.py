"""Disposable on-disk cache of analysis results, bounded in size.

Key = (session_id, source_hash, analysis_version, settings_hash). A result is stale by construction when
the session gained samples/laps (source_hash changes), the analysis code changed (analysis_version) or
the relevant settings changed (settings_hash): a stale key simply misses and the entry ages out.
Depends on core + storage only.
"""
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from .core import defaults
from .core.version import ANALYSIS_VERSION


def _digest(*parts: Any, size: int = 32) -> str:
    return hashlib.sha256('\x1f'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:size]


def settings_hash(settings: Any) -> str:
    return _digest(json.dumps(settings, sort_keys=True, default=str), size=16)


def source_hash(store, sid: str) -> str:
    """Cheap fingerprint of a session's stored data: max sample record id, sample count and lap ids (SQL only)."""
    row = store.query('SELECT MAX(id) AS last_id, COUNT(*) AS n FROM samples WHERE session=?', (sid,))[0]
    laps = [r['id'] for r in store.query('SELECT id FROM laps WHERE session=? ORDER BY id', (sid,))]
    return _digest(row['last_id'], row['n'], *laps, size=24)


class AnalysisCache:
    def __init__(self, root: str | Path, max_bytes: int = defaults.ANALYSIS_CACHE_MAX_BYTES):
        self.dir = Path(root) / 'cache' / 'analysis'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.lock = threading.Lock()
        self.hits = self.misses = self.evictions = 0

    def _path(self, session_id: str, src: str, version: int, settings: str) -> Path:
        # Prefix by session so invalidate(session) can find its entries without reading them.
        return self.dir / f'{_digest(session_id, size=16)}-{_digest(session_id, src, version, settings)}.json'

    def get(self, session_id: str, src: str, settings: str = '', version: int = ANALYSIS_VERSION) -> Any | None:
        path = self._path(session_id, src, version, settings)
        try:
            with path.open('r', encoding='utf-8') as f:
                value = json.load(f)['value']
            os.utime(path)                      # LRU: reads refresh recency
        except (OSError, ValueError, KeyError):
            with self.lock:
                self.misses += 1
            return None
        with self.lock:
            self.hits += 1
        return value

    def put(self, session_id: str, src: str, value: Any, settings: str = '', version: int = ANALYSIS_VERSION) -> bool:
        data = json.dumps({'key': [session_id, src, version, settings], 'value': value}, default=str).encode('utf-8')
        if len(data) > self.max_bytes:
            return False
        path = self._path(session_id, src, version, settings)
        tmp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)               # atomic: readers see the old or the new file, never a torn one
        except OSError:
            tmp.unlink(missing_ok=True)
            return False
        self._evict()
        return True

    def _entries(self) -> list[tuple[float, int, Path]]:
        out = []
        for p in self.dir.glob('*.json'):
            try:
                st = p.stat()
            except OSError:
                continue
            out.append((st.st_mtime, st.st_size, p))
        return out

    def _evict(self) -> None:
        with self.lock:
            entries = sorted(self._entries(), key=lambda e: e[0])   # oldest first
            total = sum(e[1] for e in entries)
            for _mtime, size, path in entries:
                if total <= self.max_bytes:
                    break
                try:
                    path.unlink()
                except OSError:
                    continue
                total -= size
                self.evictions += 1

    def invalidate(self, session_id: str) -> int:
        removed = 0
        for p in self.dir.glob(f'{_digest(session_id, size=16)}-*.json'):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def clear(self) -> int:
        removed = 0
        for p in list(self.dir.glob('*.json')) + list(self.dir.glob('.*.tmp')):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def stats(self) -> dict:
        entries = self._entries()
        return {'entries': len(entries), 'bytes': sum(e[1] for e in entries), 'max_bytes': self.max_bytes,
                'hits': self.hits, 'misses': self.misses, 'evictions': self.evictions}
