"""Phase 5 of the broadcast/spatial build (docs/AI_CONTEXT.md section 5): the
pit/fuel projector's pure math, plus publication gating end to end.
"""
import math
import time

import pytest

from backend.app.group.projection import FuelBurnTracker, pit_window, project, stop_cost_s, stops_needed


def test_stops_needed_zero_when_fuel_already_covers_the_distance_with_reserve():
    n, add = stops_needed(fuel_l=50, capacity_l=100, burn_l_per_lap=2.0, laps_left=20, reserve_l=1.0)
    assert n == 0 and add == 0.0  # needs 41L, has 50L


def test_stops_needed_computes_deficit_and_stop_count():
    # needs 20*3+1=61L, has 10L -> deficit 51L; usable tank 100-1=99L -> ceil(51/99)=1 stop
    n, add = stops_needed(fuel_l=10, capacity_l=100, burn_l_per_lap=3.0, laps_left=20, reserve_l=1.0)
    assert n == 1 and add == pytest.approx(51.0)


def test_stops_needed_multiple_stops_for_a_small_tank():
    # needs 40*2+1=81L, has 5L -> deficit 76L; usable tank 20-1=19L -> ceil(76/19)=4 stops
    n, add = stops_needed(fuel_l=5, capacity_l=20, burn_l_per_lap=2.0, laps_left=40, reserve_l=1.0)
    assert n == 4 and add == pytest.approx(76.0)


def test_stops_needed_none_without_burn_rate_laps_left_or_fuel():
    assert stops_needed(None, 100, 2.0, 10) == (None, None)
    assert stops_needed(10, 100, None, 10) == (None, None)
    assert stops_needed(10, 100, 2.0, None) == (None, None)


def test_stop_cost_is_zero_stops_free_and_none_without_pit_loss():
    assert stop_cost_s(0, 0.0, None, None) == 0.0
    assert stop_cost_s(1, 50.0, None, 1.0) is None  # pit loss unknown -> never guessed


def test_stop_cost_omits_refuel_time_when_rate_unknown_rather_than_blocking():
    assert stop_cost_s(1, 50.0, 25.0, None) == 25.0  # just the pit loss, no refuel time added


def test_stop_cost_includes_pit_loss_and_refuel_time():
    assert stop_cost_s(2, 60.0, 25.0, 2.0) == pytest.approx(2 * 25.0 + 60.0 / 2.0)


def test_pit_window_bounds_for_a_one_stop_car():
    # 60L tank, reserve 1L -> can run 29.5L worth after refuel; burn 2L/lap -> 14 laps range.
    window = pit_window(current_lap=10, laps_total=40, fuel_l=20, capacity_l=60, burn_l_per_lap=2.0, reserve_l=1.0)
    assert window is not None
    open_lap, close_lap = window
    assert close_lap == 10 + math.floor(19 / 2.0)  # last lap reachable on current fuel
    assert open_lap == max(10, 40 - math.floor(59 / 2.0))


def test_pit_window_none_without_burn_rate():
    assert pit_window(10, 40, 20, 60, None) is None


def entry(entry_id, position, gap, fuel, capacity=100.0, burn=3.0, laps_left=10, current_lap=20, laps_total=40, unc=0.1, source="reported"):
    return {
        "entry_id": entry_id, "position": position, "gap_to_leader_s": gap, "gap_uncertainty_s": unc,
        "fuel_l": fuel, "capacity_l": capacity, "burn_l_per_lap": burn, "burn_source": source,
        "laps_left": laps_left, "current_lap": current_lap, "laps_total": laps_total,
    }


def test_project_returns_none_for_non_race_formats():
    assert project([], pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="practice") is None
    assert project([], pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="manual") is None


def test_project_no_stops_needed_reports_a_summary_not_an_order():
    entries = [entry("a", 1, 0.0, 90, burn=1.0, laps_left=5), entry("b", 2, 5.0, 90, burn=1.0, laps_left=5)]
    result = project(entries, pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="laps")
    assert result["entries"] == [] and "No stops required" in result["summary"]


def test_project_orders_by_net_gap_and_reports_position_change():
    # a: leader, needs a stop (long cost); b: 8s behind, no stop needed -> b should project ahead.
    entries = [
        entry("a", 1, 0.0, fuel=5, burn=2.0, laps_left=20),  # big deficit -> 1+ stops
        entry("b", 2, 8.0, fuel=90, burn=1.0, laps_left=5),  # already covered, no stop
    ]
    result = project(entries, pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="laps")
    ranked = result["entries"]
    assert ranked[0]["entry_id"] == "b" and ranked[0]["projected_rank"] == 1
    assert ranked[1]["entry_id"] == "a" and ranked[1]["change"] == -1  # dropped from P1 to P2


def test_project_marks_close_calls_within_combined_uncertainty():
    entries = [
        entry("a", 1, 0.0, fuel=5, burn=2.0, laps_left=20, unc=0.1),
        entry("b", 2, 0.5, fuel=5, burn=2.0, laps_left=20, unc=0.1),  # same stop profile, tiny gap difference
    ]
    result = project(entries, pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="laps")
    assert all(r["close_call"] for r in result["entries"])


