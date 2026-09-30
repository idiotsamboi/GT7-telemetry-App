"""Phase 1 of the broadcast/spatial build (docs/AI_CONTEXT.md 2.1-2.5): race
distance D, the common timeline T, DistanceHistory/interval, and pit-stop
detection with its learned pit-loss/refuel-rate estimates.
"""
import math
from types import SimpleNamespace

import pytest

from backend.app.group.history import DistanceHistory, common_timeline, gap_uncertainty, interval, is_lapped
from backend.app.group.pit import PitTracker, detect, learned_pit_loss, learned_refuel_rate


def test_distance_history_time_at_interpolates_and_clamps_to_range():
    h = DistanceHistory()
    for i in range(20):
        h.add(i * 0.25, i * 10.0)  # 0.25s apart clears the 0.2s decimation
    assert h.time_at(-1) is None
    assert h.time_at(1000) is None
    assert h.time_at(45) == pytest.approx(1.125, abs=1e-6)  # halfway between D=40 (t=1.0) and D=50 (t=1.25)
    assert h.time_at(0) == pytest.approx(0.0)


def test_distance_history_decimates_below_min_step():
    h = DistanceHistory()
    h.add(0.0, 0.0)
    h.add(0.05, 5.0)  # too soon after the last sample; dropped
    assert list(h.d) == [0.0]
    h.add(0.3, 10.0)
    assert list(h.d) == [0.0, 10.0]


def test_distance_history_clamps_small_backward_noise_but_resets_on_a_big_jump():
    h = DistanceHistory()
    h.add(0.0, 100.0)
    h.add(0.3, 98.0)  # 2m of noise: clamped to the last known value, not dropped
    assert list(h.d) == [100.0, 100.0]
    h.add(0.6, 20.0)  # an 80m regression: treated as a reset, not noise
    assert list(h.d) == [20.0]


def test_distance_history_evicts_samples_older_than_max_age():
    h = DistanceHistory()
    h.add(0.0, 0.0)
    h.add(0.3, 10.0)
    h.add(200.0, 20.0)  # far past MAX_AGE_S later
    assert list(h.t) == [200.0] and list(h.d) == [20.0]


def test_interval_matches_a_known_constant_speed_gap_within_50ms():
    # Car A laps the same route as car B, 3.0s ahead at every point.
    ahead = DistanceHistory()
    behind = DistanceHistory()
    speed = 50.0  # m/s
    for i in range(200):
        t = i * 0.25
        ahead.add(t, speed * t)
        behind.add(t, speed * (t - 3.0)) if t >= 3.0 else None
    T_now = 40.0
    D_behind = speed * (T_now - 3.0)
    result = interval(ahead, T_now, D_behind)
    assert result == pytest.approx(3.0, abs=0.05)


def test_interval_is_none_when_ahead_history_does_not_cover_the_distance():
    ahead = DistanceHistory()
    ahead.add(0.0, 0.0)
    ahead.add(0.3, 10.0)
    assert interval(ahead, 100.0, 10_000.0) is None


def test_gap_uncertainty_combines_both_clocks_in_quadrature():
    assert gap_uncertainty(None, None) == pytest.approx(0.05)
    assert gap_uncertainty(30, 40) == pytest.approx(math.hypot(30, 40) / 1000 + 0.05)


def test_is_lapped_flags_beyond_half_a_lap_only():
    assert not is_lapped(D_ahead=1000, D_behind=600, length=2000)  # 400m gap, <1000
    assert is_lapped(D_ahead=1700, D_behind=600, length=2000)  # 1100m gap, >1000


def test_common_timeline_uses_offset_when_known_else_falls_back_with_extra_uncertainty():
    T, extra = common_timeline(source_utc=1000.5, received=1000.0, offset_ms=500.0)
    assert T == pytest.approx(1000.0) and extra == 0.0
    T, extra = common_timeline(source_utc=None, received=1000.0, offset_ms=None)
    assert T == 1000.0 and extra == 250.0


# --- Pit-stop detection -----------------------------------------------------

