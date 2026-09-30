"""World-frame model, storage and recognizer invariants independent of a PS5."""

import copy
import json
import math
from unittest.mock import patch

import pytest

from backend.app.track_bundle import get_model, iter_models
from backend.app.track_fusion import fuse_laps
from backend.app.track_model import TrackProgress, build_model
from backend.app.track_recognition import TrackRecognizer
from backend.app.track_store import TrackModelStore, validate_layers, validate_model


def circle(key: str = "10", *, reverse: bool = False, x: float = 0, elevation=None):
    """Make a 1256m closed route with known direction and optional elevation."""
    points = [
        [x + 200 * math.cos(i * math.tau / 360), elevation, 200 * math.sin(i * math.tau / 360)] for i in range(361)
    ]
    if reverse:
        points.reverse()
    return build_model(key, points, {"kind": "test"})


def drive(engine, model, *, distance=800, start=0, timestamp=0):
    """Feed exact model positions at 5Hz without using application receiver state."""
    result = None
    for step in range(int(distance / 10) + 1):
        i = (start + round(step * 10 / model["step_m"])) % len(model["centerline"])
        h = model["heading"][i]
        result = engine.update(
            model["centerline"][i],
            timestamp + step * 0.2,
            speed=50,
            velocity=[50 * math.cos(h), 0, 50 * math.sin(h)],
            car_id=1,
        )
    return result


def test_world_model_retains_frame_and_lossless_legacy():
    legacy = {
        "schema": 2,
        "layout_id": "10",
        "points": [
            [1000 + 200 * math.cos(i * math.tau / 100), 200 * math.sin(i * math.tau / 100)] for i in range(101)
        ],
        "versions": [{"revision": "old", "points": [[1, 2]]}],
    }
    model = build_model("10", legacy["points"], {"kind": "user-learned"}, preserve=legacy)
    assert model["legacy"] == legacy
    assert model["centerline"][0] == [1200, None, 0]
    assert 1.9 < model["step_m"] <= 2
    assert model["frame"] == "gt7-world"
    assert model["corners"]
    validate_model(model, {"10"})


def test_projection_wrap_direction_and_bridge_elevation():
    model = circle(elevation=5)
    progress = TrackProgress(model)
    hit = progress.project(model["centerline"][1], previous_s=progress.length - 3, expected_m=5)
    assert hit is not None and 0 <= hit.s < 4
    backward = progress.candidates(model["centerline"][-20], previous_s=2, expected_m=5, corridor_m=5)
    assert not backward
    a = progress.candidates([200, 5, 0], heading=math.pi / 2)[0][0]
    b = progress.candidates([200, 35, 0], heading=math.pi / 2)[0][0]
    assert b > a + 20
    assert progress.project([9999, 5, 9999]) is None


def test_direction_lock_unknown_and_manual_override():
    forward, reverse = circle(), circle("11", reverse=True)
    engine = TrackRecognizer([forward, reverse])
    result = drive(engine, forward)
    assert result["state"] == "locked" and result["layout_id"] == "10"
    engine.reset()
    assert drive(engine, reverse)["layout_id"] == "11"
    engine.select("10")
    result = drive(engine, reverse)
    assert result["layout_id"] == "10" and result["manual"]
    engine.select("")
    assert engine.update([99999, None, 99999], 0)["state"] == "unknown"


def test_shared_geometry_does_not_guess_or_lock_early():
    model = circle()
    same = circle("11")
    engine = TrackRecognizer([model, same])
    assert drive(engine, model, distance=300)["state"] != "locked"
    engine.reset()
    result = drive(engine, model)
    assert result["state"] == "ambiguous" and not result["layout_id"]


def test_teleport_and_provenance_clear_lock():
    model = circle()
    other = circle("11", x=5000)
    engine = TrackRecognizer([model, other])
    assert drive(engine, model)["layout_id"] == "10"
    result = engine.update([5200, None, 0], 17, car_id=1)
    assert not result["layout_id"]
    engine.reset()
    assert drive(engine, model)["layout_id"] == "10"
    result = engine.update(model["centerline"][0], 17, car_id=1, provenance="demo")
    assert not result["layout_id"]


def test_storage_migration_is_lossless_and_failure_atomic(tmp_path):
    legacy_root = tmp_path / "track-maps"
    legacy_root.mkdir()
    model = circle()
    legacy = {
        "schema": 2,
        "layout_id": "10",
        "points": [[p[0], p[2]] for p in model["centerline"]],
        "versions": [{"revision": "original-history"}],
    }
    path = legacy_root / "10.json"
    path.write_text(json.dumps(legacy))
    original = path.read_bytes()
    store = TrackModelStore(tmp_path, {"10", "11"})
    assert store.migrate() == ["10"]
    assert path.read_bytes() == original
    loaded = store.load("10")
    assert loaded["legacy"] == legacy
    persisted = (store.root / "10.json").read_bytes()
    with patch("backend.app.track_store.os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save(circle(x=10))
    assert (store.root / "10.json").read_bytes() == persisted
    assert not (store.root / "10.tmp").exists()
    assert store.migrate() == []


def test_pack_checksum_merge_history_and_provenance(tmp_path):
    store = TrackModelStore(tmp_path, {"10", "11"})
    model = circle()
    for provenance in ("demo", "replay"):
        with pytest.raises(ValueError, match="cannot persist"):
            store.save(model, provenance=provenance)
    store.save(model)
    pack = store.export_pack(["10"])
    store.save(circle("11", x=5000))
    assert store.import_pack(pack) == ["10"]
    assert store.load("11") is not None
    broken = json.loads(pack)
    broken["models"][0]["sha256"] = "tampered"
    with pytest.raises(ValueError, match="checksum"):
        store.import_pack(json.dumps(broken).encode())
    for n in range(10):
        store.save(circle(x=n))
    assert len(store.load("10")["history"]) == 8


def test_layer_validation_and_independent_history(tmp_path):
    model = circle()
    store = TrackModelStore(tmp_path, {"10"})
    first = store.save_layers(model, {"zones": [{"id": "z", "name": "Start", "s_start": 1200, "s_end": 20}]})
    second = store.save_layers(model, {"zones": []})
    assert second["history"][0]["revision"] == first["revision"]
    assert store.load("10") is None
    with pytest.raises(ValueError):
        validate_layers({"zones": [{"id": "z", "name": "X", "s_start": -1, "s_end": 20}]}, model["length_m"])


def test_fusion_labels_observed_envelope_and_rejects_reverse():
    model = circle()
    points = model["centerline"] + [model["centerline"][0]]
    shifted = [[p[0] * 1.01, p[1], p[2] * 1.01] for p in points]
    fused = fuse_laps(model, [points, shifted])
    assert fused["source"]["accepted_laps"] == 2
    assert fused["edges"]["left"]["source"] == "observed-envelope"
    with pytest.raises(ValueError, match="No complete"):
        fuse_laps(model, [list(reversed(points))])


def test_streamed_bundle_ids_and_raw_world_coordinates():
    keys = [model["layout_id"] for model in iter_models()]
    assert len(keys) == len(set(keys)) == 101
    model = get_model("454")
    assert model["frame"] == "gt7-world"
    assert min(p[0] for p in model["centerline"]) < -1000
    assert get_model("not-a-layout") is None


def test_invalid_frame_and_document_hash():
    with pytest.raises(ValueError):
        build_model("10", [[0, 0], [100, 0], [0, 0]], {}, frame="screen")
    model = circle()
    broken = copy.deepcopy(model)
    broken["centerline"][0][0] += 1
    with pytest.raises(ValueError, match="checksum"):
        validate_model(broken, {"10"})