def test_project_timed_format_adds_extra_uncertainty_versus_laps_format():
    entries = [entry("a", 1, 0.0, fuel=5, burn=2.0, laps_left=20, unc=0.1)]
    laps_result = project(entries, pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="laps")
    timed_result = project(entries, pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="timed")
    assert timed_result["entries"][0]["uncertainty_s"] > laps_result["entries"][0]["uncertainty_s"]


def test_project_entry_with_no_fuel_data_is_reported_but_unranked():
    entries = [
        entry("a", 1, 0.0, fuel=None, burn=None, laps_left=None),
        entry("b", 2, 5.0, fuel=5, burn=2.0, laps_left=20),
    ]
    result = project(entries, pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="laps")
    statuses = {r["entry_id"]: r["status"] for r in result["entries"]}
    assert statuses["a"] == "fuel data unavailable"
    assert any(r["entry_id"] == "b" and r["projected_rank"] == 1 for r in result["entries"])


def test_project_all_entries_unknown_is_not_reported_as_no_stops_needed():
    # A real bug: when every entry's fuel data is unavailable (the normal state
    # in the opening laps before FuelBurnTracker has 3 comparable laps), the old
    # code let any_stop_needed stay False (only known-n entries could set it)
    # and returned the "no stops required" all-clear summary with an EMPTY
    # entries list - silently dropping the "fuel data unavailable" rows and
    # actively misreporting "unknown" as "confirmed no stop needed".
    entries = [entry("a", 1, 0.0, fuel=None, burn=None, laps_left=None), entry("b", 2, 5.0, fuel=None, burn=None, laps_left=None)]
    result = project(entries, pit_loss=(25.0, "host"), refuel_rate=(2.0, "host"), race_format="laps")
    assert result["summary"] != "No stops required by current estimates"
    statuses = {r["entry_id"]: r["status"] for r in result["entries"]}
    assert statuses == {"a": "fuel data unavailable", "b": "fuel data unavailable"}


def test_project_pit_loss_unknown_flags_status_without_guessing():
    entries = [entry("a", 1, 0.0, fuel=5, burn=2.0, laps_left=20)]
    result = project(entries, pit_loss=None, refuel_rate=(2.0, "host"), race_format="laps")
    assert result["entries"][0]["status"] == "pit loss unknown"


def test_fuel_burn_tracker_needs_three_clean_laps_before_estimating():
    tracker = FuelBurnTracker()
    tracker.observe("e1", 1, 90.0)
    tracker.observe("e1", 2, 87.0)  # 3L burned lap 1
    assert tracker.burn_l_per_lap("e1") is None
    tracker.observe("e1", 3, 84.0)
    assert tracker.burn_l_per_lap("e1") is None  # only 2 deltas so far
    tracker.observe("e1", 4, 81.0)
    assert tracker.burn_l_per_lap("e1") == pytest.approx(3.0)


# --- Wired into GroupService --------------------------------------------------

def build_group(tmp_path, publication=None):
    import asyncio
    from types import SimpleNamespace
    from backend.app.group.service import GroupService

    def route():
        return [[100 * math.cos(i * math.tau / 100), 100 * math.sin(i * math.tau / 100)] for i in range(101)]

    s = GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / "db.sqlite"), config=SimpleNamespace(root=tmp_path)))

    async def setup():
        league = await s.league_save({"name": "L"})
        cfg = {"name": "T", "event_name": "T", "league_id": league["id"], "layout_id": "10", "format": "laps", "laps": 50}
        if publication:
            cfg["publication"] = publication
        await s.create_group(cfg)
        await s.set_map(route(), [])
        entries = []
        for n in range(2):
            invite = await s.invite("driver")
            j = await s.join({"credential": invite["credential"], "identity": {"display_name": f"D{n}", "number": str(n)}})
            await s.admit(j["participant"]["id"], "admitted")
            entries.append(j["participant"]["entry_id"])
        await s.session_action("start")
        return entries

    entries = asyncio.run(setup())
    return s, entries


def seed_live(s, entry_id, *, D, fuel, capacity=100.0, litres_per_lap=None, completed_laps=0):
    from backend.app.group.history import DistanceHistory
    now = time.time()
    s.live[entry_id] = {
        "values": {"fuel": fuel, "fuel_capacity": capacity, "strategy": {"litres_per_lap": litres_per_lap} if litres_per_lap else {}, "lap": completed_laps},
        "received": now, "layout_compatible": True, "counter_reset": False, "progress": 0.5, "clock_uncertainty_ms": 0.0,
        "completed_laps": [],
    }
    h = s.histories.setdefault(entry_id, DistanceHistory())
    h.last_completed_laps = completed_laps
    h.add(now - 1, D)


