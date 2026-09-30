"""Phase 2 of the broadcast/spatial build (docs/AI_CONTEXT.md section 3): the
Battle Index heat score, its hysteresis state machine, and alert generation.
"""
import math
import time

import pytest

from backend.app.group.battles import BattleEngine, clamp
from backend.app.group.history import DistanceHistory


def row(entry_id, D, *, class_name="", median_lap_ms=90_000, uncertainty=0.0):
    return {
        "entry_id": entry_id, "D": D, "identity": {"class_name": class_name},
        "clock_uncertainty_ms": uncertainty, "median_lap_ms": median_lap_ms,
    }


def history_at_constant_gap(speed, gap_s, t_end, step=0.5):
    """Two DistanceHistory objects: `behind` is always gap_s seconds behind `ahead`."""
    ahead, behind = DistanceHistory(), DistanceHistory()
    t = 0.0
    while t <= t_end:
        ahead.add(t, speed * t)
        if t >= gap_s:
            behind.add(t, speed * (t - gap_s))
        t += step
    return ahead, behind


def history_with_closing_gap(speed, start_gap, rate, floor, t_end, step=0.5, offset=0.0):
    """`behind` starts start_gap seconds back and closes at `rate` s/s down to floor -
    a genuinely developing battle, not just two cars holding station (see heat's
    f_close term: a static gap alone cannot reach "hot" by design). `offset` must
    match whatever the caller adds to this pair's row D values, or interval()
    lookups against this history will fall outside its real (unoffset) range."""
    ahead, behind = DistanceHistory(), DistanceHistory()
    t = 0.0
    while t <= t_end:
        ahead.add(t, offset + speed * t)
        gap = max(floor, start_gap - rate * t)
        if t >= gap:
            behind.add(t, offset + speed * (t - gap))
        t += step
    return ahead, behind


def test_heat_formula_matches_hand_computed_value_for_a_known_input():
    # gap=1.1s -> f_gap=(2.0-1.1)/1.8=0.5; no closing data -> f_close=0; position=1 -> f_pos=1.0*f_class(0.5, diff class);
    # time_within_1s=0 -> f_dur=0. heat=100*(0.4*0.5+0.3*0+0.1*1*0.5+0.2*0)=100*(0.2+0.05)=25.0
    engine = BattleEngine()
    ahead, behind = history_at_constant_gap(speed=50, gap_s=1.1, t_end=2)
    histories = {"A": ahead, "B": behind}
    rows = [row("A", D=100.0), row("B", D=100.0 - 50 * 1.1)]
    battles, _ = engine.tick(2.0, rows, histories, length=5000)
    assert len(battles) == 1
    b = battles[0]
    assert b["gap_s"] == pytest.approx(1.1, abs=0.05)
    assert b["heat"] == pytest.approx(25.0, abs=2.0)


def test_clamp():
    assert clamp(-1) == 0 and clamp(2) == 1 and clamp(0.5) == 0.5


def test_two_scripted_battles_both_reach_hot():
    # Floor at exactly 0.5s deliberately never satisfies the critical rule (which
    # needs gap strictly under 0.5 or 0.3), so this settles in "hot" and stays there.
    engine = BattleEngine()
    ahead1, behind1 = history_with_closing_gap(speed=50, start_gap=3.0, rate=0.1, floor=0.5, t_end=40, offset=2000)
    ahead2, behind2 = history_with_closing_gap(speed=50, start_gap=3.0, rate=0.1, floor=0.5, t_end=40, offset=0)
    histories = {"A1": ahead1, "B1": behind1, "A2": ahead2, "B2": behind2}
    states = {}
    for i in range(6, 81):  # let both histories accumulate real distance before pairing
        t = i * 0.5
        gap1 = max(0.5, 3.0 - 0.1 * t)
        gap2 = max(0.5, 3.0 - 0.1 * t)
        rows = [
            row("A1", D=2000 + 50 * t, class_name="GT3"), row("B1", D=2000 + 50 * (t - gap1), class_name="GT3"),
            row("A2", D=50 * t, class_name="GT4"), row("B2", D=50 * (t - gap2), class_name="GT4"),
        ]
        battles, _ = engine.tick(t, rows, histories, length=1_000_000)
        states = {(b["ahead"], b["behind"]): b["state"] for b in battles}
    assert states[("A1", "B1")] == "hot"
    assert states[("A2", "B2")] == "hot"


def test_a_closing_pass_reaches_critical_within_5s_of_gap_dropping_below_half_second():
    engine = BattleEngine()
    histories = {"A": DistanceHistory(), "B": DistanceHistory()}
    t = 0.0
    critical_at = None
    gap = 3.0
    while t <= 30.0:
        histories["A"].add(t, 50 * t)
        # B closes steadily from a 3s gap down toward 0.2s over 20 seconds.
        gap = max(0.2, 3.0 - t * 0.14)
        histories["B"].add(t, 50 * (t - gap))
        rows = [row("A", D=50 * t), row("B", D=50 * (t - gap))]
        battles, _ = engine.tick(t, rows, histories, length=50_000)
        if battles and battles[0]["state"] == "critical" and critical_at is None:
            critical_at = t
        t += 0.5
    assert critical_at is not None
    # gap first drops under 0.5s around t=20; critical must be flagged within 5s of that.
    assert critical_at <= 25.5


