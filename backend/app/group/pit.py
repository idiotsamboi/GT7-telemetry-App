"""Host-side pit-stop detection and the learned pit-loss/refuel-rate estimates
built from it (docs/AI_CONTEXT.md 2.5).

Detection prefers a v3 model's own pit-lane polyline when one exists. None of
the current offline models have one yet - build_model() always emits an empty
pit.points list - so in practice this always uses the heuristic fallback today;
the polyline path is here so a future survey pass is picked up automatically.

The heuristic: sustained low speed, near the start/finish region, away from a
mapped corner. The original design also wanted "not a slow corner" measured
against a per-station reference speed - no such data exists anywhere in the
v3 model (build_model never computes one), so a known corner region (already
available from the same auto-detected corners TrackService.corner_at uses) is
used as the nearest real substitute rather than inventing a reference speed.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

SLOW_KMH = 90.0
SLOW_SUSTAINED_S = 4.0
NEAR_START_FINISH_M = 60.0
PIT_LANE_RADIUS_M = 12.0
STATIONARY_KMH = 2.0
STOP_MIN_DURATION_S = 8.0
FUEL_STOP_MIN_L = 1.0
MAX_STOPS_PER_SESSION = 256


def _distance_to_polyline(position: Any, points: list[list[float]]) -> float | None:
    if not points or not position or len(position) < 3 or position[0] is None or position[2] is None:
        return None
    x, z = position[0], position[2]
    best = None
    for a, b in zip(points, points[1:]):
        vx, vz = b[0] - a[0], b[2] - a[2]
        norm = vx * vx + vz * vz
        t = 0.0 if norm < 1e-9 else max(0.0, min(1.0, ((x - a[0]) * vx + (z - a[2]) * vz) / norm))
        ex, ez = x - (a[0] + t * vx), z - (a[2] + t * vz)
        d = math.hypot(ex, ez)
        if best is None or d < best:
            best = d
    return best


def _in_corner(s: float, corners: list[dict[str, Any]] | None) -> bool:
    for corner in corners or ():
        start, end = corner["s_start"], corner["s_end"]
        if (start <= s <= end) if start <= end else (s >= start or s <= end):
            return True
    return False


def detect(
    position: Any,
    speed_kmh: float | None,
    s: float | None,
    length: float | None,
    pit_points: list[list[float]] | None,
    corners: list[dict[str, Any]] | None,
    slow_since_s: float,
) -> tuple[bool, bool]:
    """(in_pit, inferred) for one instant. inferred=False only via a surveyed pit lane."""
    near = _distance_to_polyline(position, pit_points) if pit_points else None
    if pit_points and near is not None:
        return near <= PIT_LANE_RADIUS_M, False
    if s is None or length is None or speed_kmh is None:
        return False, True
    near_start_finish = min(s, length - s) <= NEAR_START_FINISH_M
    in_pit = speed_kmh < SLOW_KMH and slow_since_s >= SLOW_SUSTAINED_S and near_start_finish and not _in_corner(s, corners)
    return in_pit, True


@dataclass
class _EntryState:
    in_pit: bool = False
    inferred: bool = True
    entered_t: float | None = None
    slow_since: float | None = None
    last_t: float | None = None
    stationary_s: float = 0.0
    fuel_before: float | None = None
    lap_at_entry: int | None = None


class PitTracker:
    """Per-group pit-stop detector: one _EntryState per entry_id."""

    def __init__(self) -> None:
        self.state: dict[str, _EntryState] = {}

    def is_in_pit(self, entry_id: str) -> bool:
        st = self.state.get(entry_id)
        return bool(st and st.in_pit)

    def consume(
        self,
        entry_id: str,
        T: float,
        *,
        position: Any,
        speed_kmh: float | None,
        s: float | None,
        length: float | None,
        lap: int | None,
        fuel: float | None,
        pit_points: list[list[float]] | None,
        corners: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        """One sample for one entry. Returns a completed stop record on exit, else None."""
        st = self.state.setdefault(entry_id, _EntryState())
        dt = (T - st.last_t) if st.last_t is not None and T > st.last_t else 0.0
        st.last_t = T
        if speed_kmh is not None and speed_kmh < SLOW_KMH:
            st.slow_since = st.slow_since if st.slow_since is not None else T
        else:
            st.slow_since = None
        slow_since_s = (T - st.slow_since) if st.slow_since is not None else 0.0
        in_pit_now, inferred = detect(position, speed_kmh, s, length, pit_points, corners, slow_since_s)
        stop = None
        if in_pit_now and not st.in_pit:
            st.in_pit = True
            st.inferred = inferred
            st.entered_t = T
            st.fuel_before = fuel
            st.lap_at_entry = lap
            st.stationary_s = 0.0
        elif in_pit_now and st.in_pit:
            if speed_kmh is not None and speed_kmh < STATIONARY_KMH:
                st.stationary_s += dt
            if st.fuel_before is None and fuel is not None:
                st.fuel_before = fuel
        elif not in_pit_now and st.in_pit:
            duration = (T - st.entered_t) if st.entered_t is not None else 0.0
            fuel_added = (fuel - st.fuel_before) if fuel is not None and st.fuel_before is not None else None
            if duration >= STOP_MIN_DURATION_S or (fuel_added is not None and fuel_added >= FUEL_STOP_MIN_L):
                stop = {
                    "entry_id": entry_id,
                    "lap": st.lap_at_entry,
                    "t_in": st.entered_t,
                    "t_out": T,
                    "fuel_before": st.fuel_before,
                    "fuel_after": fuel,
                    "inferred": st.inferred,
                    "stationary_s": round(st.stationary_s, 1),
                }
            st.in_pit = False
            st.entered_t = None
        return stop


def learned_pit_loss(stops: list[dict[str, Any]], laps_by_entry: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Median (pit_lap + next_lap - 2*median_clean_lap) over every stop with both
    laps available, in seconds. None below one usable stop (never a guess of one)."""
    samples = []
    for stop in stops:
        laps = laps_by_entry.get(stop["entry_id"], [])
        pit_lap = next((l for l in laps if l.get("number") == stop["lap"] and l.get("comparable")), None)
        next_lap = next((l for l in laps if l.get("number") == stop["lap"] + 1 and l.get("comparable")), None)
        clean = [l["duration_ms"] for l in laps if l.get("comparable") and l is not pit_lap and l is not next_lap]
        if pit_lap and next_lap and clean:
            baseline = statistics.median(clean)
            samples.append((pit_lap["duration_ms"] + next_lap["duration_ms"] - 2 * baseline) / 1000)
    if not samples:
        return None
    return {"seconds": round(statistics.median(samples), 1), "source": f"learned ({len(samples)} stop{'s' if len(samples)!=1 else ''})"}


def learned_refuel_rate(stops: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Median litres/second added while stationary during a stop. None without data."""
    samples = []
    for stop in stops:
        added = stop["fuel_after"] - stop["fuel_before"] if stop.get("fuel_after") is not None and stop.get("fuel_before") is not None else None
        stationary = stop.get("stationary_s") or 0
        if added is not None and added > 0 and stationary > 0:
            samples.append(added / stationary)
    if not samples:
        return None
    return {"litres_per_second": round(statistics.median(samples), 3), "source": f"learned ({len(samples)} stop{'s' if len(samples)!=1 else ''})"}
