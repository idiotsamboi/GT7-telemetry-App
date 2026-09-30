"""Clean-air pit advice (docs/AI_CONTEXT.md §12): runs on a driver's own app
when connected to a group that opted in to sharing basic traffic data with
its drivers (GroupConfig.share_traffic_with_drivers). Every number here is an
estimate from connected-group data, never a guarantee, and the text says so.
"""
from __future__ import annotations

import math
from typing import Any

REJOIN_WINDOW_S = 2.0
BATTLE_PENALTY_S = 0.8
MAX_STUCK_LAPS = 3
MAX_K_CAP = 5
MIN_IMPROVEMENT_S = 1.0


def pit_advice(
    *, my_d: float, my_lap_s: float, fuel_l: float, capacity_l: float | None, burn_l_per_lap: float | None,
    reserve_l: float, pit_loss_s: float | None, laps_left: float | None, length_m: float,
    traffic: list[dict[str, Any]],
) -> dict[str, Any]:
    """{'available': False, 'reason': ...} or {'available': True, 'max_k', 'options',
    'recommended_k', 'text'}. Never guesses a pit loss or a lap pace it wasn't given."""
    if not traffic:
        return {"available": False, "reason": "No shared traffic data from this group"}
    if pit_loss_s is None:
        return {"available": False, "reason": "Pit loss is unknown"}
    if not burn_l_per_lap or not my_lap_s:
        return {"available": False, "reason": "Fuel burn rate or lap pace unavailable"}
    max_k = math.floor((fuel_l - reserve_l) / burn_l_per_lap) - 1
    if max_k <= 0:
        return {"available": True, "max_k": 0, "options": [], "recommended_k": 0, "text": "Box this lap: no fuel margin to wait."}
    others_static = [t for t in traffic if not t.get("in_pit") and t.get("median_lap_s")]
    options = []
    # Never consider staying out further than the laps actually left in the
    # race (when known) - without this cap a candidate k could exceed
    # laps_left, and the race would end before that many laps were driven.
    k_cap = min(MAX_K_CAP, max(0, math.floor(laps_left))) if laps_left is not None else MAX_K_CAP
    for k in range(0, min(max_k, k_cap) + 1):
        t_k = k * my_lap_s
        d_me = my_d + k * length_m
        ahead = []
        for t in others_static:
            v_j = length_m / t["median_lap_s"]
            d_j = t["D"] + v_j * (t_k + pit_loss_s)
            rejoin_gap_s = (d_j - d_me) / v_j if v_j else None
            if rejoin_gap_s is not None and 0 < rejoin_gap_s < REJOIN_WINDOW_S:
                ahead.append(t)
        stuck_laps = max(0.0, min(MAX_STUCK_LAPS, (laps_left if laps_left is not None else MAX_STUCK_LAPS) - k))
        cost = sum(max(0.0, t["median_lap_s"] - my_lap_s) * stuck_laps for t in ahead)
        if any(t.get("battle_state") in ("hot", "critical") for t in ahead):
            cost += BATTLE_PENALTY_S
        options.append({"k": k, "cost_s": round(cost, 2), "ahead": [t["entry_id"] for t in ahead], "ahead_detail": ahead})
    now_option, best_option = options[0], min(options, key=lambda o: o["cost_s"])
    recommended_k = best_option["k"] if now_option["cost_s"] - best_option["cost_s"] >= MIN_IMPROVEMENT_S else 0
    if not now_option["ahead_detail"]:
        text = "Box when ready: you rejoin in clear air."
    else:
        # Describe what boxing right now would rejoin into; the recommended lap
        # count is the fix for that, not necessarily still-blocked traffic itself.
        cars = now_option["ahead_detail"][:2]
        pace = max(t["median_lap_s"] - my_lap_s for t in cars)
        battling = any(t.get("battle_state") in ("hot", "critical") for t in cars)
        tags = " and ".join(f"#{t.get('number') or '?'}" for t in cars)
        s = "s" if recommended_k != 1 else ""
        text = f"Boxing now rejoins behind {tags}, about {pace:.1f} s a lap slower{', and they are battling' if battling else ''}."
        if recommended_k > 0:
            text += f" Staying out {recommended_k} lap{s} should give clean air."
    return {"available": True, "max_k": max_k, "options": [{k: v for k, v in o.items() if k != "ahead_detail"} for o in options], "recommended_k": recommended_k, "text": text}