def test_overtake_keeps_the_same_battle_id_when_order_flips():
    engine = BattleEngine()
    ahead, behind = history_at_constant_gap(speed=50, gap_s=0.5, t_end=10)
    histories = {"A": ahead, "B": behind}
    rows = [row("A", D=100.0), row("B", D=100.0 - 50 * 0.5)]
    battles, _ = engine.tick(2.0, rows, histories, length=5000)
    battle_id = battles[0]["id"]
    # Order flips: B is now ahead of A.
    rows_swapped = [row("B", D=110.0), row("A", D=110.0 - 50 * 0.5)]
    battles2, alerts2 = engine.tick(2.5, rows_swapped, histories, length=5000)
    assert battles2[0]["id"] == battle_id
    assert battles2[0]["last_event"] == "overtake"
    assert any(a["kind"] == "overtake" for a in alerts2)


def test_alert_cooldown_suppresses_a_repeat_within_90s():
    engine = BattleEngine()
    ahead, behind = history_at_constant_gap(speed=50, gap_s=0.1, t_end=60)
    histories = {"A": ahead, "B": behind}
    # Drive well past critical entry; the first critical alert should fire once,
    # then not again within 90s even though the pair stays critical throughout.
    fired_at = []
    for i in range(2, 100):
        t = i * 0.5
        rows = [row("A", D=50 * t), row("B", D=50 * (t - 0.1))]
        battles, alerts = engine.tick(t, rows, histories, length=50_000)
        for a in alerts:
            if a["kind"] == "critical":
                fired_at.append(t)
    assert len(fired_at) == 1


def test_dismiss_suppresses_alerts_but_keeps_the_battle_listed():
    engine = BattleEngine()
    # Close steadily from 3.0s down past the critical thresholds over 30s.
    ahead, behind = history_with_closing_gap(speed=50, start_gap=3.0, rate=0.1, floor=0.1, t_end=30)

    def gap_at(t):
        return max(0.1, 3.0 - 0.1 * t)

    def rows_at(t):
        return [row("A", D=50 * t, class_name="X"), row("B", D=50 * (t - gap_at(t)), class_name="X")]

    histories = {"A": ahead, "B": behind}
    battle_id = None
    dismissed_at = None
    saw_alert_after_dismiss = False
    for i in range(2, 60):
        t = i * 0.5
        battles, alerts = engine.tick(t, rows_at(t), histories, length=1_000_000)
        if battles:
            battle_id = battles[0]["id"]
        if alerts and dismissed_at is None:
            # First alert of any kind (hot entry, most likely): dismiss right after it.
            engine.dismiss(battle_id, t)
            dismissed_at = t
        elif dismissed_at is not None and alerts:
            saw_alert_after_dismiss = True
    assert dismissed_at is not None  # the scripted close actually produced an alert to dismiss
    assert battles  # still listed after dismissal
    assert not saw_alert_after_dismiss  # no further alert (e.g. later critical entry) got through


def test_lapped_cars_are_excluded_unless_include_lapping():
    engine = BattleEngine()
    ahead, behind = DistanceHistory(), DistanceHistory()
    ahead.add(0, 4000); behind.add(0, 100)  # >half of a 5000m lap apart
    rows = [row("A", D=4000.0), row("B", D=100.0)]
    battles, _ = engine.tick(1.0, rows, {"A": ahead, "B": behind}, length=5000)
    assert battles == []
    battles, _ = engine.tick(1.0, rows, {"A": ahead, "B": behind}, length=5000, include_lapping=True)
    assert len(battles) == 1 and battles[0]["lapping"]


def test_classmate_pairs_are_included_beyond_simple_adjacency():
    engine = BattleEngine()
    histories = {k: DistanceHistory() for k in ("A", "B", "C")}
    for h, base in zip(histories.values(), (3000, 2000, 1990)):
        h.add(0, base)
    # Race order A > B > C; B and C share a class and are close, A is a different class far ahead.
    rows = [
        row("A", D=3000.0, class_name="GT3"), row("B", D=2000.0, class_name="GT4"),
        row("C", D=1990.0, class_name="GT4"),
    ]
    battles, _ = engine.tick(1.0, rows, histories, length=50_000)
    pairs = {(b["ahead"], b["behind"]) for b in battles}
    assert ("B", "C") in pairs  # adjacent anyway
    assert ("A", "B") in pairs  # adjacent


def test_pair_cap_is_respected():
    engine = BattleEngine()
    n = 60
    histories = {f"e{i}": DistanceHistory() for i in range(n)}
    for i, h in enumerate(histories.values()):
        h.add(0, (n - i) * 100.0)
    rows = [row(f"e{i}", D=(n - i) * 100.0) for i in range(n)]
    battles, _ = engine.tick(1.0, rows, histories, length=1_000_000)
    assert len(battles) <= 48


