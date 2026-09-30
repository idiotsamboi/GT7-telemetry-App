"""Phase 7 of the broadcast/spatial build (docs/AI_CONTEXT.md section 8):
the spatial per-lap trace, live braking-episode detection, corner matching,
and per-corner loss/cause coaching. Live path only - see spatial_coaching.py's
module docstring for the recorded-analysis scope this doesn't cover.
"""
import math

import pytest

from backend.app.spatial_coaching import (
    LiveBrakingTracker, SpatialLap, corner_for, corner_label, corner_report,
)

LENGTH = 5000.0
CORNERS = [
    {"id": "T1", "name": "T1", "source": "auto", "s_start": 100.0, "s_apex": 150.0, "s_end": 200.0},
    {"id": "T3", "name": "Turn 3", "source": "surveyed", "s_start": 1000.0, "s_apex": 1050.0, "s_end": 1120.0},
]


def build_lap(profile, layout_id="10", car_id=1):
    """profile: fn(s) -> (elapsed_s, speed_kmh, brake, throttle); sampled every 5m."""
    lap = SpatialLap(LENGTH, layout_id, car_id)
    s = 0.0
    while s < LENGTH:
        elapsed, speed, brake, throttle = profile(s)
        lap.record(s, elapsed, speed, brake, throttle)
        s += 5.0
    return lap


def reference_profile(s):
    # A steady lap: constant speed, brakes exactly at each corner's s_start,
    # releases into throttle exactly at s_apex + 20m.
    elapsed = s / 50.0  # 50 m/s pace
    for c in CORNERS:
        if c["s_start"] - 20 <= s <= c["s_apex"] + 20:
            braking = c["s_start"] <= s <= c["s_apex"]
            return elapsed, 100.0 if s < c["s_apex"] else 100.0, 0.8 if braking else 0.0, 0.0 if s < c["s_apex"] + 20 else 1.0
    return elapsed, 120.0, 0.0, 1.0


def test_spatial_lap_time_at_interpolates_and_reports_none_outside_visited_range():
    lap = SpatialLap(1000.0, "10", 1)
    # Record every bin from 0 to 20m so bin 1 (10-20m) is populated - time_at()
    # only interpolates between adjacent recorded bins, never across a gap.
    lap.record(0.0, 0.0, 100.0, 0.0, 1.0)
    lap.record(10.0, 0.5, 100.0, 0.0, 1.0)
    lap.record(20.0, 1.0, 100.0, 0.0, 1.0)
    assert lap.time_at(15.0) == pytest.approx(0.75, abs=0.05)
    assert lap.time_at(500.0) is None  # never visited


def test_corner_for_matches_the_braking_zone_and_reports_unassigned_otherwise():
    assert corner_for(1010.0, LENGTH, CORNERS) is CORNERS[1]
    assert corner_for(2500.0, LENGTH, CORNERS) is None


def test_corner_label_uses_surveyed_name_or_turn_number_for_auto():
    assert corner_label(CORNERS[0]) == "Turn 1"
    assert corner_label(CORNERS[1]) == "Turn 3"
    assert corner_label(None) == "braking zone"


def test_live_braking_tracker_produces_an_episode_with_position():
    tracker = LiveBrakingTracker()
    t = 0.0
    result = None
    # Approach at 120 km/h, brake from s=990 to s=1050 (apex), throttle from s=1070;
    # the episode only finalizes 50m past s_throttle (docs/AI_CONTEXT.md 8.2), so the
    # loop must run that far past 1070 too.
    for s in range(980, 1140, 2):
        speed = 120.0 if s < 990 else max(60.0, 120.0 - (s - 990) * 1.0)
        brake = 0.0 if s < 990 else (0.8 if s < 1050 else 0.0)
        throttle = 1.0 if s < 990 else (0.0 if s < 1070 else 0.5)
        r = tracker.observe(t, float(s), speed, brake, throttle, lap=5)
        if r:
            result = r
        t += 0.1
    assert result is not None
    assert result["s_onset"] == pytest.approx(990.0, abs=2)
    assert result["s_apex"] == pytest.approx(1048.0, abs=4)
    assert result["s_throttle"] == pytest.approx(1070.0, abs=2)
    assert result["lap"] == 5


def test_live_braking_tracker_ignores_a_brief_low_speed_brake_tap():
    tracker = LiveBrakingTracker()
    result = tracker.observe(0.0, 100.0, 20.0, 0.6, 0.0, lap=1)  # entry speed under 50 km/h
    result = tracker.observe(0.3, 105.0, 18.0, 0.0, 1.0, lap=1) or result
    assert result is None


