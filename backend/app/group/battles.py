"""Battle Index: per-pair "how close a fight is right now" scoring
(docs/AI_CONTEXT.md section 3). Computed from RAW (undelayed) classification
data at 2Hz so overlays and the broadcast delay apply on top of it exactly
like every other frame; the desk itself reads raw battles directly.

"Battle heat" is a derived score for broadcast purposes, not an official
timing metric - every text template says so.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .history import gap_uncertainty, interval, is_lapped

MAX_PAIRS = 48
GAP_WINDOW_S = 30.0
CLOSING_MIN_POINTS = 10
CLOSING_MIN_SPAN_S = 8.0

FORMING_ENTER = 40.0
FORMING_EXIT = 30.0
HOT_ENTER = 70.0
HOT_EXIT = 55.0
CRITICAL_GAP_S = 0.5
CRITICAL_GAP_HARD_S = 0.3
CRITICAL_SUSTAIN_S = 3.0
CRITICAL_EXIT_GAP_S = 0.8
EXIT_SUSTAIN_S = 5.0

ALERT_COOLDOWN_S = 90.0
DISMISS_S = 300.0

DEFAULT_WEIGHTS = {"gap": 0.40, "close": 0.30, "pos": 0.10, "dur": 0.20}


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _ols_slope(points: list[tuple[float, float]]) -> float | None:
    """OLS slope of y over x; None if fewer than 2 distinct x values."""
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    den = sum((x - mean_x) ** 2 for x, _ in points)
    if den <= 1e-9:
        return None
    num = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return num / den


@dataclass
class PairState:
    battle_id: str
    epoch: int = 0
    gaps: deque = field(default_factory=deque)
    state: str = "forming"
    below_forming_since: float | None = None
    below_hot_since: float | None = None
    above_critical_exit_since: float | None = None
    critical_since: float | None = None
    within_1s_since: float | None = None
    last_ahead: str = ""
    last_behind: str = ""
    last_seen: float = 0.0
    alert_sent: dict[str, float] = field(default_factory=dict)
    last_event: str | None = None
    dismissed_until: float = 0.0


class BattleEngine:
    """Owns all pair state for one group; ids/epochs/hysteresis persist across
    ticks here so the desk sees a stable identity for an ongoing fight."""

    def __init__(self) -> None:
        self.pairs: dict[frozenset, PairState] = {}

    def dismiss(self, battle_id: str, T: float) -> bool:
        for st in self.pairs.values():
            if st.battle_id == battle_id:
                st.dismissed_until = T + DISMISS_S
                return True
        return False

    def find(self, battle_id: str) -> PairState | None:
        return next((st for st in self.pairs.values() if st.battle_id == battle_id), None)

    def tick(
        self,
        T: float,
        rows: list[dict[str, Any]],
        histories: dict[str, Any],
        length: float | None,
        *,
        weights: dict[str, float] | None = None,
        include_lapping: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """rows must already be race-distance ordered (index 0 = leader), with
        every row valid (D not None, not stale, not in pit). Returns (battles, alerts)."""
        weights = weights or DEFAULT_WEIGHTS
        by_id = {r["entry_id"]: i for i, r in enumerate(rows)}
        pairs = list(zip(rows, rows[1:]))
        seen = {(a["entry_id"], b["entry_id"]) for a, b in pairs}
        by_class: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            cls = r["identity"].get("class_name") or ""
            if cls:
                by_class.setdefault(cls, []).append(r)
        for members in by_class.values():
            for a, b in zip(members, members[1:]):
                if (a["entry_id"], b["entry_id"]) not in seen:
                    pairs.append((a, b))
                    seen.add((a["entry_id"], b["entry_id"]))
        pairs = pairs[:MAX_PAIRS]

        battles = []
        alerts = []
        active_keys = set()
        for ahead, behind in pairs:
            A, B = ahead["entry_id"], behind["entry_id"]
            length_ok = bool(length)
            lapping = is_lapped(ahead["D"], behind["D"], length) if length_ok else False
            if lapping and not include_lapping:
                continue
            key = frozenset((A, B))
            active_keys.add(key)
            st = self.pairs.get(key)
            fresh = st is None or st.state == "ended"
            if fresh:
                epoch = (st.epoch + 1) if st else 0
                st = PairState(battle_id=f"{A}:{B}:{epoch}", epoch=epoch, last_ahead=A, last_behind=B)
                self.pairs[key] = st
            elif st.last_ahead == B and st.last_behind == A:
                st.last_event = "overtake"
            st.last_ahead, st.last_behind = A, B
            st.last_seen = T
            history_ahead = histories.get(A)
            gap = interval(history_ahead, T, behind["D"]) if history_ahead else None
            gu = gap_uncertainty(ahead.get("clock_uncertainty_ms"), behind.get("clock_uncertainty_ms"))
            if gap is not None:
                st.gaps.append((T, gap))
            while st.gaps and T - st.gaps[0][0] > GAP_WINDOW_S:
                st.gaps.popleft()
            closing_rate = None
            if len(st.gaps) >= CLOSING_MIN_POINTS and st.gaps[-1][0] - st.gaps[0][0] >= CLOSING_MIN_SPAN_S:
                closing_rate = _ols_slope(list(st.gaps))
            median_lap_s = behind.get("median_lap_ms")
            median_lap_s = median_lap_s / 1000 if median_lap_s else None
            closing_per_lap = closing_rate * median_lap_s if closing_rate is not None and median_lap_s else None
            if gap is not None:
                if gap <= 1.0:
                    if st.within_1s_since is None:
                        st.within_1s_since = T
                elif gap > 1.2:
                    st.within_1s_since = None
            time_within_1s = (T - st.within_1s_since) if st.within_1s_since is not None else 0.0
            position = by_id[B] + 1
            same_class = bool(ahead["identity"].get("class_name")) and ahead["identity"].get("class_name") == behind["identity"].get("class_name")
            confidence = "ok"
            if gap is None:
                heat = 0.0
                confidence = "low"
            else:
                f_gap = clamp((2.0 - gap) / (2.0 - 0.2))
                f_close = clamp(-closing_rate / 0.02) if closing_rate is not None else 0.0
                f_pos = 1.0 if position <= 3 else 0.8 if position <= 6 else 0.6 if position <= 10 else 0.4
                f_class = 1.0 if same_class else 0.5
                f_dur = clamp(time_within_1s / 60)
                heat = 100 * (weights["gap"] * f_gap + weights["close"] * f_close + weights["pos"] * f_pos * f_class + weights["dur"] * f_dur)
                if gu > gap / 2:
                    heat *= 0.5
                    confidence = "low"
            previous_state = st.state
            self._transition(st, heat, gap, closing_rate, T)
            if st.state in ("forming", "hot", "critical"):
                battle = {
                    "id": st.battle_id, "epoch": st.epoch, "state": st.state, "ahead": A, "behind": B,
                    "position": position, "gap_s": round(gap, 2) if gap is not None else None,
                    "gap_uncertainty_s": round(gu, 2), "closing_rate_s_per_s": round(closing_rate, 4) if closing_rate is not None else None,
                    "closing_per_lap_s": round(closing_per_lap, 2) if closing_per_lap is not None else None,
                    "heat": round(heat, 1), "confidence": confidence, "same_class": same_class, "lapping": lapping,
                    "time_within_1s": round(time_within_1s, 1), "last_event": st.last_event,
                }
                battles.append(battle)
                if T >= st.dismissed_until:
                    for kind, priority in self._alert_kinds(st, previous_state):
                        last = st.alert_sent.get(kind, -1e30)
                        if T - last < ALERT_COOLDOWN_S:
                            continue
                        st.alert_sent[kind] = T
                        alerts.append({**battle, "kind": kind, "priority": priority, "created_t": T})
            st.last_event = None
        for key, st in list(self.pairs.items()):
            if key not in active_keys and st.state != "ended":
                st.state = "ended"
        return battles, alerts

    @staticmethod
    def _alert_kinds(st: PairState, previous_state: str) -> list[tuple[str, int]]:
        kinds = []
        if st.state == "hot" and previous_state != "hot":
            kinds.append(("hot", 2))
        if st.state == "critical" and previous_state != "critical":
            kinds.append(("critical", 1))
        if st.last_event == "overtake":
            kinds.append(("overtake", 1))
        return kinds

    @staticmethod
    def _transition(st: PairState, heat: float, gap: float | None, closing_rate: float | None, T: float) -> None:
        critical_now = gap is not None and ((gap < CRITICAL_GAP_S and closing_rate is not None and closing_rate < 0) or gap < CRITICAL_GAP_HARD_S)
        if st.state == "critical":
            if gap is not None and gap > CRITICAL_EXIT_GAP_S:
                if st.above_critical_exit_since is None:
                    st.above_critical_exit_since = T
                elif T - st.above_critical_exit_since >= EXIT_SUSTAIN_S:
                    st.state = "hot" if heat >= HOT_ENTER else "forming"
                    st.above_critical_exit_since = None
            else:
                st.above_critical_exit_since = None
            return
        if critical_now:
            if st.critical_since is None:
                st.critical_since = T
            elif T - st.critical_since >= CRITICAL_SUSTAIN_S:
                st.state = "critical"
                st.critical_since = None
            return
        st.critical_since = None
        if st.state == "hot":
            if heat < HOT_EXIT:
                if st.below_hot_since is None:
                    st.below_hot_since = T
                elif T - st.below_hot_since >= EXIT_SUSTAIN_S:
                    st.state = "forming"
                    st.below_hot_since = None
            else:
                st.below_hot_since = None
            return
        # forming
        if heat >= HOT_ENTER:
            st.state = "hot"
            st.below_forming_since = None
        elif heat < FORMING_EXIT:
            if st.below_forming_since is None:
                st.below_forming_since = T
            elif T - st.below_forming_since >= EXIT_SUSTAIN_S:
                st.state = "ended"
                st.below_forming_since = None
        else:
            st.below_forming_since = None
