"""Read-only validation of a world reference and matcher against a recorded live lap."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.track_bundle import iter_models  # noqa: E402
from backend.app.track_recognition import TrackRecognizer  # noqa: E402


def main() -> None:
    """Query one indexed session, decimate to 5Hz, and never modify the source database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/telemetry.sqlite3")
    parser.add_argument("--session", required=True)
    parser.add_argument("--lap", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/track-recording-eval.json")
    args = parser.parse_args()
    engine = TrackRecognizer(iter_models())
    geometry = engine.models[args.layout]
    connection = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
    session = connection.execute("SELECT provenance FROM sessions WHERE id=?", (args.session,)).fetchone()
    if not session or session[0] != "live":
        raise ValueError("Validation requires a recording with live provenance")
    errors = []
    runtime_ms = []
    missed = 0
    first_lock = None
    false_locks = set()
    previous = -float("inf")
    start = None
    last_result = {}
    try:
        rows = connection.execute(
            "SELECT mono,payload FROM samples WHERE session=? AND lap_id=? ORDER BY mono",
            (args.session, args.lap),
        )
        for timestamp, payload in rows:
            if timestamp - previous < 0.199:
                continue
            previous = timestamp
            start = timestamp if start is None else start
            values = json.loads(payload)["values"]
            position = values.get("position")
            if not position:
                continue
            choices = geometry.candidates(position, corridor_m=100)
            if choices:
                errors.append(choices[0][1].distance_m)
            else:
                missed += 1
            before = time.perf_counter_ns()
            flags = values.get("flags", 0)
            last_result = engine.update(
                position,
                timestamp,
                speed=values.get("speed", 0),
                velocity=values.get("velocity"),
                lap=values.get("lap"),
                car_id=values.get("car_id"),
                provenance="live",
                active=bool(flags & 1 and not flags & 6),
            )
            runtime_ms.append((time.perf_counter_ns() - before) / 1_000_000)
            locked = last_result["layout_id"]
            if locked and first_lock is None:
                first_lock = {
                    "layout_id": locked,
                    "time_s": timestamp - start,
                    "evidence_distance_m": last_result["distance_m"],
                }
            if locked and locked != args.layout:
                false_locks.add(locked)
    finally:
        connection.close()
    if not errors:
        raise ValueError("No usable positions in the selected live lap")
    report = {
        "session_id": args.session,
        "lap_id": args.lap,
        "layout_id": args.layout,
        "reference_revision": geometry.revision,
        "reference_frame": "unmodified GT7 world x/z metres",
        "provenance": "recorded live",
        "samples": len(errors),
        "outside_100m_corridor": missed,
        "median_distance_m": statistics.median(errors),
        "p95_distance_m": sorted(errors)[int(0.95 * (len(errors) - 1))],
        "first_lock": first_lock,
        "false_locks": sorted(false_locks),
        "runtime_p50_ms": statistics.median(runtime_ms),
        "runtime_p95_ms": sorted(runtime_ms)[int(0.95 * (len(runtime_ms) - 1))],
        "final_state": last_result,
        "limits": "One recorded lap; not a live PS5 check, held-out catalogue evaluation, or A55 measurement",
    }
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "final_state"}, indent=2))


if __name__ == "__main__":
    main()
