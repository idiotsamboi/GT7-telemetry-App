"""Net position and pit-window projector (docs/AI_CONTEXT.md section 5): given
each entry's fuel state and gap to the leader, project the running order after
everyone's remaining pit stops, and each entry's own pit window.

Pure math only; GroupService resolves each entry's inputs (fuel, burn rate,
gap to leader, host-entered or learned pit loss/refuel rate) and calls project().
"""
from __future__ import annotations

import math
import statistics
from typing import Any

RESERVE_L_DEFAULT = 1.0
LEARNED_STOP_UNCERTAINTY_FACTOR = 0.15  # applied to stop cost when pit loss is learned from < 3 stops
HOST_STOP_UNCERTAINTY_FACTOR = 0.05  # applied when pit loss is host-entered or learned from >= 3 stops
TIMED_FORMAT_UNCERTAINTY_FACTOR = 0.10  # extra uncertainty in a timed race (lap count itself is an estimate)


def stops_needed(
    fuel_l: float | None, capacity_l: float | None, burn_l_per_lap: float | None, laps_left: float | None,
    reserve_l: float = RESERVE_L_DEFAULT,
) -> tuple[int | None, float | None]:
    """(n_stops, litres_to_add). None, None if the inputs can't support an estimate."""
    if burn_l_per_lap is None or laps_left is None or fuel_l is None:
        return None, None
    need_l = laps_left * burn_l_per_lap + reserve_l
    deficit = need_l - fuel_l
    if deficit <= 0:
        return 0, 0.0
    usable_tank = max(0.001, (capacity_l or 0) - reserve_l)
    return math.ceil(deficit / usable_tank), deficit


def stop_cost_s(n_stops: int, add_l: float, pit_loss_s: float | None, refuel_rate_lps: float | None) -> float | None:
    """Seconds lost to n_stops stops adding add_l litres total. None only if
    pit_loss_s itself is unknown (never guessed); an unknown refuel rate just
    omits refuel time from the estimate rather than blocking it."""
    if n_stops == 0:
        return 0.0
    if pit_loss_s is None:
        return None
    refuel_s = add_l / refuel_rate_lps if refuel_rate_lps else 0.0
    return n_stops * pit_loss_s + refuel_s


def pit_window(
    current_lap: int, laps_total: int | None, fuel_l: float | None, capacity_l: float | None,
    burn_l_per_lap: float | None, reserve_l: float = RESERVE_L_DEFAULT,
) -> tuple[int, int] | None:
    """(open_lap, close_lap) for a one-stop car. None if not computable."""
    if not burn_l_per_lap or laps_total is None or fuel_l is None:
        return None
    close_lap = current_lap + math.floor(max(0.0, fuel_l - reserve_l) / burn_l_per_lap)
    open_lap = max(current_lap, laps_total - math.floor(max(0.0, (capacity_l or 0) - reserve_l) / burn_l_per_lap))
    return open_lap, close_lap


def project(
    entries: list[dict[str, Any]], *, pit_loss: tuple[float, str] | None, refuel_rate: tuple[float, str] | None,
    race_format: str, reserve_l: float = RESERVE_L_DEFAULT,
) -> dict[str, Any] | None:
    """entries: [{entry_id, position, gap_to_leader_s, gap_uncertainty_s, fuel_l,
    capacity_l, burn_l_per_lap, burn_source, laps_left, current_lap, laps_total}].
    pit_loss/refuel_rate: (value, 'host'|'learned') or None if unknown.
    None if this format has no notion of "laps remaining" to project against.
    """
    if race_format not in ("laps", "timed"):
        return None
    rows = []
    any_stop_needed = False
    any_unknown = False
    for e in entries:
        n, add_l = stops_needed(e["fuel_l"], e["capacity_l"], e["burn_l_per_lap"], e["laps_left"], reserve_l)
        base = {"entry_id": e["entry_id"], "position": e.get("position"), "burn_source": e.get("burn_source")}
        if n is None:
            any_unknown = True
            rows.append({**base, "stops": None, "net_gap_s": None, "status": "fuel data unavailable"})
            continue
        any_stop_needed = any_stop_needed or n > 0
        cost = stop_cost_s(n, add_l, pit_loss[0] if pit_loss else None, refuel_rate[0] if refuel_rate else None)
        if n and cost is None:
            rows.append({**base, "stops": n, "net_gap_s": None, "status": "pit loss unknown"})
            continue
        gap = e.get("gap_to_leader_s")
        net_gap = (gap + cost) if gap is not None and cost is not None else None
        unc = e.get("gap_uncertainty_s") or 0.0
        if cost:
            unc += (LEARNED_STOP_UNCERTAINTY_FACTOR if pit_loss and pit_loss[1] == "learned" else HOST_STOP_UNCERTAINTY_FACTOR) * cost
            if race_format == "timed":
                unc += TIMED_FORMAT_UNCERTAINTY_FACTOR * cost
        window = None
        if n == 1:
            window = pit_window(e["current_lap"], e.get("laps_total"), e["fuel_l"], e["capacity_l"], e["burn_l_per_lap"], reserve_l)
        rows.append({
            **base, "stops": n, "net_gap_s": round(net_gap, 1) if net_gap is not None else None,
            "uncertainty_s": round(unc, 1) if net_gap is not None else None, "window": window, "status": None,
        })
    # Only claim "no stops required" when every entry's fuel data was actually
    # known to need zero stops - if any entry's fuel data is unavailable, that's
    # an unknown, not a clean bill of health, so fall through and return every
    # row instead (known entries ranked, unknown ones unranked with their status).
    if not any_stop_needed and not any_unknown:
        return {"entries": [], "summary": "No stops required by current estimates"}
    ranked = sorted((r for r in rows if r["net_gap_s"] is not None), key=lambda r: r["net_gap_s"])
    unranked = [r for r in rows if r["net_gap_s"] is None]
    for i, r in enumerate(ranked):
        r["projected_rank"] = i + 1
        r["change"] = (r["position"] - r["projected_rank"]) if r["position"] is not None else None
        r["close_call"] = False
    for i in range(1, len(ranked)):
        a, b = ranked[i - 1], ranked[i]
        if abs(a["net_gap_s"] - b["net_gap_s"]) < (a["uncertainty_s"] + b["uncertainty_s"]):
            a["close_call"] = b["close_call"] = True
    return {"entries": ranked + unranked, "summary": None}


class FuelBurnTracker:
    """Per-entry host-side fuel-burn-per-lap fallback, used only when a driver
    doesn't report strategy.litres_per_lap themselves. Needs >=3 comparable
    (non-refuel) laps before offering an estimate - never a guess from one lap."""

    def __init__(self) -> None:
        self._at_lap_start: dict[str, tuple[int, float]] = {}
        self._deltas: dict[str, list[float]] = {}

    def observe(self, entry_id: str, lap: int | None, fuel_l: float | None) -> None:
        if lap is None or fuel_l is None:
            return
        prev = self._at_lap_start.get(entry_id)
        if prev is not None and prev[0] == lap - 1 and prev[1] >= fuel_l:
            samples = self._deltas.setdefault(entry_id, [])
            samples.append(prev[1] - fuel_l)
            del samples[:-20]
        if prev is None or prev[0] != lap:
            self._at_lap_start[entry_id] = (lap, fuel_l)

    def burn_l_per_lap(self, entry_id: str) -> float | None:
        samples = self._deltas.get(entry_id) or []
        if len(samples) < 3:
            return None
        return statistics.median(samples)
