"""Robust confirmed-lap fusion; observed spread is never labelled track limits."""

from __future__ import annotations

import bisect
import math
from statistics import median
from typing import Any, Sequence

from .track_model import TrackProgress, build_model, revision, world_points


def fuse_laps(model: dict[str, Any], laps: Sequence[Sequence[Sequence[float | None]]]) -> dict[str, Any]:
    """Fuse at most eight confirmed clean laps into two-metre median lateral bins.

    Reject incomplete, wrong-direction and outlier laps before contributing to
    the consensus. Callers retain raw laps separately in the append-only corpus.
    """
    if len(laps) > 8:
        raise ValueError("Fusion accepts at most eight laps per revision")
    progress = TrackProgress(model)
    accepted = []
    for raw in laps:
        points = world_points(raw)
        offsets = []
        distances = []
        previous = None
        traveled = 0.0
        backwards = 0
        for i, point in enumerate(points):
            heading = None
            if i:
                dx, dz = point[0] - points[i - 1][0], point[2] - points[i - 1][2]
                if math.hypot(dx, dz) > 200:
                    backwards += len(points)
                heading = math.atan2(dz, dx)
            hit = progress.project(point, heading=heading)
            if hit is None:
                continue
            if previous is not None:
                advance = (hit.s - previous + progress.length / 2) % progress.length - progress.length / 2
                backwards += advance < -8
                traveled += max(0, advance)
            previous = hit.s
            offsets.append((hit.s, hit.lateral_m))
            distances.append(hit.distance_m)
        if len(offsets) < len(points) * 0.9 or backwards or not 0.95 <= traveled / progress.length <= 1.05:
            continue
        if median(distances) > 15 or sorted(distances)[int(len(distances) * 0.95)] > 30:
            continue
        offsets.sort()
        extended = [
            (offsets[-1][0] - progress.length, offsets[-1][1]),
            *offsets,
            (offsets[0][0] + progress.length, offsets[0][1]),
        ]
        stations = [item[0] for item in extended]
        bins = []
        for station in model["s"]:
            right = min(bisect.bisect_right(stations, station), len(extended) - 1)
            a, b = extended[right - 1], extended[right]
            if b[0] - a[0] > 40:
                bins.append(None)
            else:
                t = (station - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0
                bins.append(a[1] + t * (b[1] - a[1]))
        if sum(value is not None for value in bins) / len(bins) >= 0.95:
            accepted.append(bins)
    if not accepted:
        raise ValueError("No complete, direction-consistent inlier lap to fuse")
    centreline = []
    left = []
    right = []
    for i, point in enumerate(model["centerline"]):
        offsets = [lap[i] for lap in accepted if lap[i] is not None]
        displacement = median(offsets) if offsets else 0
        nx, nz = -math.sin(model["heading"][i]), math.cos(model["heading"][i])
        centreline.append([point[0] + nx * displacement, point[1], point[2] + nz * displacement])
        for target, offset in ((left, max(offsets, default=0)), (right, min(offsets, default=0))):
            target.append([point[0] + nx * offset, point[1], point[2] + nz * offset])
    result = build_model(
        model["layout_id"],
        centreline + [centreline[0]],
        {
            "kind": "user-learned",
            "method": "median lateral fusion",
            "accepted_laps": len(accepted),
            "base_revision": model["revision"],
        },
    )
    result["edges"] = {
        "left": {"source": "observed-envelope", "label": "Observed driving envelope", "points": left},
        "right": {"source": "observed-envelope", "label": "Observed driving envelope", "points": right},
    }
    result["revision"] = revision(result)
    return result
