"""Evaluate vendored capture paths only against models built from separate surveys."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.track_bundle import iter_models  # noqa: E402
from backend.app.track_recognition import TrackRecognizer  # noqa: E402


def normalise(name: str) -> str:
    """Match names exactly using the existing catalogue normalizer."""
    return "".join(c.lower() for c in unicodedata.normalize("NFKD", name.replace("Grand Prix Layout", "GP Layout"))
                   if c.isalnum())


def main() -> None:
    """Keep capture-derived models out of held-out results to avoid testing on training data."""
    cache = ROOT / "data/reference-research/world"
    manifest = json.loads((cache / "manifest.json").read_text())
    raw = (cache / "vendor/circuits.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["files"]["vendor/circuits.json"]["sha256"]:
        raise ValueError("Capture source checksum mismatch")
    captures = json.loads(raw)
    surveyed = {normalise(m["name"]): m["layout_id"] for m in iter_models() if m["source"]["kind"] == "surveyed"}
    engine = TrackRecognizer(iter_models())
    results = []
    for capture in captures["captures"]:
        key = surveyed.get(normalise(capture["variation_name"]))
        points = capture.get("path", [])
        if not key or len(points) < 20:
            continue
        engine.reset()
        timestamp = 0.0
        distance = 0.0
        first = None
        false = set()
        for a, b in zip(points, points[1:]):
            dx, dz = b[0] - a[0], b[1] - a[1]
            span = math.hypot(dx, dz)
            dt = max(0.2, span / 50)
            timestamp += dt
            distance += span
            result = engine.update([b[0], None, b[1]], timestamp, speed=span / dt,
                                   velocity=[dx / dt, 0, dz / dt], car_id=1)
            if result["layout_id"] and first is None:
                first = {"layout_id": result["layout_id"], "distance_m": distance, "simulated_time_s": timestamp}
            if result["layout_id"] and result["layout_id"] != key:
                false.add(result["layout_id"])
        row = {"layout_id": key, "capture": capture["file"], "capture_sha256": capture["sha256"],
               "source_points": len(points), "first_lock": first, "false_locks": sorted(false),
               "closed_within_100m": math.dist(points[0], points[-1]) <= 100}
        results.append(row)
        print(key, first, sorted(false), flush=True)
    report = {"suite": "Vendor paths held out from surveyed model construction; no capture-derived models tested",
              "source": captures["source"], "source_checksum": hashlib.sha256(raw).hexdigest(),
              "simulated_speed_mps": 50, "limits": "20m source sampling; simulated timestamps; one start per capture",
              "captures": len(results), "false_lock_captures": sum(bool(r["false_locks"]) for r in results),
              "correct_first_locks": sum(bool(r["first_lock"] and r["first_lock"]["layout_id"] == r["layout_id"])
                                         for r in results), "results": results}
    (ROOT / "docs/recognition-capture-eval.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