def test_service_projection_end_to_end_ranks_by_net_gap(tmp_path):
    import time as _time
    s, (leader_id, chaser_id) = build_group(tmp_path)
    g = s.active()
    g["entries"][leader_id]["baseline"] = 0
    g["entries"][chaser_id]["baseline"] = 0
    seed_live(s, leader_id, D=1000.0, fuel=90.0, litres_per_lap=1.0, completed_laps=10)  # plenty of fuel
    seed_live(s, chaser_id, D=980.0, fuel=5.0, litres_per_lap=2.0, completed_laps=10)  # needs a stop
    g["pit_loss_s"] = 25.0
    g["refuel_rate_lps"] = 2.0
    proj = s._compute_projection(g, _time.time())
    assert proj["result"] is not None
    ranked = [e for e in proj["result"]["entries"] if e.get("projected_rank")]
    assert ranked[0]["entry_id"] == leader_id  # no stop needed, stays ahead
    assert any(e["entry_id"] == chaser_id and e["stops"] for e in proj["result"]["entries"])
    assert proj["pit_loss"] == (25.0, "host")


def test_service_projection_uses_learned_pit_loss_when_no_host_value(tmp_path):
    import time as _time
    s, (leader_id, chaser_id) = build_group(tmp_path)
    g = s.active()
    g["entries"][leader_id]["baseline"] = 0
    g["entries"][chaser_id]["baseline"] = 0
    seed_live(s, leader_id, D=1000.0, fuel=90.0, litres_per_lap=1.0, completed_laps=10)
    seed_live(s, chaser_id, D=980.0, fuel=5.0, litres_per_lap=2.0, completed_laps=10)
    g["pit_stops"] = [{"entry_id": chaser_id, "lap": 3, "fuel_before": 10.0, "fuel_after": 80.0, "stationary_s": 30.0}]
    s.live[chaser_id]["completed_laps"] = [
        {"number": 2, "duration_ms": 90_000, "comparable": True},
        {"number": 3, "duration_ms": 115_000, "comparable": True},
        {"number": 4, "duration_ms": 105_000, "comparable": True},
        {"number": 5, "duration_ms": 90_500, "comparable": True},
    ]
    proj = s._compute_projection(g, _time.time())
    assert proj["pit_loss"] is not None and proj["pit_loss"][1] == "learned"
    assert proj["refuel_rate"] is not None and proj["refuel_rate"][1] == "learned"


def test_service_projection_host_calculated_burn_used_when_not_reported(tmp_path):
    import time as _time
    s, (leader_id, chaser_id) = build_group(tmp_path)
    g = s.active()
    g["entries"][leader_id]["baseline"] = 0
    g["entries"][chaser_id]["baseline"] = 0
    seed_live(s, leader_id, D=1000.0, fuel=90.0, litres_per_lap=1.0, completed_laps=10)
    seed_live(s, chaser_id, D=980.0, fuel=5.0, litres_per_lap=None, completed_laps=10)  # not reported
    s.fuel_burn.observe(chaser_id, 1, 90.0)
    s.fuel_burn.observe(chaser_id, 2, 87.0)
    s.fuel_burn.observe(chaser_id, 3, 84.0)
    s.fuel_burn.observe(chaser_id, 4, 81.0)
    proj = s._compute_projection(g, _time.time())
    chaser_row = next(e for e in proj["result"]["entries"] if e["entry_id"] == chaser_id)
    assert chaser_row["burn_source"] == "host-calculated"


def test_service_projection_publication_gates_public_exposure(tmp_path):
    s, (leader_id, chaser_id) = build_group(tmp_path, publication=["basic"])
    g = s.active()
    g["entries"][leader_id]["baseline"] = 0
    g["entries"][chaser_id]["baseline"] = 0
    seed_live(s, leader_id, D=1000.0, fuel=90.0, litres_per_lap=1.0, completed_laps=10)
    seed_live(s, chaser_id, D=980.0, fuel=5.0, litres_per_lap=2.0, completed_laps=10)
    g["pit_loss_s"] = 25.0
    import time as _time
    s.projections[g["id"]] = s._compute_projection(g, _time.time())
    assert s._public_projection(g) is None  # fuel+strategy not both published
    g["publication"] = ["basic", "fuel", "strategy"]
    public = s._public_projection(g)
    assert public is not None
    assert all("fuel_l" not in e and "capacity_l" not in e for e in public["entries"])


def test_fuel_burn_tracker_excludes_only_the_lap_where_fuel_went_up():
    tracker = FuelBurnTracker()
    tracker.observe("e1", 1, 90.0)
    tracker.observe("e1", 2, 87.0)  # -3L: counted
    tracker.observe("e1", 3, 60.0)  # -27L: still a decrease, so counted (an outlier the median absorbs)
    tracker.observe("e1", 4, 95.0)  # +35L: a refuel completing mid-lap - the only one excluded
    tracker.observe("e1", 5, 92.0)  # -3L: counted
    tracker.observe("e1", 6, 89.0)  # -3L: counted
    assert tracker.burn_l_per_lap("e1") == pytest.approx(3.0)  # median([3,27,3,3]), the 27L outlier suppressed
