"""Per-entry distance-over-time history and the gap math built on it.

Phase 1 of the broadcast/spatial build (docs/AI_CONTEXT.md 2.1-2.4). D (race
distance, in metres, monotonically increasing along a drive) and T (a clock-
corrected common timeline) are computed by the caller per telemetry sample;
this module only stores that series per entry and answers "when was this car
at distance D" - the primitive every gap/interval calculation is built on.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections import deque
from typing import Any


class DistanceHistory:
    """Per-entry bounded (T, D) samples, monotonic in D, decimated to <=5Hz, 180s."""

    MAX_AGE_S = 180.0
    MIN_STEP_S = 0.2

    def __init__(self) -> None:
        self.t: deque[float] = deque()
        self.d: deque[float] = deque()
        self.last_completed_laps: int | None = None

    def clear(self) -> None:
        self.t.clear()
        self.d.clear()

    def add(self, T: float, D: float | None) -> None:
        if D is None:
            return
        if self.t and T - self.t[-1] < self.MIN_STEP_S:
            return
        if self.d and D < self.d[-1] - 5.0:
            # A large backward jump means a reset/teleport, not noise - drop history
            # rather than let a stale, now-meaningless series answer time_at() queries.
            self.clear()
        self.t.append(T)
        self.d.append(max(D, self.d[-1]) if self.d else D)
        while self.t and T - self.t[0] > self.MAX_AGE_S:
            self.t.popleft()
            self.d.popleft()

    def time_at(self, D: float) -> float | None:
        """Timeline value when this car was at distance D; None if outside history.

        Callers computing many lookups against the same entry in one tick should
        avoid the repeated list() conversion here by taking their own list(self.d)
        snapshot once (deque indexing is not O(1)); no caller currently needs that.
        """
        if not self.d or D < self.d[0] or D > self.d[-1]:
            return None
        d = list(self.d)
        t = list(self.t)
        i = bisect_left(d, D)
        if d[i] == D:
            return t[i]
        span = d[i] - d[i - 1]
        if span <= 0:
            return t[i - 1]
        return t[i - 1] + (t[i] - t[i - 1]) * (D - d[i - 1]) / span


def interval(history_ahead: DistanceHistory, T_now: float, D_behind: float) -> float | None:
    """Seconds the behind car is behind the ahead car, at the behind car's current D.

    None if the ahead car's history doesn't cover D_behind (too far back, lapped,
    or simply not enough history yet - never guessed).
    """
    t_ahead = history_ahead.time_at(D_behind)
    if t_ahead is None:
        return None
    return T_now - t_ahead


def gap_uncertainty(uncertainty_ahead_ms: float | None, uncertainty_behind_ms: float | None) -> float:
    """Seconds of uncertainty on an interval() result from both cars' clock uncertainty."""
    a = uncertainty_ahead_ms or 0.0
    b = uncertainty_behind_ms or 0.0
    return math.sqrt(a * a + b * b) / 1000 + 0.05


def is_lapped(D_ahead: float, D_behind: float, length: float) -> bool:
    """True once the gap exceeds half a lap - the two are no longer on comparable
    ground, so an interval() between them would read as laps, not seconds."""
    return bool(length) and length > 0 and (D_ahead - D_behind) > length / 2


def common_timeline(source_utc: float | None, received: float | None, offset_ms: float | None) -> tuple[float, float]:
    """(T, extra_uncertainty_ms) for one sample, clock-corrected when an offset is known."""
    if source_utc is not None and offset_ms is not None:
        return source_utc - offset_ms / 1000, 0.0
    return (received if received is not None else 0.0), 250.0
