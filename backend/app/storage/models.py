"""Read models returned by the storage repositories. Plain dataclasses, JSON-safe via `to_public()`."""
from dataclasses import asdict, dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar('T')

MAX_PAGE = 200


@dataclass(slots=True)
class Page(Generic[T]):
    items: list[T]
    limit: int
    offset: int = 0
    total: int | None = None
    next_cursor: str | None = None      # opaque; pass back as the query's/samples' `cursor`/`after`

    def to_public(self) -> dict:
        return {'items': [i.to_public() if hasattr(i, 'to_public') else i for i in self.items], 'limit': self.limit,
                'offset': self.offset, 'total': self.total, 'next_cursor': self.next_cursor}


@dataclass(slots=True)
class SessionQuery:
    include_archived: bool = False
    provenance: str | None = None       # 'live' | 'demo' | 'import' | ...
    limit: int = 50
    offset: int = 0
    cursor: str | None = None           # keyset cursor from a previous page; wins over offset

    def clamped_limit(self) -> int:
        return max(1, min(int(self.limit), MAX_PAGE))


@dataclass(slots=True)
class SessionSummary:
    """One row of the session list. Built from the sessions index; never loads samples or the report."""
    id: str
    started: str
    ended: str | None
    status: str
    provenance: str
    protected: bool
    archived_at: str | None
    meta: dict[str, Any]
    lap_count: int = 0

    def to_public(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class SessionDetail:
    """Metadata, laps and report; samples are fetched separately (paged, channel-projected)."""
    id: str
    started: str
    ended: str | None
    status: str
    provenance: str
    protected: bool
    archived_at: str | None
    meta: dict[str, Any]
    laps: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None

    def to_public(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class SampleRow:
    record_id: int
    mono: float
    utc: str | None
    values: dict[str, Any]

    def to_public(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class LapSeries:
    """Per-channel downsampled series. Each channel has its own time axis (extrema kept, so peaks survive)."""
    session_id: str
    lap_id: str
    channels: list[str]
    points: int
    source_samples: int
    truncated: bool
    series: dict[str, dict[str, list]]  # channel -> {'t': [mono...], 'v': [value...]}

    def to_public(self) -> dict:
        return asdict(self)
