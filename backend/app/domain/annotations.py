"""One typed timeline entry for a session (incident, flag, pit, radio, bookmark, ...).

Stored in the `events` table with `kind` set (migration 003); old untyped engineer decisions
(`kind` NULL) are converted on read by `from_decision_event`.
"""
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, get_args

Kind = Literal['incident', 'flag', 'pit', 'radio', 'user_marker', 'engineer_alert', 'system',
               'race_control', 'lap_boundary', 'bookmark']
Severity = Literal['info', 'notice', 'warning', 'critical']
KINDS: tuple[str, ...] = get_args(Kind)
SEVERITIES: tuple[str, ...] = get_args(Severity)

# Engineer priorities: 0 critical (spoken immediately) .. 3 coaching/info.
_PRIORITY_SEVERITY: tuple[Severity, ...] = ('critical', 'warning', 'notice', 'info')
# runtime.decision categories -> annotation kind. Anything unlisted is an engineer alert.
_CATEGORY_KIND: dict[str, str] = {
    'annotation': 'user_marker', 'bookmark': 'bookmark', 'lap': 'lap_boundary', 'box': 'pit', 'pit': 'pit',
    'answer': 'radio', 'radio': 'radio', 'connection': 'system', 'disk': 'system', 'recording': 'system',
    'incident': 'incident', 'flag': 'flag', 'race_control': 'race_control',
}


@dataclass(slots=True)
class Annotation:
    id: str
    session_id: str | None
    kind: Kind
    mono: float | None = None
    utc: float | None = None            # epoch seconds
    lap: int | None = None
    distance_m: float | None = None
    severity: Severity = 'info'
    source: str = ''
    message: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f'Unknown annotation kind {self.kind!r}')
        if self.severity not in SEVERITIES:
            raise ValueError(f'Unknown severity {self.severity!r}')

    @classmethod
    def new(cls, session_id: str | None, kind: Kind, message: str = '', **fields: Any) -> 'Annotation':
        fields.setdefault('utc', datetime.now(timezone.utc).timestamp())
        return cls(id=uuid.uuid4().hex, session_id=session_id, kind=kind, message=message, **fields)

    def to_public(self) -> dict:
        return asdict(self)

    def to_event_row(self) -> tuple[str | None, str | None, str, str]:
        """Args for the writer's `annotation` job: (session, utc ISO text, payload JSON, kind)."""
        stamp = datetime.fromtimestamp(self.utc, timezone.utc).isoformat() if self.utc is not None else None
        return (self.session_id, stamp, json.dumps(asdict(self)), self.kind)

    @classmethod
    def from_event_row(cls, row: Mapping[str, Any]) -> 'Annotation':
        """Inverse of to_event_row for a row shaped like the events table ({'payload','kind','session','utc'})
        or a `Store.annotations()` item. Untyped rows (kind NULL) go through `from_decision_event`."""
        payload = row.get('payload', row)
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)
        if row.get('kind') is None and 'category' in payload:
            legacy = from_decision_event(payload)
            legacy.session_id = legacy.session_id or row.get('session')
            legacy.utc = legacy.utc if legacy.utc is not None else _epoch(row.get('utc'))
            return legacy
        known = {k: payload[k] for k in ('id', 'session_id', 'mono', 'utc', 'lap', 'distance_m', 'severity', 'source',
                                         'message', 'metadata') if k in payload}
        known.setdefault('session_id', row.get('session'))
        known.setdefault('id', str(row.get('id') or row.get('event_id') or uuid.uuid4().hex))
        return cls(kind=row.get('kind') or payload['kind'], **known)


def _epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def from_decision_event(event: Mapping[str, Any]) -> Annotation:
    """Convert an engineer decision event (`runtime.decision`: asdict(engineer.Event) + decision/reason/utc)."""
    category = str(event.get('category') or '')
    priority = event.get('priority', 2)
    severity = _PRIORITY_SEVERITY[priority] if isinstance(priority, int) and 0 <= priority <= 3 else 'notice'
    evidence = event.get('evidence') or {}
    lap = evidence.get('lap')
    return Annotation(
        id=str(event.get('id') or uuid.uuid4().hex), session_id=event.get('session'),
        kind=_CATEGORY_KIND.get(category, 'engineer_alert'),        # type: ignore[arg-type]
        mono=event.get('timestamp'), utc=_epoch(event.get('utc')), lap=lap if isinstance(lap, int) else None,
        distance_m=evidence.get('distance_m'), severity=severity, source='engineer', message=str(event.get('message') or ''),
        metadata={'category': category, 'decision': event.get('decision'), 'reason': event.get('reason'),
                  'requested': bool(event.get('requested')), 'evidence': evidence})