def test_detect_heuristic_requires_sustained_slow_speed_near_start_finish():
    # Fast, near start/finish: not in pit.
    assert detect(position=[0, 0, 5], speed_kmh=150, s=5, length=5000, pit_points=None, corners=None, slow_since_s=0)[0] is False
    # Slow but only just started (not sustained 4s yet).
    assert detect(position=[0, 0, 5], speed_kmh=40, s=5, length=5000, pit_points=None, corners=None, slow_since_s=1)[0] is False
    # Slow, sustained, near start/finish: in pit (heuristic/inferred).
    in_pit, inferred = detect(position=[0, 0, 5], speed_kmh=40, s=5, length=5000, pit_points=None, corners=None, slow_since_s=5)
    assert in_pit and inferred
    # Slow and sustained but far from start/finish: not in pit.
    assert detect(position=[0, 0, 2500], speed_kmh=40, s=2500, length=5000, pit_points=None, corners=None, slow_since_s=5)[0] is False
    # Slow, sustained, near start/finish, but inside a mapped corner: excluded.
    corners = [{"id": "T1", "name": "Turn 1", "s_start": 0, "s_end": 20}]
    assert detect(position=[0, 0, 5], speed_kmh=40, s=5, length=5000, pit_points=None, corners=corners, slow_since_s=5)[0] is False


def test_detect_prefers_a_surveyed_pit_lane_when_present():
    pit_points = [[0, 0, 0], [0, 0, 100]]
    # Right on the pit lane, fast: still counts (surveyed path ignores speed entirely).
    in_pit, inferred = detect(position=[0, 0, 50], speed_kmh=150, s=None, length=None, pit_points=pit_points, corners=None, slow_since_s=0)
    assert in_pit and not inferred
    # 50m away from the pit lane: not in pit.
    assert detect(position=[50, 0, 50], speed_kmh=150, s=None, length=None, pit_points=pit_points, corners=None, slow_since_s=0)[0] is False


from backend.app.group.pit import SLOW_SUSTAINED_S


def drive_pit_stop(tracker, entry_id, *, extra_pit_s=10.0, fuel_added=0.0, stationary=True, lap=5):
    """Ramp up to the sustained-slow threshold (registers as 'in pit'), hold for
    extra_pit_s more seconds (optionally adding fuel), then exit at speed. The
    recorded stop's duration is ~extra_pit_s - the ramp-up itself doesn't count,
    since detect() only flips true once slow_since_s clears SLOW_SUSTAINED_S."""
    t = 0.0
    fuel = 50.0
    stop = None
    ramp_steps = int(SLOW_SUSTAINED_S / 0.5) + 1
    for _ in range(ramp_steps):
        stop = tracker.consume(entry_id, t, position=[0, 0, 5], speed_kmh=1.0, s=5, length=5000, lap=lap, fuel=fuel, pit_points=None, corners=None) or stop
        t += 0.5
    hold_steps = max(1, int(extra_pit_s / 0.5))
    hold_speed = 0.0 if stationary else 50.0
    for _ in range(hold_steps):
        fuel += fuel_added / hold_steps
        stop = tracker.consume(entry_id, t, position=[0, 0, 5], speed_kmh=hold_speed, s=5, length=5000, lap=lap, fuel=fuel, pit_points=None, corners=None) or stop
        t += 0.5
    exit_stop = tracker.consume(entry_id, t, position=[0, 0, 2500], speed_kmh=150.0, s=2500, length=5000, lap=lap, fuel=fuel, pit_points=None, corners=None)
    return exit_stop or stop


def test_pit_tracker_records_a_completed_stop_on_exit_after_minimum_duration():
    tracker = PitTracker()
    stop = drive_pit_stop(tracker, "e1", extra_pit_s=10.0)
    assert stop is not None
    assert stop["entry_id"] == "e1" and stop["lap"] == 5
    assert stop["t_out"] - stop["t_in"] >= 8.0
    assert stop["inferred"] is True


def test_pit_tracker_ignores_a_brief_slow_roll_through():
    tracker = PitTracker()
    stop = drive_pit_stop(tracker, "e2", extra_pit_s=2.0)  # too short, no fuel added
    assert stop is None


def test_pit_tracker_completes_early_on_fuel_added_even_if_briefer_than_min_duration():
    tracker = PitTracker()
    stop = drive_pit_stop(tracker, "e3", extra_pit_s=3.0, fuel_added=5.0)
    assert stop is not None and stop["fuel_after"] - stop["fuel_before"] == pytest.approx(5.0, abs=0.2)


