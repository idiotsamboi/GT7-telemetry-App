"""Alerts (what the UI shows) and the declarative form of engineer rules.

The engineer Scheduler stays the SPEECH arbiter. An alert is a visible, acknowledgeable record;
`RuleDef` is the data form of a rule (entry/exit/persistence/cooldown) that the rule engine will consume.
"""
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal

from ..core.registry import Registry

AlertSource = Literal['telemetry', 'race_control', 'engineer', 'network', 'hardware', 'session', 'storage']
AlertSeverity = Literal['info', 'notice', 'warning', 'critical']
SOURCES = ('telemetry', 'race_control', 'engineer', 'network', 'hardware', 'session', 'storage')
SEVERITY_ORDER = {'info': 0, 'notice': 1, 'warning': 2, 'critical': 3}
REOPEN_AFTER_S = 30.0     # an acknowledged alert that fires again after this long is shown again


@dataclass(slots=True)
class Alert:
    id: str
    time: float                              # epoch seconds
    source: AlertSource
    severity: AlertSeverity
    title: str
    message: str = ''
    acknowledged: bool = False
    expires: float | None = None             # epoch seconds; None = until acknowledged/evicted
    action: dict | None = None               # {'command_id': str, 'payload': dict}
    context: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None            # a live alert with the same key is refreshed, not duplicated
    count: int = 1

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f'Unknown alert source {self.source!r}')
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f'Unknown alert severity {self.severity!r}')

    def to_public(self) -> dict:
        return asdict(self)


class AlertCenter:
    """Bounded, thread-safe alert list. Oldest alerts fall off; expired ones are dropped on read."""

    def __init__(self, maxlen: int = 100, clock: Callable[[], float] = time.time):
        self._alerts: deque[Alert] = deque(maxlen=maxlen)
        self._clock = clock
        self._lock = threading.Lock()

    def raise_alert(self, source: AlertSource, severity: AlertSeverity, title: str, message: str = '', *,
                    ttl_s: float | None = None, action: dict | None = None, context: dict | None = None,
                    dedupe_key: str | None = None) -> Alert:
        now = self._clock()
        with self._lock:
            self._expire(now)
            if dedupe_key is not None:
                existing = next((a for a in self._alerts if a.dedupe_key == dedupe_key), None)
                if existing is not None:      # refresh in place; a repeat re-opens an acknowledged alert only if more severe
                    if SEVERITY_ORDER[severity] > SEVERITY_ORDER[existing.severity] or (existing.acknowledged and now - existing.time >= REOPEN_AFTER_S):
                        existing.severity, existing.acknowledged = severity, False      # more severe, or it came back after a quiet spell
                    existing.message, existing.time, existing.count = message, now, existing.count + 1
                    existing.expires = now + ttl_s if ttl_s is not None else existing.expires
                    return existing
            alert = Alert(id=uuid.uuid4().hex, time=now, source=source, severity=severity, title=title, message=message,
                          expires=now + ttl_s if ttl_s is not None else None, action=action, context=context or {},
                          dedupe_key=dedupe_key)
            self._alerts.append(alert)
            return alert

    def acknowledge(self, alert_id: str) -> bool:
        with self._lock:
            for alert in self._alerts:
                if alert.id == alert_id:
                    alert.acknowledged = True
                    return True
        return False

    def acknowledge_all(self) -> int:
        with self._lock:
            pending = [a for a in self._alerts if not a.acknowledged]
            for alert in pending:
                alert.acknowledged = True
            return len(pending)

    def _expire(self, now: float) -> None:
        live = [a for a in self._alerts if a.expires is None or a.expires > now]
        if len(live) != len(self._alerts):
            self._alerts.clear()
            self._alerts.extend(live)

    def active(self, include_acknowledged: bool = False) -> list[Alert]:
        """Most severe first, then newest."""
        with self._lock:
            self._expire(self._clock())
            items = [a for a in self._alerts if include_acknowledged or not a.acknowledged]
        return sorted(items, key=lambda a: (-SEVERITY_ORDER[a.severity], -a.time))

    def to_public(self, include_acknowledged: bool = False) -> list[dict]:
        return [a.to_public() for a in self.active(include_acknowledged)]

    def __len__(self) -> int:
        with self._lock:
            self._expire(self._clock())
            return len(self._alerts)


@dataclass(frozen=True)
class RuleDef:
    """Declarative engineer rule. Mirrors the keys of engineer.RULES (priority 0 = critical .. 3 = coaching)."""
    id: str
    priority: int
    prerequisites: str
    entry: str
    exit: str
    persist_s: float
    cooldown_s: float
    message: str
    evidence: tuple[str, ...] = ()           # channels/values quoted as evidence


RULE_DEFS: Registry[RuleDef] = Registry('rule_defs', public=lambda r: {
    'id': r.id, 'priority': r.priority, 'prerequisites': r.prerequisites, 'entry': r.entry, 'exit': r.exit,
    'persist_s': r.persist_s, 'cooldown_s': r.cooldown_s, 'message': r.message, 'evidence': list(r.evidence)})