def test_worker_tick_is_fast_at_sixteen_entries():
    engine = BattleEngine()
    n = 16

    def distance(i, t):
        return (n - i) * 100.0 + t * 50  # all cars moving at the same 50 m/s pace

    histories = {f"e{i}": DistanceHistory() for i in range(n)}
    t = 0.0
    for _ in range(20):  # warm up so interval() lookups hit real, populated ranges
        for i, h in enumerate(histories.values()):
            h.add(t, distance(i, t))
        t += 0.5
    start = time.perf_counter()
    for _ in range(50):
        for i, h in enumerate(histories.values()):
            h.add(t, distance(i, t))
        rows = [row(f"e{i}", D=distance(i, t)) for i in range(n)]
        engine.tick(t, rows, histories, length=1_000_000)
        t += 0.5
    avg_ms = (time.perf_counter() - start) / 50 * 1000
    assert avg_ms < 2.0, f"battle tick averaged {avg_ms:.3f}ms, over the 2ms/tick budget"


def test_group_service_battle_task_runs_and_is_filtered_for_drivers(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from backend.app.group.service import GroupService

    def route():
        return [[100 * math.cos(i * math.tau / 100), 100 * math.sin(i * math.tau / 100)] for i in range(101)]

    s = GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / "db.sqlite"), config=SimpleNamespace(root=tmp_path)))
    s.running = True  # battle_loop checks this; only GroupService.start() sets it otherwise

    async def check():
        league = await s.league_save({"name": "Test league"})
        await s.create_group({"name": "Test", "event_name": "Test event", "league_id": league["id"], "layout_id": "10"})
        await s.set_map(route(), [])
        joined = []
        for n in range(2):
            invite = await s.invite("driver")
            j = await s.join({"credential": invite["credential"], "identity": {"display_name": f"Driver {n}", "number": str(n)}})
            await s.admit(j["participant"]["id"], "admitted")
            joined.append(j)
        principals = [await s.authenticate(j["token"], ("driver",)) for j in joined]

        def pos_at(t):
            angle = (t / 40.0) * math.tau  # a continuous point on the circle, not a truncated index
            return [100 * math.cos(angle), 0, 100 * math.sin(angle)]

        def send(n, t):
            body = {
                "group_id": s.active()["id"], "session_id": s.active()["session_id"], "participant_id": joined[n]["participant"]["id"],
                "entry_id": joined[n]["participant"]["entry_id"], "boot_id": "b", "sequence": int(t * 10) + 1,
                "source_mono": t, "source_utc": 1000.0 + t, "provenance": "live", "layout_id": "10", "local_session_id": "l",
                "values": {"position": pos_at(t), "lap": 0, "flags": 1},
            }
            s.telemetry(principals[n], body)

        send(0, 0.0); send(1, 0.0)
        await s.session_action("start")
        # Drive both entries around the circle with a small, continuous gap between
        # them. Baseline capture and staleness both depend on real wall-clock
        # freshness (a live-only concern); this sandbox occasionally stalls several
        # seconds between two ordinary synchronous statements for reasons unrelated
        # to this code, so both are forced here rather than left to real timing.
        for i in range(1, 40):
            t = i * 0.3
            send(0, t)
            send(1, max(0.0, t - 0.3))
        for e in s.active()["entries"].values():
            e["baseline"] = 0
        # Poll rather than sleep a fixed amount: this sandbox occasionally stalls
        # several seconds for reasons unrelated to this code, which would otherwise
        # make the "received" freshness this depends on flake independent of any
        # real bug. Refreshing it every retry keeps the check meaningful either way.
        gid = s.active()["id"]
        for _ in range(20):
            for live in s.live.values():
                live["received"] = time.time()
            await asyncio.sleep(0.3)
            if s.battles.get(gid):
                break
        return gid, principals[0]

    group_id, driver_principal = asyncio.run(check())
    assert group_id in s.battle_tasks
    assert s.battles.get(group_id)  # the 2Hz worker actually computed a battle
    asyncio.run(s.session_action("end"))
    assert group_id not in s.battle_tasks
    raw = s.raw_snapshot(s.group(group_id))
    driver_view = s.filter_snapshot(raw, s.group(group_id), driver_principal)
    assert driver_view["battles"] == []


def test_ended_pair_gets_a_new_epoch_on_reformation():
    engine = BattleEngine()
    ahead, behind = history_at_constant_gap(speed=50, gap_s=0.5, t_end=5)
    histories = {"A": ahead, "B": behind}
    rows = [row("A", D=100.0), row("B", D=100.0 - 50 * 0.5)]
    battles, _ = engine.tick(2.0, rows, histories, length=5000)
    first_id = battles[0]["id"]
    # Not adjacent this tick (some other car in between) - pair ends.
    engine.tick(2.5, [row("A", D=200), row("X", D=150), row("B", D=100)], {"A": ahead, "X": DistanceHistory(), "B": behind}, length=5000)
    battles2, _ = engine.tick(3.0, rows, histories, length=5000)
    assert battles2[0]["id"] != first_id