def test_pit_tracker_accumulates_stationary_time_for_refuel_rate():
    tracker = PitTracker()
    stop = drive_pit_stop(tracker, "e4", extra_pit_s=10.0, stationary=True)
    assert stop is not None
    assert stop["stationary_s"] == pytest.approx(10.0, abs=0.6)


def test_learned_pit_loss_and_refuel_rate_from_a_single_stop():
    stops = [{"entry_id": "e1", "lap": 5, "fuel_before": 50.0, "fuel_after": 100.0, "stationary_s": 25.0}]
    laps_by_entry = {
        "e1": [
            {"number": 4, "duration_ms": 90_000, "comparable": True},
            {"number": 5, "duration_ms": 115_000, "comparable": True},  # pit lap: slower
            {"number": 6, "duration_ms": 105_000, "comparable": True},  # next lap: slower
            {"number": 7, "duration_ms": 90_500, "comparable": True},
        ]
    }
    loss = learned_pit_loss(stops, laps_by_entry)
    assert loss is not None and loss["source"] == "learned (1 stop)"
    # baseline median clean lap = median(90000, 90500) = 90250ms; loss = (115000+105000-2*90250)/1000
    assert loss["seconds"] == pytest.approx((115_000 + 105_000 - 2 * 90_250) / 1000, abs=0.1)
    rate = learned_refuel_rate(stops)
    assert rate is not None and rate["litres_per_second"] == pytest.approx(50.0 / 25.0, abs=1e-6)


def test_learned_pit_loss_is_none_without_a_usable_stop():
    assert learned_pit_loss([], {}) is None
    assert learned_refuel_rate([{"entry_id": "e1", "fuel_before": None, "fuel_after": None, "stationary_s": 0}]) is None


# --- Wired into GroupService -------------------------------------------------

def test_classification_computes_d_and_feeds_history(tmp_path):
    import asyncio
    from backend.app.group.service import GroupService
    from backend.app.group.timing import Projection

    def route(scale=1.0):
        return [[scale * 100 * math.cos(i * math.tau / 100), scale * 100 * math.sin(i * math.tau / 100)] for i in range(101)]

    s = GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / "db.sqlite"), config=SimpleNamespace(root=tmp_path)))

    async def setup():
        league = await s.league_save({"name": "Test league"})
        group = await s.create_group({"name": "Test", "event_name": "Test event", "league_id": league["id"], "layout_id": "10"})
        await s.set_map(route(), [])
        invite = await s.invite("driver")
        joined = await s.join({"credential": invite["credential"], "identity": {"display_name": "Driver", "number": "1"}})
        await s.admit(joined["participant"]["id"], "admitted")
        return joined

    joined = asyncio.run(setup())
    entry_id = joined["participant"]["entry_id"]
    principal = asyncio.run(s.authenticate(joined["token"], ("driver",)))

    def send(i, lap=0):
        point = route()[i * 5]
        body = {
            "group_id": s.active()["id"], "session_id": s.active()["session_id"], "participant_id": joined["participant"]["id"],
            "entry_id": entry_id, "boot_id": "b1", "sequence": i + 1, "source_mono": i * 0.3, "source_utc": 1000.0 + i * 0.3,
            "provenance": "live", "layout_id": "10", "local_session_id": "l1",
            "values": {"position": [point[0], 0, point[1]], "lap": lap, "flags": 1},
        }
        s.telemetry(principal, body)

    send(0)
    asyncio.run(s.session_action("start"))
    # Baseline capture at session start needs a live sample received within the
    # last 2 real seconds; on a slow CI/sandbox host that window can already have
    # elapsed by here, so set it directly rather than make this test timing-flaky.
    s.active()["entries"][entry_id]["baseline"] = 0
    length = s.projectors[s.active()["id"]].length
    for i in range(1, 6):
        send(i)
    import time as _time
    row = next(r for r in s.classification(s.active(), _time.time()) if r["entry_id"] == entry_id)
    assert row["D"] is not None and 0 <= row["D"] < length
    assert entry_id in s.histories and len(s.histories[entry_id].d) >= 1