def test_corner_report_detects_a_later_brake_onset_with_correct_sign_and_cause():
    ref = build_lap(reference_profile)

    def slower_profile(s):
        # Identical except braking at T3 starts 15m later (worse) - loses time
        # on entry (from the late brake point on), not on exit.
        shifted = {**CORNERS[1], "s_start": CORNERS[1]["s_start"] + 15}
        elapsed = s / 50.0 + (0.3 if s >= shifted["s_start"] else 0.0)
        if shifted["s_start"] - 20 <= s <= shifted["s_apex"] + 20:
            braking = shifted["s_start"] <= s <= shifted["s_apex"]
            return elapsed, 100.0, 0.8 if braking else 0.0, 0.0 if s < shifted["s_apex"] + 20 else 1.0
        if CORNERS[0]["s_start"] - 20 <= s <= CORNERS[0]["s_apex"] + 20:
            braking = CORNERS[0]["s_start"] <= s <= CORNERS[0]["s_apex"]
            return elapsed, 100.0, 0.8 if braking else 0.0, 0.0 if s < CORNERS[0]["s_apex"] + 20 else 1.0
        return elapsed, 120.0, 0.0, 1.0

    lap = build_lap(slower_profile)
    lap_tracker, ref_tracker = LiveBrakingTracker(), LiveBrakingTracker()
    lap_episodes, ref_episodes = [], []
    for i, s in enumerate(x * 5.0 for x in range(int(LENGTH / 5))):
        _, speed, brake, throttle = slower_profile(s)
        r = lap_tracker.observe(i * 0.1, s, speed, brake, throttle, lap=7)
        if r:
            lap_episodes.append(r)
        _, speed, brake, throttle = reference_profile(s)
        r = ref_tracker.observe(i * 0.1, s, speed, brake, throttle, lap=3)
        if r:
            ref_episodes.append(r)

    report = corner_report(lap, ref, CORNERS, lap_number=7, lap_episodes=lap_episodes, ref_episodes=ref_episodes)
    t3 = next((item for item in report if "Turn 3" in item["corner"]), None)
    assert t3 is not None
    assert t3["loss_s"] > 0  # slower
    assert "earlier" in t3["text"] or "later" in t3["text"]
    assert "later" in t3["text"]  # braked later -> worse
    assert t3["priority"] == 2  # a loss, not a gain


def test_corner_report_gain_case_uses_keep_that_wording():
    ref = build_lap(reference_profile)

    def faster_profile(s):
        shifted = {**CORNERS[1], "s_start": CORNERS[1]["s_start"] - 15}
        elapsed = s / 50.0 - (0.3 if s > shifted["s_apex"] else 0.0)
        if shifted["s_start"] - 20 <= s <= shifted["s_apex"] + 20:
            braking = shifted["s_start"] <= s <= shifted["s_apex"]
            return elapsed, 100.0, 0.8 if braking else 0.0, 0.0 if s < shifted["s_apex"] + 20 else 1.0
        return elapsed, 120.0, 0.0, 1.0

    lap = build_lap(faster_profile)
    report = corner_report(lap, ref, CORNERS, lap_number=2, lap_episodes=[], ref_episodes=[])
    t3 = next((item for item in report if "Turn 3" in item["corner"]), None)
    assert t3 is not None and t3["loss_s"] < 0
    assert "keep that" in t3["text"].lower()
    assert t3["priority"] == 3


def test_corner_report_skips_corners_below_the_minimum_loss_threshold():
    ref = build_lap(reference_profile)
    lap = build_lap(reference_profile)  # identical lap: no real difference anywhere
    report = corner_report(lap, ref, CORNERS, lap_number=2, lap_episodes=[], ref_episodes=[])
    assert report == []


def test_corner_report_returns_nothing_for_a_different_layout():
    ref = build_lap(reference_profile, layout_id="10")
    lap = build_lap(reference_profile, layout_id="11")
    assert corner_report(lap, ref, CORNERS, lap_number=1, lap_episodes=[], ref_episodes=[]) == []


def test_corner_report_never_mentions_wear_or_grip_in_any_text():
    ref = build_lap(reference_profile)

    def slower_profile(s):
        shifted = {**CORNERS[1], "s_start": CORNERS[1]["s_start"] + 15}
        elapsed = s / 50.0 + (0.3 if s > shifted["s_apex"] else 0.0)
        if shifted["s_start"] - 20 <= s <= shifted["s_apex"] + 20:
            braking = shifted["s_start"] <= s <= shifted["s_apex"]
            return elapsed, 100.0, 0.8 if braking else 0.0, 0.0 if s < shifted["s_apex"] + 20 else 1.0
        return elapsed, 120.0, 0.0, 1.0

    lap = build_lap(slower_profile)
    report = corner_report(lap, ref, CORNERS, lap_number=1, lap_episodes=[], ref_episodes=[])
    for item in report:
        assert "wear" not in item["text"].lower() and "grip" not in item["text"].lower()
