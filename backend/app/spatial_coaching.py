"""Spatial per-lap timing trace and corner-loss coaching (docs/AI_CONTEXT.md
section 8, live path only - see the module docstring note at the bottom on
scope). Every distance in metres is a position along the locked v3 layout
(track_service.TrackService); nothing here runs unless a lap is locked.
Coaching is correlation with a reference lap, not proof of cause, and every
template says so; braking analysis compares speed and pedal timing only -
never wear, grip or anything not directly measured.
"""
from __future__ import annotations

import math
from array import array
from collections import deque
from dataclasses import dataclass, field
from typing import Any

BIN_M = 10.0
MIN_CORNER_LOSS_S = 0.05
ONSET_DIFF_M = 8.0
MIN_SPEED_DIFF_KMH = 3.0
THROTTLE_DIFF_M = 10.0
BRAKE_ONSET = 0.10
BRAKE_RELEASE = 0.05
MIN_EPISODE_DURATION_S = 0.25
MIN_ENTRY_KMH = 50.0
EXIT_DISTANCE_M = 50.0
COACHING_MIN_LOSS_S = 0.05
MAX_ITEMS = 3


class SpatialLap:
    """A closed lap's elapsed-time/speed/pedal trace indexed by 10m bins along
    the locked layout. NaN means "never visited this bin" (never a guess)."""

    def __init__(self, length_m: float, layout_id: str, car_id: int | None) -> None:
        self.length_m = length_m
        self.layout_id = layout_id
        self.car_id = car_id
        n = max(1, math.ceil(length_m / BIN_M))
        self.times = array("f", [float("nan")] * n)
        self.speed_min = array("f", [float("nan")] * n)
        self.brake_max = array("f", [0.0] * n)
        self.throttle_max = array("f", [0.0] * n)

    def _bin(self, s: float) -> int:
        return max(0, min(len(self.times) - 1, int(s // BIN_M)))

    def record(self, s: float, elapsed_s: float, speed_kmh: float | None, brake: float | None, throttle: float | None) -> None:
        i = self._bin(s)
        if math.isnan(self.times[i]):
            self.times[i] = elapsed_s
        if speed_kmh is not None and (math.isnan(self.speed_min[i]) or speed_kmh < self.speed_min[i]):
            self.speed_min[i] = speed_kmh
        if brake is not None:
            self.brake_max[i] = max(self.brake_max[i], brake)
        if throttle is not None:
            self.throttle_max[i] = max(self.throttle_max[i], throttle)

    def time_at(self, s: float) -> float | None:
        """Interpolated elapsed time at s, or None if that bin was never visited."""
        s = s % self.length_m
        pos = s / BIN_M
        lo = min(len(self.times) - 1, int(pos))
        hi = min(lo + 1, len(self.times) - 1)
        a = self.times[lo]
        if math.isnan(a):
            return None
        b = self.times[hi]
        if hi == lo or math.isnan(b):
            return a
        return a + (b - a) * (pos - lo)

    def to_json(self) -> dict[str, Any]:
        return {
            "layout_id": self.layout_id, "car_id": self.car_id, "length_m": round(self.length_m, 1),
            "times": [None if math.isnan(x) else round(x, 3) for x in self.times],
            "speed_min_kmh": [None if math.isnan(x) else round(x, 1) for x in self.speed_min],
            "brake_max": [round(x, 2) for x in self.brake_max],
            "throttle_max": [round(x, 2) for x in self.throttle_max],
        }


@dataclass
class BrakingEpisode:
    s_onset: float
    lap: int | None
    entry_kmh: float | None
    s_peak: float = 0.0
    peak_brake: float = 0.0
    s_apex: float = 0.0
    min_kmh: float | None = None
    s_release: float | None = None
    s_throttle: float | None = None
    exit_kmh: float | None = None
    duration_s: float = 0.0
    _onset_t: float = field(default=0.0, repr=False)
    _release_t: float | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class LiveBrakingTracker:
    """Per-sample braking-episode detector with track position, for the live
    coaching path. analytics.braking_episodes() covers recorded analysis
    separately, using stored raw position rather than a live v3 lock.

    An episode stays open past brake release to find s_throttle and exit_kmh
    50m further on (docs/AI_CONTEXT.md 8.2); a fresh braking onset before that
    resolves just closes it early with whatever was captured.
    """

    def __init__(self) -> None:
        self.active: BrakingEpisode | None = None
        self.episodes: deque[dict[str, Any]] = deque(maxlen=20)

    def observe(self, t: float, s: float | None, speed_kmh: float | None, brake: float | None, throttle: float | None, lap: int | None) -> dict[str, Any] | None:
        if s is None or brake is None:
            return None
        if brake >= BRAKE_ONSET and self.active is None:
            self.active = BrakingEpisode(s_onset=s, lap=lap, entry_kmh=speed_kmh, s_peak=s, peak_brake=brake, s_apex=s, min_kmh=speed_kmh, _onset_t=t)
            return None
        if self.active is None:
            return None
        ep = self.active
        if brake > ep.peak_brake:
            ep.peak_brake, ep.s_peak = brake, s
        if speed_kmh is not None and (ep.min_kmh is None or speed_kmh < ep.min_kmh):
            ep.min_kmh, ep.s_apex = speed_kmh, s
        if ep.s_release is None and brake < BRAKE_RELEASE:
            ep.s_release, ep._release_t = s, t
        if ep.s_release is not None and ep.s_throttle is None and throttle is not None and throttle > 0.2:
            ep.s_throttle = s
        finalize = False
        if ep.s_throttle is not None and s - ep.s_throttle >= EXIT_DISTANCE_M:
            ep.exit_kmh = speed_kmh
            finalize = True
        elif ep.s_release is not None and brake >= BRAKE_ONSET and s != ep.s_onset:
            finalize = True  # braking again before exit resolved - close with what we have
        if not finalize:
            return None
        self.active = None
        if ep.s_release is None:
            return None
        ep.duration_s = ep._release_t - ep._onset_t
        if ep.duration_s < MIN_EPISODE_DURATION_S or ep.entry_kmh is None or ep.entry_kmh < MIN_ENTRY_KMH:
            return None
        record = ep.to_dict()
        self.episodes.appendleft(record)
        return record


def corner_for(s_onset: float, length_m: float, corners: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The locked model's corner whose [s_start-200, s_apex] window contains
    s_onset, or None (reported as an unassigned braking zone, never guessed)."""
    for c in corners or ():
        start = (c["s_start"] - 200) % length_m
        end = c["s_apex"] % length_m
        if start <= end:
            if start <= s_onset <= end:
                return c
        elif s_onset >= start or s_onset <= end:
            return c
    return None


def corner_label(corner: dict[str, Any] | None) -> str:
    if not corner:
        return "braking zone"
    if corner.get("source") == "auto":
        return f"Turn {corner['id'].lstrip('T')}" if corner.get("id", "").startswith("T") else f"Turn {corner['id']}"
    return corner.get("name") or corner.get("id") or "corner"


def _segment_loss(lap: SpatialLap, ref: SpatialLap, a: float, b: float) -> float | None:
    """(lap - ref) elapsed-time delta over [a, b], skipping any window that
    wraps the start/finish line (elapsed time isn't continuous across it)."""
    if a > b:
        return None
    ta_lap, tb_lap = lap.time_at(a), lap.time_at(b)
    ta_ref, tb_ref = ref.time_at(a), ref.time_at(b)
    if None in (ta_lap, tb_lap, ta_ref, tb_ref) or tb_lap < ta_lap or tb_ref < ta_ref:
        return None
    return (tb_lap - ta_lap) - (tb_ref - ta_ref)


def corner_report(
    lap: SpatialLap, ref: SpatialLap, corners: list[dict[str, Any]], lap_number: int,
    lap_episodes: list[dict[str, Any]], ref_episodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-corner loss/gain evidence items for one completed lap against a
    reference lap of the same layout, ranked by |loss|. Never invents a cause -
    only reports measured onset/min-speed/throttle differences that exceed a
    real threshold, and only when both laps have a matching episode."""
    if lap.layout_id != ref.layout_id or lap.length_m != ref.length_m:
        return []
    items = []
    for corner in corners or ():
        a, b = (corner["s_start"] - 150) % lap.length_m, (corner["s_end"] + 100) % lap.length_m
        loss = _segment_loss(lap, ref, a, b)
        if loss is None or abs(loss) < MIN_CORNER_LOSS_S:
            continue
        label = corner_label(corner)
        ep = next((e for e in lap_episodes if corner_for(e["s_onset"], lap.length_m, corners) is corner), None)
        rep = next((e for e in ref_episodes if corner_for(e["s_onset"], ref.length_m, corners) is corner), None)
        causes = []
        text = None
        confidence = "moderate" if ep and rep else "low"
        if loss < 0:
            # A gain needs no cause attribution - just acknowledge and move on.
            text = f"{label}: {abs(loss):.1f} s quicker than reference. Keep that."
        elif ep and rep:
            d_onset = ep["s_onset"] - rep["s_onset"]
            d_min = (ep["min_kmh"] or 0) - (rep["min_kmh"] or 0)
            d_throttle = (ep["s_throttle"] - rep["s_throttle"]) if ep.get("s_throttle") is not None and rep.get("s_throttle") is not None else None
            entry_a, entry_b = a, corner["s_apex"] % lap.length_m
            exit_a, exit_b = corner["s_apex"] % lap.length_m, b
            entry_loss = _segment_loss(lap, ref, entry_a, entry_b) if entry_a <= entry_b else None
            exit_loss = _segment_loss(lap, ref, exit_a, exit_b) if exit_a <= exit_b else None
            prefer_entry = entry_loss is not None and (exit_loss is None or abs(entry_loss) >= abs(exit_loss))
            if abs(d_onset) >= ONSET_DIFF_M:
                causes.append(("onset", d_onset))
            if abs(d_min) >= MIN_SPEED_DIFF_KMH:
                causes.append(("min_speed", d_min))
            if d_throttle is not None and abs(d_throttle) >= THROTTLE_DIFF_M:
                causes.append(("throttle", d_throttle))
            if prefer_entry and any(k == "onset" for k, _ in causes):
                text = f"{label}: {loss:.1f} s slower than your reference. You braked {abs(d_onset):.0f} m {'earlier' if d_onset < 0 else 'later'}."
                if any(k == "min_speed" for k, _ in causes):
                    text += f" Minimum speed {abs(d_min):.0f} km/h {'lower' if d_min < 0 else 'higher'}."
            elif any(k == "throttle" for k, _ in causes):
                text = f"{label}: {loss:.1f} s lost on exit. Throttle came in {abs(d_throttle):.0f} m later than your reference."
            elif any(k == "min_speed" for k, _ in causes):
                text = f"{label}: {loss:.1f} s slower than your reference. Minimum speed {abs(d_min):.0f} km/h {'lower' if d_min < 0 else 'higher'}."
        if text is None:
            text = f"{label}: {'quicker' if loss < 0 else 'slower'} than your reference by {abs(loss):.1f} s."
        items.append({
            "id": f"corner:{corner.get('id', label)}", "priority": 3 if loss < 0 else 2, "kind": "corner_loss",
            "corner": label, "lap": lap_number, "loss_s": round(loss, 2), "causes": causes,
            "confidence": confidence, "text": text,
        })
    items.sort(key=lambda i: -abs(i["loss_s"]))
    return items[:MAX_ITEMS]
