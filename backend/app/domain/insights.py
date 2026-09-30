"""A coaching/analysis finding in one shape, with adapters from the two existing producers.

Never invents causes: adapters only carry across what `analytics.improvements()` and
`spatial_coaching.corner_report()` actually measured.
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Mapping

Severity = Literal['info', 'notice', 'warning', 'critical']


@dataclass(slots=True)
class Insight:
    id: str
    category: str                                   # 'technique' | 'corner' | ...
    severity: Severity
    title: str
    description: str = ''
    lap: int | None = None
    corner_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    metric: dict[str, Any] | None = None            # {'name', 'value', 'unit'}
    comparison: dict[str, Any] | None = None        # e.g. {'reference': 'reference lap', 'delta_s': 0.31}
    suggested_followup: str | None = None

    def to_public(self) -> dict:
        return asdict(self)


def from_improvement(card: Mapping[str, Any]) -> Insight:
    """`analytics.improvements(laps)` card: {title, observation, laps, confidence, impact_ms, advice, channel}."""
    laps = list(card.get('laps') or [])
    return Insight(
        id=f"improvement:{card.get('channel', card.get('title', ''))}", category='technique', severity='notice',
        title=str(card.get('title', '')), description=str(card.get('observation', '')), lap=laps[-1] if laps else None,
        evidence={'laps': laps, 'confidence': card.get('confidence'), 'channel': card.get('channel'),
                  'impact_ms': card.get('impact_ms')},
        metric={'name': 'affected_laps', 'value': len(laps), 'unit': 'laps'},
        suggested_followup=card.get('advice'))


def from_corner_item(item: Mapping[str, Any]) -> Insight:
    """`spatial_coaching.corner_report(...)` item: {id, priority, kind, corner, lap, loss_s, causes, confidence, text}."""
    loss = item.get('loss_s')
    causes = [{'kind': k, 'value': v} for k, v in (item.get('causes') or [])]
    corner_id = str(item.get('id', ''))
    return Insight(
        id=corner_id or f"corner:{item.get('corner')}", category='corner',
        severity='info' if isinstance(loss, (int, float)) and loss < 0 else 'notice',
        title=str(item.get('corner', '')), description=str(item.get('text', '')), lap=item.get('lap'),
        corner_id=corner_id.removeprefix('corner:') or None,
        evidence={'causes': causes, 'confidence': item.get('confidence'), 'priority': item.get('priority')},
        metric={'name': 'loss_s', 'value': loss, 'unit': 's'},
        comparison={'reference': 'reference lap', 'delta_s': loss})


def from_improvements(cards: Iterable[Mapping[str, Any]]) -> list[Insight]:
    return [from_improvement(c) for c in cards]


def from_corner_report(items: Iterable[Mapping[str, Any]]) -> list[Insight]:
    return [from_corner_item(i) for i in items]
