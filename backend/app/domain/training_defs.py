"""Achievement / Challenge definitions and pure evaluators.

A definition is data plus an `EvaluatorRef` (evaluator id + params). An evaluator is a PURE function
`(summary, params) -> Progress` over a stored session summary dict:
    {'status': 'completed', 'provenance': 'live', 'laps': [{'number', 'duration_ms', 'complete', 'comparable', ...}]}
i.e. what `Store.detail()` / `SessionDetail.to_public()` already return. No I/O, no clocks, no randomness.
"""
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Protocol

from ..core.registry import Registry


@dataclass(frozen=True, slots=True)
class Progress:
    current: float
    target: float
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def met(self) -> bool:
        return self.current >= self.target

    def to_public(self) -> dict:
        return {**asdict(self), 'met': self.met}


class Evaluator(Protocol):
    def __call__(self, summary: Mapping[str, Any], params: Mapping[str, Any]) -> Progress: ...


@dataclass(frozen=True)
class EvaluatorDef:
    id: str
    fn: Evaluator
    description: str = ''


@dataclass(frozen=True)
class EvaluatorRef:
    id: str
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Achievement:
    id: str
    name: str
    description: str
    evaluator: EvaluatorRef
    hidden: bool = False


@dataclass(frozen=True)
class Challenge:
    id: str
    name: str
    description: str
    evaluator: EvaluatorRef
    scope: str = 'session'          # 'session' | 'open'


EVALUATORS: Registry[EvaluatorDef] = Registry('evaluators', public=lambda e: {'id': e.id, 'description': e.description})
ACHIEVEMENTS: Registry[Achievement] = Registry('achievements', public=lambda a: {
    'id': a.id, 'name': a.name, 'description': a.description, 'hidden': a.hidden,
    'evaluator': a.evaluator.id, 'params': dict(a.evaluator.params)})
CHALLENGES: Registry[Challenge] = Registry('challenges', public=lambda c: {
    'id': c.id, 'name': c.name, 'description': c.description, 'scope': c.scope,
    'evaluator': c.evaluator.id, 'params': dict(c.evaluator.params)})


def evaluate(definition: Achievement | Challenge, summary: Mapping[str, Any]) -> Progress:
    evaluator = EVALUATORS.require(definition.evaluator.id)
    return evaluator.fn(summary, definition.evaluator.params)


def evaluate_all(summary: Mapping[str, Any], registry: Registry = ACHIEVEMENTS) -> dict[str, Progress]:
    return {d.id: evaluate(d, summary) for d in registry}


def evaluator(id: str, description: str = '') -> Callable[[Evaluator], Evaluator]:
    def wrap(fn: Evaluator) -> Evaluator:
        EVALUATORS.register(EvaluatorDef(id, fn, description))
        return fn
    return wrap


# ---- evaluators ------------------------------------------------------------------------------------
def _clean(lap: Mapping[str, Any]) -> bool:
    return bool(lap.get('complete') and lap.get('comparable') and lap.get('duration_ms'))


@evaluator('clean_laps', 'Count of complete, comparable, timed laps')
def clean_laps(summary: Mapping[str, Any], params: Mapping[str, Any]) -> Progress:
    laps = [l['number'] for l in summary.get('laps', []) if _clean(l)]
    return Progress(len(laps), params.get('count', 1), {'laps': laps[:20]})


@evaluator('consistent_streak', 'Longest run of consecutive clean laps within a tolerance of the run median')
def consistent_streak(summary: Mapping[str, Any], params: Mapping[str, Any]) -> Progress:
    tolerance = params.get('tolerance_pct', 1.5) / 100
    count = int(params.get('count', 5))
    best: list[int] = []
    run: list[Mapping[str, Any]] = []

    def close(run_laps: list[Mapping[str, Any]]) -> None:
        nonlocal best
        # Trim from the front until the run fits its own median tolerance.
        while len(run_laps) >= 2:
            median = statistics.median(l['duration_ms'] for l in run_laps)
            if all(abs(l['duration_ms'] - median) <= median * tolerance for l in run_laps):
                break
            run_laps = run_laps[1:]
        if len(run_laps) > len(best):
            best = [l['number'] for l in run_laps]

    for lap in summary.get('laps', []):
        if _clean(lap):
            run.append(lap)
            close(list(run))
        else:
            run = []
    return Progress(len(best), count, {'laps': best, 'tolerance_pct': tolerance * 100})


@evaluator('completed_session', 'A finished session that recorded at least one lap')
def completed_session(summary: Mapping[str, Any], params: Mapping[str, Any]) -> Progress:
    provenances = tuple(params.get('provenances', ('live',)))
    done = summary.get('status') == 'completed' and summary.get('provenance') in provenances and bool(summary.get('laps'))
    return Progress(1 if done else 0, 1, {'status': summary.get('status'), 'provenance': summary.get('provenance')})


ACHIEVEMENTS.register(Achievement('first_clean_lap', 'First clean lap', 'Complete a lap that passes the application quality checks.',
                                  EvaluatorRef('clean_laps', {'count': 1})))
ACHIEVEMENTS.register(Achievement('five_consistent_laps', 'Five in a row', 'Five consecutive clean laps within 1.5% of each other.',
                                  EvaluatorRef('consistent_streak', {'count': 5, 'tolerance_pct': 1.5})))
ACHIEVEMENTS.register(Achievement('first_completed_session', 'First session in the books', 'Finish a live session with at least one lap.',
                                  EvaluatorRef('completed_session', {'provenances': ('live',)})))
CHALLENGES.register(Challenge('clean_stint_10', 'Clean stint', 'Ten clean laps in one session.', EvaluatorRef('clean_laps', {'count': 10})))
