"""Build-time route discrimination and geometric equivalence, without telemetry noise."""

from __future__ import annotations

import math
from typing import Any

from .track_model import TrackProgress


def separating_intervals(a: TrackProgress, b: TrackProgress) -> tuple[list[list[float]], bool, float]:
    """Sample ordered geometry every 20m; report >20m separation and <=5m equivalence.

    Same-position reverse travel is distinct. Intervals conservatively start one
    sample after divergence and end one sample before convergence.
    """
    separated = []
    equivalent = abs(a.length - b.length) / max(a.length, b.length) < 0.01
    samples = []
    for i in range(0, len(a.x), 10):
        hits = b.candidates([a.x[i], None, a.z[i]], heading=a.headings[i], corridor_m=22)
        hit = hits[0][1] if hits else None
        direction = hit is not None and math.cos(hit.heading - a.headings[i]) > 0.9
        distinct = hit is None or hit.distance_m > 20 or not direction
        equivalent = equivalent and hit is not None and hit.distance_m <= 5 and direction
        samples.append((float(a.s[i]), distinct))
    start = None
    for i, (station, distinct) in enumerate(samples):
        if distinct and start is None:
            start = station
        if start is not None and (not distinct or i == len(samples) - 1):
            end = samples[i - 1][0] if not distinct else station
            if end - start > 40:
                separated.append([start + 20, end - 20])
            start = None
    # Circular longest contiguous shared run: start anywhere, including across S/F.
    longest = 0.0
    run = 0.0
    spacing = a.length / len(samples)
    for _, distinct in samples * 2:
        run = 0.0 if distinct else min(a.length, run + spacing)
        longest = max(longest, run)
    return separated, bool(equivalent), longest


def annotate_overlaps(models: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach immutable discrimination ranges and conservative equivalence classes."""
    geometry = {key: TrackProgress(model) for key, model in models.items()}
    report = []
    for key, model in models.items():
        model["distinguishing"] = {}
        model["equivalence_class"] = [key]
        for other, candidate in models.items():
            if key == other or model.get("venue_id") != candidate.get("venue_id"):
                continue
            ranges, equivalent, shared = separating_intervals(geometry[key], geometry[other])
            model["distinguishing"][other] = ranges
            if equivalent:
                model["equivalence_class"].append(other)
            if shared > 1000:
                report.append(
                    {
                        "layout_id": key,
                        "other_layout_id": other,
                        "longest_shared_m": round(shared, 1),
                        "geometrically_equivalent": equivalent,
                    }
                )
    # Equivalence requires both directed comparisons, not just subset containment.
    for key, model in models.items():
        model["equivalence_class"] = sorted(
            other for other in model["equivalence_class"] if key in models[other]["equivalence_class"]
        )
    return report
