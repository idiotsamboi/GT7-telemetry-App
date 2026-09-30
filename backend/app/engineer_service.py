"""EngineerService boundary.

The UI (and the `engineer.ask` command) talks to this interface and never learns whether an answer came
from rules/templates, the local model selecting evidence, or a future remote model. A remote LLM is NOT
implemented: the interface only permits one later, behind a feature flag and explicit user opt-in.
"""
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .domain.alerts import Alert
from .voice import intent

Confidence = Literal['low', 'moderate', 'high']
AnswerSource = Literal['rules', 'template', 'local_ai_selected', 'local_ai_rephrased']

# Intents that read or write engineer state (answers come from telemetry/session data, not free text).
_DATA_INTENTS = frozenset({'status', 'fuel', 'finish', 'save', 'pit', 'fuel_options', 'last', 'best', 'tyres', 'delta',
                           'loss', 'corner_report', 'compare_braking', 'lap_summary', 'compare'})


@dataclass(slots=True)
class EngineerResponse:
    message: str
    intent: str
    severity: str = 'info'
    category: str = 'answer'
    evidence: dict = field(default_factory=dict)
    related_lap: int | None = None
    related_corner: str | None = None
    recommended_action: dict | None = None      # {'command_id': ..., 'payload': ...} or {'route': ...}
    confidence: Confidence | None = None
    source: AnswerSource = 'rules'
    navigate: str | None = None

    def to_public(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class EngineerBrief:
    status: str
    items: list = field(default_factory=list)
    engine: str = 'Evidence summary'
    reason: str | None = None
    source: AnswerSource = 'template'


class EngineerService(Protocol):
    def ask(self, question: str) -> EngineerResponse: ...
    def brief(self) -> EngineerBrief: ...
    def alerts(self) -> list[Alert]: ...


class RuntimeEngineer:
    """Composes the existing pieces without changing them: `Runtime.execute` (rules/templates + the 100-intent
    catalogue), `local_ai` (evidence selection/rephrase guard), `spatial_coaching` and `clean_air` results."""

    def __init__(self, runtime):
        self.runtime = runtime

    def ask(self, question: str) -> EngineerResponse:
        action, arg = intent(question)
        raw = self.runtime.command(question)
        variation = raw.get('variation')
        coaching = self.runtime.coaching_result or {}
        lap = coaching.get('lap') if action in ('loss', 'corner_report', 'compare_braking') else None
        recommended = {'route': raw['navigate']} if raw.get('navigate') else None
        source: AnswerSource = 'template' if variation else 'rules'
        if self.runtime.local_ai.result.get('engine', '').startswith('Qwen') and self.runtime.settings.local_ai_rephrase and variation:
            source = 'local_ai_rephrased'
        return EngineerResponse(
            message=raw['answer'], intent=raw.get('intent', action), category='answer',
            confidence='moderate' if action in _DATA_INTENTS else None,
            related_lap=lap, related_corner=arg if action == 'corner_report' and isinstance(arg, str) else None,
            recommended_action=recommended, source=source, navigate=raw.get('navigate'))

    def brief(self) -> EngineerBrief:
        result = self.runtime.local_ai.result or {}
        source: AnswerSource = 'local_ai_selected' if str(result.get('engine', '')).startswith('Qwen') else 'template'
        return EngineerBrief(status=result.get('status', 'waiting'), items=list(result.get('items') or []),
                             engine=result.get('engine', 'Evidence summary'), reason=result.get('reason'), source=source)

    def alerts(self) -> list[Alert]:
        return self.runtime.alerts.active()

    def career_brief(self) -> dict:
        """Structured stored evidence, called by the local HTTP worker, never the receiver or speech loop."""
        return self.runtime.career_repository.engineer()
