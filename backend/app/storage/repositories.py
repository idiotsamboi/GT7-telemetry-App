"""Repository layer over `Store`. It wraps the existing SQL/writer thread; it does not replace them.

Rules: list/get never load samples; samples are paged and channel-projected; every write goes through
the writer queue (bounded, drop-new) and raises `AppError(UNAVAILABLE)` if the queue is full.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Iterable, Protocol

from ..analytics import downsample
from ..core.errors import AppError, ResultCode
from .models import (MAX_PAGE, LapSeries, Page, SampleRow, SessionDetail, SessionQuery, SessionSummary)
from .store import Store

PURGE_CONFIRMATION = 'DELETE ARCHIVED SESSION'
MAX_SAMPLE_PAGE = 10000
MAX_SERIES_SOURCE_ROWS = 200_000


class SessionRepository(Protocol):
    def list(self, query: SessionQuery) -> Page[SessionSummary]: ...
    def get(self, sid: str) -> SessionDetail | None: ...
    def samples(self, sid: str, *, after: int | str | None = None, lap_id: str | None = None,
                channels: Iterable[str] | None = None, limit: int = MAX_SAMPLE_PAGE) -> Page[SampleRow]: ...
    def lap_series(self, sid: str, lap_id: str, channels: Iterable[str], points: int = 600) -> LapSeries: ...
    def update_meta(self, sid: str, meta: dict, protected: bool | None = None) -> None: ...
    def protect(self, sid: str, protected: bool = True) -> None: ...
    def archive(self, sid: str, archived: bool = True) -> None: ...
    def purge(self, sid: str, *, confirm: str) -> bool: ...
    def annotations(self, sid: str, kinds: Iterable[str] | None = None, limit: int = 1000) -> list[dict]: ...


def encode_cursor(*parts: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(list(parts)).encode()).decode()


def decode_cursor(cursor: str) -> list:
    try:
        parts = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, TypeError):
        raise AppError(ResultCode.INVALID_INPUT, 422, 'Invalid cursor') from None
    if not isinstance(parts, list):
        raise AppError(ResultCode.INVALID_INPUT, 422, 'Invalid cursor')
    return parts


class SqliteSessionRepository:
    def __init__(self, store: Store):
        self.store = store

    # ---- reads -------------------------------------------------------------------------------
    def list(self, query: SessionQuery) -> Page[SessionSummary]:
        limit = query.clamped_limit()
        where, args = ['(? OR archived_at IS NULL)'], [int(query.include_archived)]
        if query.provenance:
            where.append('provenance=?')
            args.append(query.provenance)
        total = self.store.query(f'SELECT COUNT(*) AS n FROM sessions WHERE {" AND ".join(where)}', tuple(args))[0]['n']
        page_where, page_args, offset = list(where), list(args), 0
        if query.cursor:
            started, sid = (decode_cursor(query.cursor) + [None, None])[:2]
            page_where.append('(started<? OR (started=? AND id<?))')
            page_args += [started, started, sid]
        else:
            offset = max(0, int(query.offset))
        rows = self.store.query(
            'SELECT id,started,ended,status,provenance,protected,archived_at,meta,'
            '(SELECT COUNT(*) FROM laps WHERE laps.session=sessions.id) AS lap_count '
            f'FROM sessions WHERE {" AND ".join(page_where)} ORDER BY started DESC,id DESC LIMIT ? OFFSET ?',
            (*page_args, limit + 1, offset))
        more = len(rows) > limit
        rows = rows[:limit]
        items = [SessionSummary(id=r['id'], started=r['started'], ended=r['ended'], status=r['status'],
                                provenance=r['provenance'], protected=bool(r['protected']), archived_at=r['archived_at'],
                                meta=json.loads(r['meta']), lap_count=r['lap_count']) for r in rows]
        cursor = encode_cursor(items[-1].started, items[-1].id) if more and items else None
        return Page(items=items, limit=limit, offset=offset, total=total, next_cursor=cursor)

    def get(self, sid: str) -> SessionDetail | None:
        rows = self.store.query('SELECT * FROM sessions WHERE id=?', (sid,))
        if not rows:
            return None
        r = rows[0]
        laps = [json.loads(x['payload']) for x in
                self.store.query('SELECT payload FROM laps WHERE session=? ORDER BY rowid LIMIT 10000', (sid,))]
        return SessionDetail(id=r['id'], started=r['started'], ended=r['ended'], status=r['status'],
                             provenance=r['provenance'], protected=bool(r['protected']), archived_at=r.get('archived_at'),
                             meta=json.loads(r['meta']), laps=laps, report=json.loads(r['report']) if r['report'] else None)

    def samples(self, sid: str, *, after: int | str | None = None, lap_id: str | None = None,
                channels: Iterable[str] | None = None, limit: int = MAX_SAMPLE_PAGE) -> Page[SampleRow]:
        """`after` is a record_id cursor (exclusive). Rows come back in record_id order."""
        limit = max(1, min(int(limit), MAX_SAMPLE_PAGE))
        cursor = int(after) if after not in (None, '') else 0
        wanted = list(channels) if channels is not None else None
        sql, args = 'SELECT id,payload FROM samples WHERE session=? AND id>?', [sid, cursor]
        if lap_id is not None:
            sql += ' AND lap_id=?'
            args.append(lap_id)
        rows = self.store.query(sql + ' ORDER BY id LIMIT ?', (*args, limit + 1))
        more = len(rows) > limit
        out = []
        for r in rows[:limit]:
            payload = json.loads(r['payload'])
            values = payload.get('values') or {}
            if wanted is not None:
                values = {k: values[k] for k in wanted if k in values}
            out.append(SampleRow(record_id=r['id'], mono=payload.get('mono'), utc=payload.get('utc'), values=values))
        return Page(items=out, limit=limit, next_cursor=str(out[-1].record_id) if more and out else None)

    def lap_series(self, sid: str, lap_id: str, channels: Iterable[str], points: int = 600) -> LapSeries:
        channels = list(dict.fromkeys(channels))
        points = max(2, min(int(points), 5000))
        monos: list[float] = []
        columns: dict[str, list] = {c: [] for c in channels}
        cursor: str | None = None
        truncated = False
        while True:
            page = self.samples(sid, after=cursor, lap_id=lap_id, channels=channels)
            for row in page.items:
                monos.append(row.mono)
                for c in channels:
                    columns[c].append(row.values.get(c))
            cursor = page.next_cursor
            if cursor is None:
                break
            if len(monos) >= MAX_SERIES_SOURCE_ROWS:
                truncated = True
                break
        series = {}
        for c in channels:
            rows = [{'mono': m, 'values': {c: v}} for m, v in zip(monos, columns[c])]
            kept = downsample(rows, limit=points, channel=c)     # min AND max per bucket, in time order
            series[c] = {'t': [r['mono'] for r in kept], 'v': [r['values'][c] for r in kept]}
        return LapSeries(session_id=sid, lap_id=lap_id, channels=channels, points=points,
                         source_samples=len(monos), truncated=truncated, series=series)

    def annotations(self, sid: str, kinds: Iterable[str] | None = None, limit: int = 1000) -> list[dict]:
        return self.store.annotations(sid, kinds, limit)

    # ---- writes (queued on the single writer thread) -----------------------------------------
    def _put(self, kind: str, args: Any, flush: bool) -> None:
        if not self.store.put(kind, args):
            raise AppError(ResultCode.UNAVAILABLE, 503, 'Storage queue full')
        if flush:
            self.store.flush()

    def _require(self, sid: str) -> SessionDetail:
        detail = self.get(sid)
        if detail is None:
            raise AppError(ResultCode.NOT_FOUND, 404, 'Unknown session')
        return detail

    def update_meta(self, sid: str, meta: dict, protected: bool | None = None, *, flush: bool = True) -> None:
        current = self._require(sid)
        self._put('metadata', (json.dumps(meta), int(current.protected if protected is None else protected), sid), flush)

    def protect(self, sid: str, protected: bool = True, *, flush: bool = True) -> None:
        current = self._require(sid)
        self._put('metadata', (json.dumps(current.meta), int(protected), sid), flush)

    def archive(self, sid: str, archived: bool = True, *, flush: bool = True) -> None:
        from datetime import datetime, timezone
        self._require(sid)
        self._put('archive', (datetime.now(timezone.utc).isoformat() if archived else None, sid), flush)

    def purge(self, sid: str, *, confirm: str) -> bool:
        """Irreversibly delete an ended, unprotected, archived session. Active sessions are never purged."""
        if confirm != PURGE_CONFIRMATION:
            raise AppError(ResultCode.INVALID_INPUT, 422, f'Type "{PURGE_CONFIRMATION}" to confirm')
        detail = self._require(sid)
        if detail.ended is None:
            raise AppError(ResultCode.INVALID_STATE, 409, 'An active session cannot be purged')
        if detail.protected:
            raise AppError(ResultCode.INVALID_STATE, 409, 'Protected sessions cannot be purged')
        if detail.archived_at is None:
            raise AppError(ResultCode.INVALID_STATE, 409, 'Archive the session before purging it')
        self._put('purge', sid, True)     # the writer re-checks eligibility inside its transaction
        return self.get(sid) is None
