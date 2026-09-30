"""Tyre heating-rate signal processing (docs/AI_CONTEXT.md section 7): compares
each tyre's smoothed surface temperature against its own historical baseline -
at the same point on track when a v3 layout is locked, or a rolling time
average otherwise - and reports a rate of change. Surface temperature only;
never a wear or grip claim, and the alert text this feeds must not say either.
"""
from __future__ import annotations

from collections import deque
from typing import Any

SAMPLE_HZ = 5.0
SAMPLE_PERIOD_S = 1 / SAMPLE_HZ
EMA_ALPHA = 0.2
BASELINE_BETA = 0.3
BIN_M = 100.0
MIN_BIN_VISITS = 2
ANOMALY_WINDOW_S = 20.0
ANOMALY_MIN_POINTS = 60
FALLBACK_WINDOW_S = 90.0
MIN_DRIVING_KMH = 60.0


def _ols_slope(points: list[tuple[float, float]]) -> float | None:
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    den = sum((x - mean_x) ** 2 for x, _ in points)
    if den <= 1e-9:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / den


class TyreHeatMonitor:
    """One instance per solo runtime; four tyres, indices matching the
    telemetry order (FL, FR, RL, RR)."""

    def __init__(self) -> None:
        self.ema: list[float | None] = [None, None, None, None]
        self.baseline: dict[tuple[str, int, int], float] = {}
        self.visits: dict[tuple[str, int, int], int] = {}
        self.current_bin: dict[int, int] = {}
        self.anomaly_history: list[deque] = [deque() for _ in range(4)]
        self.rolling: list[deque] = [deque() for _ in range(4)]
        self._last_sample_t: float | None = None
        self._method = "time baseline"

    def reset(self) -> None:
        self.__init__()

    def observe(
        self,
        t: float,
        tyres: list[float | None] | None,
        speed_kmh: float | None,
        *,
        active: bool,
        locked: bool,
        s: float | None,
        layout_id: str,
    ) -> dict[str, Any]:
        """One telemetry sample. Internally decimated to ~5Hz; returns the same
        cached result on samples in between (cheap - no work happens then)."""
        if self._last_sample_t is not None and t - self._last_sample_t < SAMPLE_PERIOD_S:
            return self._result()
        self._last_sample_t = t
        if not active or not tyres or (speed_kmh or 0) < MIN_DRIVING_KMH or len(tyres) != 4:
            return self._result()
        bin_index = int(s // BIN_M) if locked and s is not None else None
        self._method = "track-position baseline" if bin_index is not None else "time baseline"
        for i, temp in enumerate(tyres):
            if temp is None or not isinstance(temp, (int, float)):
                continue
            self.ema[i] = temp if self.ema[i] is None else self.ema[i] + EMA_ALPHA * (temp - self.ema[i])
            self.rolling[i].append((t, self.ema[i]))
            while self.rolling[i] and t - self.rolling[i][0][0] > FALLBACK_WINDOW_S:
                self.rolling[i].popleft()
            if bin_index is not None:
                key = (layout_id, i, bin_index)
                previous_bin = self.current_bin.get(i)
                if previous_bin is not None and previous_bin != bin_index:
                    exit_key = (layout_id, i, previous_bin)
                    if exit_key in self.baseline:
                        self.baseline[exit_key] += BASELINE_BETA * (self.ema[i] - self.baseline[exit_key])
                    else:
                        self.baseline[exit_key] = self.ema[i]
                    self.visits[exit_key] = self.visits.get(exit_key, 0) + 1
                self.current_bin[i] = bin_index
                anomaly = None
                if self.visits.get(key, 0) >= MIN_BIN_VISITS and key in self.baseline:
                    anomaly = self.ema[i] - self.baseline[key]
            else:
                mean = sum(v for _, v in self.rolling[i]) / len(self.rolling[i]) if self.rolling[i] else None
                anomaly = (self.ema[i] - mean) if mean is not None else None
            if anomaly is not None:
                self.anomaly_history[i].append((t, anomaly))
                while self.anomaly_history[i] and t - self.anomaly_history[i][0][0] > ANOMALY_WINDOW_S:
                    self.anomaly_history[i].popleft()
        return self._result()

    def _result(self) -> dict[str, Any]:
        rates: list[float | None] = [None] * 4
        anomalies: list[float | None] = [None] * 4
        for i in range(4):
            history = self.anomaly_history[i]
            if history:
                anomalies[i] = history[-1][1]
            if len(history) >= ANOMALY_MIN_POINTS:
                rates[i] = _ols_slope(list(history))
        return {"rates": rates, "anomalies": anomalies, "method": self._method}
