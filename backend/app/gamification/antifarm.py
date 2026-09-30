"""F098: pure anti-farming detectors. Each returns (factor 0..1, reason); 1.0 means no reduction.

Calculated application heuristics only; they are not official game data and are not yet wired into XP.
"""
from __future__ import annotations

from typing import Iterable, Sequence


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def duplicate_source(ids: Iterable[str]) -> tuple[float, str]:
    """Reduce when the same source id is submitted more than once."""
    items = list(ids)
    if not items:
        return 1.0, 'no_sources'
    distinct = len(set(items))
    if distinct == len(items):
        return 1.0, 'unique_sources'
    return _clamp(distinct / len(items)), f'duplicate_sources:{len(items) - distinct}'


def repeated_identical(values: Sequence[float | int], window: int = 5) -> tuple[float, str]:
    """Reduce to zero when the trailing `window` values are all identical (loop signature)."""
    if window < 2:
        raise ValueError('window must be at least 2')
    items = list(values)
    if len(items) < window:
        return 1.0, 'insufficient_history'
    if len(set(items[-window:])) == 1:
        return 0.0, f'identical_last_{window}'
    return 1.0, 'varied_values'


def low_information(laps: Sequence[float | int], min_distinct: int = 3) -> tuple[float, str]:
    """Reduce when lap durations carry too few distinct values to be independent evidence."""
    items = list(laps)
    if min_distinct < 1:
        raise ValueError('min_distinct must be positive')
    if not items:
        return 0.0, 'no_laps'
    distinct = len(set(items))
    need = min(min_distinct, len(items))
    if distinct >= need:
        return 1.0, 'sufficient_information'
    return _clamp(distinct / need), f'low_information:{distinct}/{need}'


def combined_factor(*results: tuple[float, str]) -> tuple[float, str]:
    """Single helper: multiply factors, join the non-neutral reasons."""
    factor = 1.0
    reasons = []
    for value, reason in results:
        factor *= _clamp(value)
        if value < 1.0:
            reasons.append(reason)
    return round(factor, 4), ','.join(reasons) or 'no_reduction'
