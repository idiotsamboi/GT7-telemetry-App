"""Reproducible world-model recognition probes; synthetic trials are labelled explicitly."""

from __future__ import annotations

import argparse
import gc
import json
import math
import platform
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.track_bundle import iter_models  # noqa: E402
from backend.app.track_recognition import TrackRecognizer  # noqa: E402


def percentile(values: list[float], fraction: float) -> float | None:
    """Return an empirical nearest-rank percentile, or unavailable for an empty sample."""
    return sorted(values)[min(len(values) - 1, math.ceil(len(values) * fraction) - 1)] if values else None


def retained_size(value: Any, seen: set[int] | None = None) -> int:
    """Count owned Python object memory once, including packed arrays and indexes."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(retained_size(k, seen) + retained_size(v, seen) for k, v in value.items())
    elif isinstance(value, (tuple, list, set, frozenset)):
        size += sum(retained_size(item, seen) for item in value)
    elif hasattr(value, "__dict__"):
        size += retained_size(vars(value), seen)
    return size


def main() -> None:
    """Measure randomized starts with noise and dropouts without using the live receiver."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", default="docs/recognition-eval.json")
    args = parser.parse_args()
    engine = TrackRecognizer(iter_models())
    gc.collect()
    model_bytes = retained_size(engine)
    durations = []
    layouts = []
    confusion = Counter()
    rng = random.Random(71227)
    for key in list(engine.models)[: args.limit or None]:
        geometry = engine.models[key]
        trials = []
        for trial in range(args.trials):
            engine.manual = ""
            engine.reset()
            start = rng.randrange(len(geometry.x))
            sigma = (1, 3, 5)[trial % 3]
            first = None
            eligible_distance = None
            separated = set()
            required = set(engine.meta[key].get("distinguishing") or {})
            states = Counter()
            false = []
            # The user-approved window starts after route-distinguishing evidence.
            # Eligibility comes from build-time geometry, independently of matcher confidence.
            for step in range(math.ceil((geometry.length + 1500) / 10)):
                if step and rng.random() < 0.04:
                    continue
                i = (start + round(step * 10 / (geometry.length / len(geometry.x)))) % len(geometry.x)
                heading = geometry.headings[i]
                for other, ranges in (engine.meta[key].get("distinguishing") or {}).items():
                    if any(begin <= geometry.s[i] <= end for begin, end in ranges):
                        separated.add(other)
                if eligible_distance is None and separated >= required:
                    eligible_distance = step * 10
                position = [
                    geometry.x[i] + rng.gauss(0, sigma),
                    float(geometry.y[i]) if math.isfinite(geometry.y[i]) else None,
                    geometry.z[i] + rng.gauss(0, sigma),
                ]
                before = time.perf_counter_ns()
                result = engine.update(
                    position,
                    step * 0.2,
                    speed=50,
                    velocity=[50 * math.cos(heading), 0, 50 * math.sin(heading)],
                    car_id=1,
                )
                durations.append((time.perf_counter_ns() - before) / 1_000_000)
                states[result["state"]] += 1
                locked = result["layout_id"]
                if locked and first is None:
                    first = {"layout_id": locked, "time_s": step * 0.2, "distance_m": step * 10}
                    confusion[f"{key}->{locked}"] += 1
                if locked and locked != key:
                    false.append(locked)
                if eligible_distance is not None and step * 10 >= eligible_distance + 1200:
                    break
            trials.append(
                {"sigma_m": sigma, "first_lock": first, "false_locks": sorted(set(false)), "states": dict(states),
                 "distinguishing_distance_m": eligible_distance,
                 "within_distinguishing_window": bool(first and first["layout_id"] == key
                     and eligible_distance is not None and first["distance_m"] <= eligible_distance + 1000)}
            )
        locks = [t["first_lock"] for t in trials if t["first_lock"] and t["first_lock"]["layout_id"] == key]
        layouts.append(
            {
                "layout_id": key,
                "name": engine.meta[key]["name"],
                "trials": trials,
                "correct_lock_rate": len(locks) / len(trials),
                "within_1km_rate": sum(lock["distance_m"] <= 1000 for lock in locks) / len(trials),
                "within_distinguishing_window_rate": sum(t["within_distinguishing_window"] for t in trials) / len(trials),
                "false_lock_trials": sum(bool(t["false_locks"]) for t in trials),
                "median_lock_distance_m": statistics.median([lock["distance_m"] for lock in locks]) if locks else None,
                "p95_lock_distance_m": percentile([lock["distance_m"] for lock in locks], 0.95),
            }
        )
        print(key, layouts[-1]["within_1km_rate"], layouts[-1]["false_lock_trials"], flush=True)
    report = {
        "suite": "synthetic perturbations of bundled model geometry; not independent held-out validation",
        "seed": 71227,
        "processor": platform.processor(),
        "python": platform.python_version(),
        "world_layouts": len(engine.models),
        "evaluated_layouts": len(layouts),
        "trials_per_layout": args.trials,
        "model_retained_bytes": model_bytes,
        "runtime_ms": {
            "p50": percentile(durations, 0.5),
            "p95": percentile(durations, 0.95),
            "samples": len(durations),
        },
        "false_lock_trials": sum(row["false_lock_trials"] for row in layouts),
        "within_1km_rate": statistics.mean(row["within_1km_rate"] for row in layouts),
        "acceptance_rule": "Within 1km after independently determined distinguishing evidence; no guessing beforehand",
        "within_distinguishing_window_rate": statistics.mean(row["within_distinguishing_window_rate"] for row in layouts),
        "confusion": dict(confusion),
        "layouts": layouts,
        "unverified": ["Orange Pi A55 timing", "pit exit", "live PS5"],
    }
    destination = ROOT / args.output
    destination.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"layouts", "confusion"}}, indent=2))


if __name__ == "__main__":
    main()
