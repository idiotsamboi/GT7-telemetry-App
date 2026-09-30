"""Version-three world models and the single indexed track-progress primitive.

This module has no networking, application state, or receiver dependencies.
Runtime geometry is packed; JSON documents and spatial indexes are separate.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from array import array
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

CELL_M = 25.0
STEP_M = 2.0
MAX_POINTS = 40_000


def revision(document: dict[str, Any]) -> str:
    """Hash semantic model content without recursive history or its own hash."""
    content = {k: v for k, v in document.items() if k not in {"revision", "history"}}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def world_points(points: Sequence[Sequence[float | None]]) -> list[list[float | None]]:
    """Validate world positions, retaining unknown elevation as null."""
    if not 3 <= len(points) <= MAX_POINTS:
        raise ValueError("A track requires 3 to 40000 points")
    result = []
    for point in points:
        if len(point) not in (2, 3):
            raise ValueError("Positions must be [x,z] or [x,elevation,z]")
        p = [point[0], None, point[1]] if len(point) == 2 else list(point)
        for i, value in enumerate(p):
            if value is None and i == 1:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Coordinates must be finite metres")
            if not math.isfinite(value) or abs(value) > 1_000_000:
                raise ValueError("Coordinates outside the supported world frame")
        result.append(p)
    return result


def auto_corners(s: list[float], curvature: list[float], length: float) -> list[dict[str, Any]]:
    """Find sustained bends with hysteresis, merging closely spaced chicane peaks."""
    regions = []
    start = None
    for i, value in enumerate(curvature + [0.0] * 12):
        if start is None and abs(value) >= 0.006:
            start = i
        elif start is not None and abs(value) < 0.002:
            end = min(i, len(s) - 1)
            if s[end] - s[start] >= 12:
                if regions and s[start] - s[regions[-1][1]] < 25:
                    regions[-1][1] = end
                else:
                    regions.append([start, end])
            start = None
    result = []
    for start, end in regions:
        apex = max(range(start, end + 1), key=lambda i: abs(curvature[i]))
        result.append(
            {
                "id": f"T{len(result) + 1}",
                "name": f"T{len(result) + 1}",
                "s_start": s[start],
                "s_apex": s[apex],
                "s_end": min(s[end], length),
                "dir": "left" if curvature[apex] > 0 else "right",
                "source": "auto",
            }
        )
    return result


def build_model(
    layout_id: str,
    points: Sequence[Sequence[float | None]],
    source: dict[str, Any],
    *,
    frame: str = "gt7-world",
    preserve: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a closed two-metre model without changing translation, scale or direction."""
    if frame not in {"gt7-world", "normalized-legacy"}:
        raise ValueError("Unsupported coordinate frame")
    raw = world_points(points)
    if math.hypot(raw[0][0] - raw[-1][0], raw[0][2] - raw[-1][2]) > 100:
        raise ValueError("Open or incomplete route")
    if raw[-1] != raw[0]:
        raw.append(raw[0][:])
    distances = [0.0]
    for a, b in zip(raw, raw[1:]):
        span = math.hypot(b[0] - a[0], b[2] - a[2])
        if span > 200:
            raise ValueError("Route contains a gap over 200 metres")
        distances.append(distances[-1] + span)
    length = distances[-1]
    if not 100 <= length <= 80_000:
        raise ValueError("Route length outside supported bounds")
    count = math.ceil(length / STEP_M)
    centreline = []
    stations = []
    for i in range(count):
        station = length * i / count
        j = min(bisect.bisect_right(distances, station), len(raw) - 1)
        span = distances[j] - distances[j - 1]
        t = (station - distances[j - 1]) / span if span else 0.0
        a, b = raw[j - 1], raw[j]
        centreline.append(
            [round(a[k] + t * (b[k] - a[k]), 4) if a[k] is not None and b[k] is not None else None for k in range(3)]
        )
        stations.append(round(station, 4))
    headings = []
    for i, a in enumerate(centreline):
        b = centreline[(i + 1) % count]
        headings.append(math.atan2(b[2] - a[2], b[0] - a[0]))
    # A twenty-metre derivative suppresses vertices inherited from the source's 20m sampling.
    curvature = [
        round(
            math.atan2(
                math.sin(headings[(i + 5) % count] - headings[(i - 5) % count]),
                math.cos(headings[(i + 5) % count] - headings[(i - 5) % count]),
            )
            / (10 * length / count),
            6,
        )
        for i in range(count)
    ]
    model = {
        "schema": 3,
        "layout_id": str(layout_id),
        "frame": frame,
        "step_m": length / count,
        "centerline": centreline,
        "s": stations,
        "heading": headings,
        "curvature": curvature,
        "length_m": length,
        "source": source,
        "centerline_source": source,
        "edges": {side: {"source": "none", "points": []} for side in ("left", "right")},
        "walls": [],
        "runoff": [],
        "start_finish": {
            "point": centreline[0],
            "normal": [math.cos(headings[0]), math.sin(headings[0])],
            "s": 0.0,
            "source": "path origin; timing unverified",
        },
        "pit": {"points": [], "entry_s": None, "exit_s": None, "source": "none"},
        "corners": auto_corners(stations, curvature, length),
        "sectors": [],
        "zones": [],
        "history": [],
    }
    if preserve is not None:
        # Retain the complete original document, including exact points and old revisions.
        model["legacy"] = preserve
    model["revision"] = revision(model)
    return model


@dataclass(frozen=True, slots=True)
class Progress:
    """A projection in metres, with signed lateral offset and measured fit error."""

    s: float
    fraction: float
    lateral_m: float
    distance_m: float
    heading: float
    elevation_m: float | None
    segment: int


