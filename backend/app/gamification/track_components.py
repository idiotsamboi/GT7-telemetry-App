"""F016-F019: track-mastery components, corner coverage, discovery levels and mission targeting.

Every value here is CALCULATED application progression from REPORTED per-lap fuel use and stored
training captures. Missing evidence stays None (UNAVAILABLE); nothing is inferred as official GT7 data.
"""
from __future__ import annotations

import math
from statistics import mean, pstdev

MIN_FUEL_LAPS = 3
MAX_FUEL_HISTORY = 20
FUEL_CV_LIMIT = .05          # 5% lap-to-lap fuel spread scores 0
MIN_MISSION_CONFIDENCE = .3
LEVELS = ('Visited', 'Recognized', 'Learning', 'Familiar', 'Strong', 'Mastered')


def _valid_fuel(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def strategy_component(previous_history: list | None, laps: list[dict]) -> dict:
    """F016: fuel-use consistency across comparable laps (CALCULATED from REPORTED fuel level deltas)."""
    history = [v for v in (previous_history or []) if _valid_fuel(v)]
    history += [lap['fuel_used_l'] for lap in laps if lap.get('comparable', True) and lap.get('refuel') is not True and _valid_fuel(lap.get('fuel_used_l'))]
    history = [round(float(v), 4) for v in history][-MAX_FUEL_HISTORY:]
    base = {'provenance': 'CALCULATED', 'source': 'REPORTED per-lap fuel level deltas', 'sample_count': len(history),
            'recent_fuel_l': history, 'method': 'fuel-use spread across comparable laps; no pit-strategy claim'}
    if len(history) < MIN_FUEL_LAPS:
        return {**base, 'score': None, 'confidence': 0.0, 'provenance': 'UNAVAILABLE',
                'reason': 'Needs at least three comparable laps with reported fuel use'}
    cv = pstdev(history) / mean(history)
    return {**base, 'score': round(max(0.0, min(100.0, 100 * (1 - cv / FUEL_CV_LIMIT))), 2),
            'confidence': round(min(.85, len(history) / 20), 3), 'spread_fraction': round(cv, 5)}


def training_component(progress: dict | None) -> dict:
    """F017: stored training-capture completion for the layout (percent of the capture goal)."""
    if not isinstance(progress, dict) or not progress.get('laps_saved'):
        return {'score': None, 'confidence': 0.0, 'provenance': 'UNAVAILABLE', 'reason': 'No training captures for this layout'}
    percent = progress.get('percent')
    if not isinstance(percent, (int, float)) or isinstance(percent, bool) or not math.isfinite(percent):
        return {'score': None, 'confidence': 0.0, 'provenance': 'UNAVAILABLE', 'reason': 'Training progress unreadable'}
    return {'score': round(max(0.0, min(100.0, float(percent))), 2), 'confidence': round(min(1.0, progress['laps_saved'] / 3), 3),
            'provenance': 'CALCULATED', 'laps_saved': progress['laps_saved'], 'complete': bool(progress.get('complete')),
            'source': 'training captures (application-recorded)'}


def corner_coverage(records: list[dict], catalogued) -> dict:
    """F018: sampled corners / catalogued corners; unavailable when the catalogue size is unknown."""
    sampled = sum(1 for c in records if c.get('sample_count', 0) >= 3)
    if not isinstance(catalogued, int) or isinstance(catalogued, bool) or catalogued <= 0:
        return {'available': False, 'sampled': sampled, 'catalogued': None, 'percentage': None,
                'provenance': 'UNAVAILABLE', 'reason': 'Corner catalogue unknown for this layout'}
    return {'available': True, 'sampled': min(sampled, catalogued), 'catalogued': catalogued,
            'percentage': round(100.0 * min(sampled, catalogued) / catalogued, 1), 'provenance': 'CALCULATED'}


def discovery_level(payload: dict, previous_level: str | None = None) -> str:
    """F013/F020: level is monotonic; a falling score never revokes an earned level (hysteresis)."""
    laps = payload.get('lap_count') or 0
    observed = payload.get('observed_component_score')
    overall = payload.get('overall_score')
    confidence = payload.get('confidence') or 0
    level = 'Visited'
    if laps >= 5: level = 'Recognized'
    if laps >= 10: level = 'Learning'
    if laps >= 25 and observed is not None and observed >= 40: level = 'Familiar'
    if laps >= 50 and observed is not None and observed >= 65 and confidence >= .5: level = 'Strong'
    if laps >= 100 and overall is not None and overall >= 85 and confidence >= .7: level = 'Mastered'
    if previous_level in LEVELS and LEVELS.index(previous_level) > LEVELS.index(level):
        return previous_level
    return level


def mission_component(payload: dict) -> str | None:
    """F019: weakest component a stored-lap evaluator can measure (pace -> clean laps, consistency -> streak)."""
    if not payload.get('layout_id') or payload.get('car_id') is None or (payload.get('confidence') or 0) < MIN_MISSION_CONFIDENCE:
        return None
    comps = payload.get('components') or {}
    measurable = {k: comps[k] for k in ('pace', 'consistency') if isinstance(comps.get(k), (int, float))}
    return min(measurable, key=lambda k: (measurable[k], k)) if measurable else None
