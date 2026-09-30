"""Pure, versioned evidence policy. No official lap-validity or race claims."""
from dataclasses import dataclass
import math
from statistics import mean, pstdev

ALGORITHM_VERSION = 1
MAX_LAPS = 2000
SKILLS = ('consistency', 'pace', 'braking', 'throttle', 'cornering', 'racecraft', 'fuel_management', 'strategy', 'track_knowledge', 'discipline')

@dataclass(frozen=True)
class LevelCurve:
    scale: float = 100
    exponent: float = 1.65
    max_level: int = 100

    def __post_init__(self):
        if not math.isfinite(self.scale) or not math.isfinite(self.exponent) or self.scale < 1 or self.exponent < 1 or not 2 <= self.max_level <= 1000:
            raise ValueError('Invalid level curve')

    def threshold(self, level: int) -> int:
        if not 1 <= level <= self.max_level:
            raise ValueError('Level outside curve')
        return round(self.scale * (level - 1) ** self.exponent)

    def progress(self, total_xp: int) -> dict:
        if total_xp < 0: raise ValueError('XP cannot be negative')
        level = 1
        while level < self.max_level and self.threshold(level + 1) <= total_xp:
            level += 1
        return dict(current=level, total_xp=total_xp, level_start_xp=self.threshold(level),
                    next_level_xp=self.threshold(level + 1) if level < self.max_level else None,
                    max_level=self.max_level)


def update_skill(old_score, old_count: int, observed: float, count: int) -> tuple[float, float, int]:
    """Bound influence to 20 laps per session and 100 past observations."""
    if not math.isfinite(observed) or not 0 <= observed <= 100 or count <= 0:
        raise ValueError('Invalid skill evidence')
    weight = min(count, 20)
    past = min(max(old_count, 0), 100) if old_score is not None else 0
    alpha = min(.2, weight / (past + weight)) if past else 1.0
    score = old_score + alpha * (observed - old_score) if past else observed
    evidence_count = min(1000000, old_count + count)
    return round(score, 2), round(min(1.0, evidence_count / 40), 3), evidence_count


def score_to_grade(score: float | None) -> str | None:
    """Map 0-100 score to motorsport letter grade (S, A, B, C, D)."""
    if score is None or not math.isfinite(score):
        return None
    if score >= 95.0:
        return 'S'
    if score >= 85.0:
        return 'A'
    if score >= 70.0:
        return 'B'
    if score >= 55.0:
        return 'C'
    return 'D'


def evaluate(session: dict, context: dict) -> dict:
    reasons = []
    if session.get('provenance') != 'live': reasons.append('non_live_source')
    if not session.get('ended') or session.get('status') != 'completed': reasons.append('session_not_finalized_completed')
    if context.get('integrity') is False: reasons.append('incomplete_capture')
    laps = session.get('laps', [])
    if not isinstance(laps, list): laps = []; reasons.append('missing_laps')
    if len(laps) > MAX_LAPS or context.get('truncated'): reasons.append('lap_limit_exceeded')
    contexts = context.get('laps', {})
    accepted = []; identities = set(); lap_rejections = []
    comparable = [lap for lap in laps[:MAX_LAPS] if lap.get('comparable') is True]
    for lap in comparable:
        lap_id = lap.get('id')
        evidence = contexts.get(lap_id, {})
        duration = lap.get('duration_ms')
        car = evidence.get('car_id'); layout = evidence.get('layout_id')
        if evidence.get('integrity') is False or evidence.get('identity_state') not in ('locked', 'authoritative') or evidence.get('provenance') != 'live' or not isinstance(layout, str) or not layout.strip() or layout.strip().lower() in ('unknown', 'none', 'unavailable') or isinstance(car, bool) or not isinstance(car, int) or car <= 0:
            reasons.append('missing_authoritative_lap_identity'); continue
        identities.add((layout, car))
        if lap.get('complete') is not True or lap.get('partial') is not False or lap.get('quality') != [] or lap.get('refuel') is not False:
            lap_rejections.append(dict(lap_id=lap_id, reason='incomplete_or_poor_quality')); continue
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 1000 < duration < 3600000:
            lap_rejections.append(dict(lap_id=lap_id, reason='missing_or_invalid_duration')); continue
        accepted.append(lap)
    if len(identities) > 1: reasons.append('mixed_layout_or_car')
    if len(accepted) < 2: reasons.append('insufficient_comparable_laps')
    if len({lap.get('id') for lap in accepted}) != len(accepted): reasons.append('duplicate_lap_evidence')
    reasons = list(dict.fromkeys(reasons))
    evidence = dict(algorithm_version=ALGORITHM_VERSION, comparable_lap_ids=[lap['id'] for lap in accepted],
                    evidence_type='lap_comparison', source='calculated', provenance=session.get('provenance', 'unknown'),
                    session_id=session.get('id'), confidence=round(min(.85, len(accepted)/40), 3),
                    comparable_laps=len(accepted), excluded_laps=lap_rejections, official_validity='unknown',
                    consistency_score=None, session_grade=None, spread_fraction=None, layout_id=None, car_id=None)
    if len(identities) == 1:
        evidence['layout_id'], evidence['car_id'] = next(iter(identities))
    if reasons: return dict(status='excluded', exclusions=reasons, evidence=evidence, rewards=[])
    durations = [lap['duration_ms'] for lap in accepted]
    spread = pstdev(durations) / mean(durations)
    score = round(max(0.0, min(100.0, 100 * (1 - spread / .1))), 2)
    grade = score_to_grade(score)
    evidence.update(consistency_score=score, session_grade=grade, spread_fraction=round(spread, 6))
    # Session cap: 80 XP, with no per-lap runaway or unverifiable PB reward.
    rewards = [dict(category='comparable_practice', amount=min(60, 10 * len(accepted)))]
    if spread <= .02: rewards.append(dict(category='consistency', amount=20))
    return dict(status='eligible', exclusions=[], evidence=evidence, rewards=rewards)
