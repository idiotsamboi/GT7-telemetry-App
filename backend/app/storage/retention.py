"""Retention selection. Pure: decides WHICH sessions to archive; the caller archives them (never purges).

Hard guarantees: protected sessions and active sessions (`ended` is NULL) are never selected, whatever
the age or size pressure. Selection is oldest first.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ..core import defaults

GB = 1024 ** 3


@dataclass(frozen=True)
class RetentionPolicy:
    days: int = defaults.RETENTION_DAYS
    max_bytes: int | None = None
    protect_favourites: bool = True         # meta.favourite / meta.favorite also counts as protected

    @classmethod
    def from_settings(cls, days: int, max_storage_gb: float | None = None, protect_favourites: bool = True) -> 'RetentionPolicy':
        return cls(days=days, max_bytes=int(max_storage_gb * GB) if max_storage_gb else None,
                   protect_favourites=protect_favourites)


def _epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def is_eligible(session: Mapping, policy: RetentionPolicy) -> bool:
    if session.get('ended') is None or session.get('protected') or session.get('archived_at'):
        return False
    meta = session.get('meta') or {}
    if policy.protect_favourites and (meta.get('favourite') or meta.get('favorite')):
        return False
    return True


def select_for_archive(sessions: Iterable[Mapping], policy: RetentionPolicy, now: float | datetime, db_bytes: int = 0) -> list[str]:
    """Session ids to archive: older than `policy.days`, plus (only if the database exceeds
    `policy.max_bytes`) the oldest remaining eligible sessions until the estimated excess is covered.
    A session's size is its `bytes` key when known, else an even share of `db_bytes`."""
    sessions = list(sessions)
    now_s = _epoch(now)
    dated = []
    for s in sessions:
        started = _epoch(s.get('started'))
        if started is not None and is_eligible(s, policy):
            dated.append((started, s))
    dated.sort(key=lambda pair: pair[0])
    share = db_bytes / len(sessions) if sessions else 0
    cutoff = now_s - policy.days * 86400
    selected: list[str] = []
    freed = 0.0
    remaining = []
    for started, s in dated:
        if started < cutoff:
            selected.append(s['id'])
            freed += s.get('bytes') or share
        else:
            remaining.append(s)
    if policy.max_bytes is not None and db_bytes - freed > policy.max_bytes:
        for s in remaining:
            if db_bytes - freed <= policy.max_bytes:
                break
            selected.append(s['id'])
            freed += s.get('bytes') or share
    return selected
