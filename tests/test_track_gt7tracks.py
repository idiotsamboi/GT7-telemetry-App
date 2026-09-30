"""GT7Tracks ingest: parser traps, lap segmentation, fusion gate and elevation transfer.

track-tool.py is a build-time script (never imported at runtime), so it is loaded here
by path rather than as a package. All fixtures are synthetic; no network access.
"""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("track_tool", ROOT / "scripts/track-tool.py")
track_tool = importlib.util.module_from_spec(spec)
sys.modules["track_tool"] = track_tool
spec.loader.exec_module(track_tool)

from backend.app.track_model import TrackProgress, build_model  # noqa: E402


def circle_points(radius=200.0, n=360, elevation=None):
    return [[radius * math.cos(i * math.tau / n), elevation, radius * math.sin(i * math.tau / n)] for i in range(n)]


def write_csv(path, rows):
    lines = ["track_id,x,z,y,speed,rpm,orientation,rotation_x,rotation_z,rotation_y"]
    for track_id, x, z, y, speed in rows:
        lines.append(f"{track_id},{x},{z},{y},{speed},6000,0,0,0,0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_column_order_trap_elevation_is_the_fourth_column(tmp_path):
    """On disk the order is track_id,x,z,y - z is horizontal, y is elevation."""
    path = tmp_path / "1.csv"
    write_csv(path, [("1", 10.0, 20.0, 62.0, 30.0), ("1", 11.0, 21.0, 63.0, 30.0)])
    rows = track_tool.parse_gt7tracks_csv(path)
    x, elevation, world_z, speed = rows[0]
    assert x == 10.0 and world_z == 20.0 and elevation == 62.0 and speed == 30.0


def test_duplicate_stationary_and_jump_rows_are_dropped(tmp_path):
    path = tmp_path / "1.csv"
    write_csv(
        path,
        [
            ("1", 0.0, 0.0, 0.0, 30.0),
            ("1", 0.0, 0.0, 0.0, 30.0),  # exact duplicate of the previous row
            ("1", 0.05, 0.0, 0.0, 0.5),  # stationary/near-zero speed
            ("1", 1.0, 0.0, 0.0, 30.0),
            ("1", 500.0, 0.0, 0.0, 30.0),  # a 499m jump: rejected as corrupt/teleported
            ("1", 501.0, 0.0, 0.0, 30.0),
        ],
    )
    rows = track_tool.parse_gt7tracks_csv(path)
    xs = [r[0] for r in rows]
    assert xs == [0.0, 1.0]


def test_non_finite_and_malformed_rows_are_skipped(tmp_path):
    path = tmp_path / "1.csv"
    path.write_text(
        "track_id,x,z,y,speed,rpm,orientation,rotation_x,rotation_z,rotation_y\n"
        "1,nan,0,0,30,6000,0,0,0,0\n"
        "1,not-a-number,0,0,30,6000,0,0,0,0\n"
        "1,1,2,3\n"  # too few columns
        "1,5.0,0,0,30,6000,0,0,0,0\n",
        encoding="utf-8",
    )
    rows = track_tool.parse_gt7tracks_csv(path)
    assert len(rows) == 1 and rows[0][0] == 5.0


def test_unexpected_column_layout_is_rejected(tmp_path):
    path = tmp_path / "1.csv"
    path.write_text("track_id,speed,x,z,y\n1,30,0,0,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="column layout"):
        track_tool.parse_gt7tracks_csv(path)


def test_lap_segmentation_closes_on_anchor_return_and_gates_by_length():
    points = circle_points()
    # 1.5 laps: ends mid-circle, well away from the anchor, so exactly one lap can close.
    parsed = [(p[0], 0.0, p[2], 30.0) for p in points + points[: len(points) // 2]]
    anchor = (points[0][0], points[0][2])
    length = sum(math.hypot(b[0] - a[0], b[2] - a[2]) for a, b in zip(points, points[1:] + points[:1]))
    laps = track_tool.segment_gt7tracks_laps(parsed, anchor, length, None)
    assert len(laps) == 1
    lap_length = sum(math.hypot(b[0] - a[0], b[2] - a[2]) for a, b in zip(laps[0], laps[0][1:]))
    assert abs(lap_length - length) / length < 0.05


def test_lap_failing_the_length_gate_is_rejected():
    points = circle_points()
    parsed = [(p[0], 0.0, p[2], 30.0) for p in points * 2]
    anchor = (points[0][0], points[0][2])
    # A reference length far from the actual driven circle fails the +/-10% length gate.
    laps = track_tool.segment_gt7tracks_laps(parsed, anchor, 100.0, None)
    assert laps == []


def test_pit_garage_excursion_is_discarded_when_an_existing_model_is_given():
    points = circle_points()
    model = build_model("1", points + [points[0]], {"kind": "test"})
    progress = TrackProgress(model)
    length = model["length_m"]
    # One clean lap, then a detour 100m off the centreline (a pit road), then a second clean lap.
    detour = [[points[0][0] + 100, None, points[0][2]] for _ in range(20)]
    parsed = [(p[0], 0.0, p[2], 30.0) for p in points] + [(p[0], 0.0, p[2], 30.0) for p in points]
    parsed_with_detour = parsed[: len(points)] + [(d[0], 0.0, d[2], 30.0) for d in detour] + parsed[len(points):]
    anchor = (points[0][0], points[0][2])
    laps = track_tool.segment_gt7tracks_laps(parsed_with_detour, anchor, length, progress)
    assert len(laps) >= 1
    for lap in laps:
        for point in lap:
            hit = progress.project([point[0], None, point[2]], corridor_m=60)
            assert hit is not None and hit.distance_m <= 25


def test_fit_stats_reports_median_and_p95_and_none_when_too_sparse():
    points = circle_points()
    model = build_model("1", points + [points[0]], {"kind": "test"})
    progress = TrackProgress(model)
    on_line = [[p[0], None, p[2]] for p in points]
    stats = track_tool.fit_stats(progress, on_line)
    assert stats is not None
    median_m, p95_m = stats
    assert median_m < 1.0 and p95_m < 1.0
    far_away = [[100000.0, None, 100000.0] for _ in range(20)]
    assert track_tool.fit_stats(progress, far_away) is None


def test_elevation_attach_medians_and_smooths_then_transfer_stays_within_5m():
    points = circle_points()
    model = build_model("1", points + [points[0]], {"kind": "test"})
    # Dense raw samples (60Hz-like), well above the model's 2m-resampled station count,
    # so most stations receive at least one elevation observation to median/smooth.
    dense = circle_points(n=3000)
    laps = [[[p[0], 50.0 + 0.1 * ((i % 5) - 2), p[2]] for i, p in enumerate(dense)]]  # noisy but centred on 50m
    track_tool.attach_gt7tracks_elevation(model, laps, {"kind": "gt7tracks capture"})
    assert model["elevation_source"] == "gt7tracks"
    elevations = [p[1] for p in model["centerline"]]
    assert all(45 <= e <= 55 for e in elevations if e is not None)
    assert sum(e is not None for e in elevations) / len(elevations) > 0.9

    # A sibling whose centreline sits within 5m of the elevated model gets elevation copied.
    sibling_points = circle_points(radius=200.2)
    sibling = build_model("2", sibling_points + [sibling_points[0]], {"kind": "test"})
    catalogue = [{"id": "v", "layouts": [{"id": "1"}, {"id": "2"}]}]
    models = {"1": model, "2": sibling}
    track_tool.transfer_elevation(models, catalogue)
    assert sibling["elevation_source"] in ("transferred", "transferred-partial")
    assert any(p[1] is not None for p in sibling["centerline"])

    # A sibling far from any elevated model keeps null elevation.
    far_points = circle_points(radius=5000.0)
    far_sibling = build_model("3", far_points + [far_points[0]], {"kind": "test"})
    catalogue2 = [{"id": "v", "layouts": [{"id": "1"}, {"id": "3"}]}]
    models2 = {"1": model, "3": far_sibling}
    track_tool.transfer_elevation(models2, catalogue2)
    assert far_sibling.get("elevation_source") is None
    assert all(p[1] is None for p in far_sibling["centerline"])