class TrackProgress:
    """Packed geometry with bounded local segment searches, shared by all consumers."""

    def __init__(self, model: dict[str, Any]) -> None:
        self.layout_id = model["layout_id"]
        self.revision = model["revision"]
        self.frame = model["frame"]
        self.length = float(model["length_m"])
        self.closed = True
        self.x = array("f", (p[0] for p in model["centerline"]))
        self.z = array("f", (p[2] for p in model["centerline"]))
        self.y = array("f", (p[1] if p[1] is not None else math.nan for p in model["centerline"]))
        self.s = array("f", model["s"])
        self.headings = array("f", model["heading"])
        self.grid: dict[tuple[int, int], array] = {}
        cells = defaultdict(list)
        for i in range(len(self.x)):
            j = (i + 1) % len(self.x)
            for gx in range(
                math.floor(min(self.x[i], self.x[j]) / CELL_M), math.floor(max(self.x[i], self.x[j]) / CELL_M) + 1
            ):
                for gz in range(
                    math.floor(min(self.z[i], self.z[j]) / CELL_M), math.floor(max(self.z[i], self.z[j]) / CELL_M) + 1
                ):
                    cells[gx, gz].append(i)
        self.grid = {key: array("I", value) for key, value in cells.items()}

    def candidates(
        self,
        position: Sequence[float | None],
        *,
        heading: float | None = None,
        previous_s: float | None = None,
        expected_m: float | None = None,
        corridor_m: float = 40.0,
    ) -> list[tuple[float, Progress]]:
        """Return at most eight plausible branches; heading/elevation disambiguate bridges."""
        if len(position) != 3 or position[0] is None or position[2] is None:
            return []
        x, y, z = position
        if not math.isfinite(x) or not math.isfinite(z):
            return []
        gx, gz = math.floor(x / CELL_M), math.floor(z / CELL_M)
        radius = math.ceil(corridor_m / CELL_M)
        seen = set()
        matches = []
        for dx in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                for i in self.grid.get((gx + dx, gz + dz), ()):
                    if i in seen:
                        continue
                    seen.add(i)
                    j = (i + 1) % len(self.x)
                    vx, vz = self.x[j] - self.x[i], self.z[j] - self.z[i]
                    norm = vx * vx + vz * vz
                    if norm < 0.0001:
                        continue
                    t = max(0.0, min(1.0, ((x - self.x[i]) * vx + (z - self.z[i]) * vz) / norm))
                    ex, ez = x - self.x[i] - t * vx, z - self.z[i] - t * vz
                    distance = math.hypot(ex, ez)
                    if distance > corridor_m:
                        continue
                    station = (self.s[i] + t * math.sqrt(norm)) % self.length
                    score = min((distance / 6.0) ** 2 / 2, 30.0)
                    elevation = self.y[i] + t * (self.y[j] - self.y[i])
                    if math.isnan(elevation):
                        elevation = None
                    if y is not None and elevation is not None and math.isfinite(y):
                        score += min(((y - elevation) / 3.0) ** 2 / 2, 30.0)
                    if heading is not None:
                        score += 12.0 * (1.0 - math.cos(heading - self.headings[i]))
                    if previous_s is not None:
                        advance = (station - previous_s + self.length / 2) % self.length - self.length / 2
                        if advance < -8:
                            continue
                        if expected_m is not None:
                            if abs(advance - expected_m) > max(50, expected_m * 2):
                                continue
                            score += ((advance - expected_m) / max(8.0, expected_m * 0.3)) ** 2 / 2
                    hit = Progress(
                        station,
                        station / self.length,
                        (vx * ez - vz * ex) / math.sqrt(norm),
                        distance,
                        self.headings[i],
                        elevation,
                        i,
                    )
                    matches.append((score, hit))
        matches.sort(key=lambda pair: pair[0])
        branches = []
        for score, hit in matches:
            if branches and score > branches[0][0] + 8:
                break
            if all(abs((hit.s - old.s + self.length / 2) % self.length - self.length / 2) > 8 for _, old in branches):
                branches.append((score, hit))
            if len(branches) == 8:
                break
        return branches

    def project(self, position: Sequence[float | None], **kwargs: Any) -> Progress | None:
        """Return the best unambiguous local projection, or unavailable."""
        choices = self.candidates(position, **kwargs)
        if not choices:
            return None
        score, best = choices[0]
        if any(other < score + 0.15 and abs(hit.s - best.s) > 50 for other, hit in choices[1:]):
            return None
        return best

    def match(self, points: Sequence[Sequence[float]], complete: bool = False) -> dict[str, float] | None:
        """Validate an ordered learned route using this same indexed progress primitive."""
        if len(points) < 12:
            return None
        errors = []
        advances = []
        agreement = []
        previous = None
        for a, b in zip(points, points[1:]):
            heading = math.atan2(b[1] - a[1], b[0] - a[0])
            hit = self.project([b[0], None, b[1]], heading=heading, corridor_m=45)
            if not hit:
                return None
            errors.append(hit.distance_m)
            agreement.append(math.cos(heading - hit.heading) > 0.5)
            if previous is not None:
                advances.append((hit.s - previous + self.length / 2) % self.length - self.length / 2)
            previous = hit.s
        coverage = sum(max(0, value) for value in advances) / self.length
        if sum(errors) / len(errors) > 15 or sum(agreement) / len(agreement) < 0.9:
            return None
        if any(value < -10 or value > 200 for value in advances):
            return None
        if complete and (not 0.90 <= coverage <= 1.08 or math.dist(points[0], points[-1]) > 75):
            return None
        return {"mean_error_m": sum(errors) / len(errors), "direction_agreement": sum(agreement) / len(agreement),
                "coverage": coverage}
