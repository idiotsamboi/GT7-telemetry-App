import json, math
from backend.app.training import TrainingRecorder, POINTS_PER_KM_TARGET
from backend.app.telemetry import demo_sample


def drive(recorder, laps, points_per_lap=200, flags=1, radius=200.0):
    """Feed `laps` complete circuits plus one leading partial segment."""
    lap_number = 0
    for lap_index in range(laps + 1):  # +1 leading partial lap, discarded
        for i in range(points_per_lap):
            a = i / points_per_lap * math.tau
            s = demo_sample(0, 0)
            s.values.update(
                position=[radius * math.cos(a), 12.0, radius * math.sin(a)],
                lap=lap_number,
                flags=flags,
            )
            recorder.consume(s)
        lap_number += 1
    # One final boundary crossing to flush the last full lap.
    s = demo_sample(0, 0)
    s.values.update(position=[radius, 12.0, 0.0], lap=lap_number, flags=flags)
    recorder.consume(s)


def test_opening_partial_lap_is_discarded_and_full_laps_are_saved(tmp_path):
    r = TrainingRecorder(tmp_path)
    r.start("1", {"name": "Test Circuit", "track": "Test Venue", "direction": "forward", "length_m": 1000.0})
    drive(r, laps=2)
    assert r.laps_this_session == 2
    lines = (tmp_path / "track-training" / "1.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["layout_id"] == "1"
    assert len(record["points"]) >= 50
    assert all(len(p) == 3 for p in record["points"])


def test_short_segments_below_minimum_points_are_not_saved(tmp_path):
    r = TrainingRecorder(tmp_path)
    r.start("2", {"name": "Short", "track": "V", "direction": "forward", "length_m": 500.0})
    drive(r, laps=2, points_per_lap=10)  # well under MIN_LAP_POINTS
    assert r.laps_this_session == 0
    assert not (tmp_path / "track-training" / "2.jsonl").exists()


def test_paused_or_offtrack_samples_are_ignored(tmp_path):
    r = TrainingRecorder(tmp_path)
    r.start("3", {"name": "N", "track": "V", "direction": "forward", "length_m": 1000.0})
    s = demo_sample(0, 0)
    s.values.update(position=[0, 0, 0], lap=1, flags=0)  # off track
    r.consume(s)
    s.values.update(flags=2)  # paused
    r.consume(s)
    assert r.current == [] and r.points_this_session == 0


def test_inactive_recorder_ignores_samples(tmp_path):
    r = TrainingRecorder(tmp_path)
    s = demo_sample(0, 0)
    s.values.update(position=[1.0, 2.0, 3.0], lap=1, flags=1)
    r.consume(s)
    assert r.current == [] and r.points_this_session == 0


def test_saved_lap_count_and_status(tmp_path):
    r = TrainingRecorder(tmp_path)
    r.start("4", {"name": "N", "track": "V", "direction": "forward", "length_m": 1000.0})
    drive(r, laps=1)
    status = r.status()
    assert status["active"] and status["layout_id"] == "4" and status["laps_saved_total"] == 1
    r.stop()
    assert r.status()["active"] is False
    assert r.saved_lap_count("4") == 1


def test_goal_is_incomplete_below_target_and_complete_once_reached(tmp_path):
    r = TrainingRecorder(tmp_path)
    per_lap = POINTS_PER_KM_TARGET // 2 + 50  # ~1km layout: two laps just clears the target
    meta = {"name": "N", "track": "V", "direction": "forward", "length_m": 1000.0}
    r.start("5", meta)
    drive(r, laps=1, points_per_lap=per_lap)
    goal = r.status()["goal"]
    assert goal["laps_saved"] == 1 and not goal["complete"] and goal["percent"] < 100
    r.start("5", meta)  # a second recording session, same layout - goal persists from disk
    drive(r, laps=1, points_per_lap=per_lap)
    goal = r.status()["goal"]
    assert goal["laps_saved"] == 2 and goal["complete"] and goal["percent"] == 100
    assert goal["points_per_km"] >= POINTS_PER_KM_TARGET


def test_list_progress_only_includes_layouts_with_saved_laps(tmp_path):
    r = TrainingRecorder(tmp_path)
    layouts = {
        "6": {"name": "Six", "track": "V", "direction": "forward", "length_m": 1000.0},
        "7": {"name": "Seven", "track": "V", "direction": "forward", "length_m": 1000.0},
    }
    r.start("6", layouts["6"])
    drive(r, laps=1)
    r.start("7", layouts["7"])  # started but never completes a lap
    assert r.list_progress(layouts) == [
        {
            "layout_id": "6", "name": "Six", "venue_name": "V", "direction": "forward", "length_m": 1000.0,
            **r.goal("6", 1000.0),
        }
    ]


def test_preview_points_drain_on_status_read(tmp_path):
    r = TrainingRecorder(tmp_path)
    r.start("8", {"name": "N", "track": "V", "direction": "forward", "length_m": 1000.0})
    s = demo_sample(0, 0)
    s.values.update(position=[1.0, 2.0, 3.0], lap=0, flags=1)
    r.consume(s)
    s.values.update(position=[4.0, 5.0, 6.0])
    r.consume(s)
    status = r.status()
    assert status["preview_points"] == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert r.status()["preview_points"] == []  # drained; not resent


def test_discard_current_lap_drops_unsaved_points_but_keeps_saved_laps(tmp_path):
    r = TrainingRecorder(tmp_path)
    r.start("9", {"name": "N", "track": "V", "direction": "forward", "length_m": 1000.0})
    drive(r, laps=1)  # one lap safely saved to disk
    assert r.laps_this_session == 1
    s = demo_sample(0, 0)
    s.values.update(position=[9.0, 9.0, 9.0], lap=2, flags=1)
    r.consume(s)  # start of a second, in-progress lap
    assert r.current and r.points_this_session > 0
    points_before_discard = r.points_this_session
    r.discard_current_lap()
    assert r.current == [] and r.pending == [] and r.retake_id == 1
    assert r.laps_this_session == 1  # the earlier saved lap is untouched
    assert r.points_this_session == points_before_discard  # session total is a counter, not rewound
    assert r.saved_lap_count("9") == 1
    # A fresh lap boundary after the discard starts clean, not stitched to the aborted one.
    s.values.update(position=[9.1, 9.0, 9.0], lap=2, flags=1)
    r.consume(s)
    assert len(r.current) == 1


def test_discard_current_lap_is_a_noop_when_not_recording(tmp_path):
    r = TrainingRecorder(tmp_path)
    r.discard_current_lap()
    assert r.retake_id == 0


def test_restart_layout_deletes_saved_captures_unless_it_is_the_active_one(tmp_path):
    r = TrainingRecorder(tmp_path)
    r.start("10", {"name": "N", "track": "V", "direction": "forward", "length_m": 1000.0})
    drive(r, laps=1)
    path = tmp_path / "track-training" / "10.jsonl"
    assert path.exists()
    assert r.restart_layout("10") is False  # refused: this layout is actively recording
    assert path.exists()
    r.stop()
    assert r.restart_layout("10") is True
    assert not path.exists()
    assert r.saved_lap_count("10") == 0
    # Deleting a layout with no file at all is a harmless no-op.
    assert r.restart_layout("nonexistent") is True
