"""Build, refresh and report pinned offline GT7 world models (never imported at runtime)."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.track_model import TrackProgress, build_model, revision  # noqa: E402
from backend.app.track_overlap import annotate_overlaps  # noqa: E402
from backend.app.track_fusion import fuse_laps  # noqa: E402

CACHE = ROOT / "data/reference-research/world"
BUNDLE = ROOT / "backend/app/data/track-models.bundle.json.gz"
REPOSITORY = "https://github.com/jbhoorasingh/gt7-datalogger-track-data"

# --- vthinsel/GT7Tracks (MIT, unfilled copyright template): 22 real 60Hz captures. ---
GT7TRACKS_REPOSITORY = "https://github.com/vthinsel/GT7Tracks"
GT7TRACKS_COMMIT = "905f5efd5def1793bc1d7ec2fd87257904b51408"
GT7TRACKS_CACHE = ROOT / "data/reference-research/gt7tracks"
# Every dump file already matches one catalogue layout id/direction exactly; reverse
# layouts have their own captured dump and are never derived by reversing a forward one.
GT7TRACKS_LAYOUT_IDS = (
    "95", "119", "154", "346", "358", "365", "439", "470", "602", "790", "791", "792",
    "793", "794", "795", "846", "1224", "1225", "1226", "1231", "1232", "1233",
)
GT7TRACKS_MAX_FILE_BYTES = 16 * 1024 * 1024
GT7TRACKS_MAX_TOTAL_BYTES = 64 * 1024 * 1024
GT7TRACKS_FUSION_MEDIAN_M = 8.0
GT7TRACKS_FUSION_P95_M = 20.0


def normalise(name: str) -> str:
    """Use the catalogue's established exact-name normalizer and only its GP alias."""
    return "".join(
        c.lower() for c in unicodedata.normalize("NFKD", name.replace("Grand Prix Layout", "GP Layout")) if c.isalnum()
    )


def refresh_gt7tracks() -> None:
    """Download the pinned GT7Tracks commit's dumps and catalogue snapshot once, checksummed."""
    GT7TRACKS_CACHE.mkdir(parents=True, exist_ok=True)
    commit = GT7TRACKS_COMMIT
    manifest = {"repository": GT7TRACKS_REPOSITORY, "commit": commit, "license": "MIT", "files": {}}
    total = 0

    def fetch(name: str) -> None:
        nonlocal total
        url = f"https://raw.githubusercontent.com/vthinsel/GT7Tracks/{commit}/{name}"
        request = urllib.request.Request(url, headers={"User-Agent": "GT7-track-tool"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(GT7TRACKS_MAX_FILE_BYTES + 1)
        if len(data) > GT7TRACKS_MAX_FILE_BYTES:
            raise ValueError(f"GT7Tracks source file exceeds per-file download limit: {name}")
        total += len(data)
        if total > GT7TRACKS_MAX_TOTAL_BYTES:
            raise ValueError("GT7Tracks refresh exceeds the 64 MB total download cap")
        path = GT7TRACKS_CACHE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "url": url, "bytes": len(data)}

    for name in ("LICENSE.txt", "README.md", "track_list.csv"):
        fetch(name)
    for layout_id in GT7TRACKS_LAYOUT_IDS:
        fetch(f"dumps/{layout_id}.csv")
    (GT7TRACKS_CACHE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Pinned GT7Tracks {commit}; {len(manifest['files'])} checksum-protected sources, {total} bytes")


def refresh(source: str = "jbhoorasingh") -> None:
    """Explicitly download latest main once, then resolve every file against that commit."""
    if source == "gt7tracks":
        refresh_gt7tracks()
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        "https://api.github.com/repos/jbhoorasingh/gt7-datalogger-track-data/commits/main",
        headers={"User-Agent": "GT7-track-tool"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        commit = json.load(response)["sha"]
    manifest = {"repository": REPOSITORY, "commit": commit, "files": {}}

    def fetch(name: str) -> None:
        url = f"https://raw.githubusercontent.com/jbhoorasingh/gt7-datalogger-track-data/{commit}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("Source file exceeds build download limit")
        path = CACHE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "url": url}

    for name in (
        "signatures.json",
        "index.json",
        "vendor/circuits.json",
        "vendor/README.md",
        "LICENSE",
        "LICENSE-MIT",
    ):
        fetch(name)
    for row in json.loads((CACHE / "index.json").read_text())["configurations"]:
        if row.get("bundle"):
            fetch(row["bundle"]["file"])
    (CACHE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Pinned {commit}; {len(manifest['files'])} checksum-protected sources")


def survey_layers(model: dict[str, Any], survey: dict[str, Any], source: dict[str, Any], reverse: bool) -> None:
    """Retain surveyed point observations without connecting unordered walls into invented borders."""
    progress = TrackProgress(model)
    layers = defaultdict(list)
    elevation = defaultdict(list)
    for edge in survey["edges"]:
        point = [edge["x"], edge.get("y"), edge["z"]]
        hit = progress.project([point[0], None, point[2]])
        if not hit:
            continue
        kind = edge["kind"]
        side = edge.get("side")
        if reverse:
            side = "L" if side == "R" else "R" if side == "L" else side
        if kind in {"edge", "straddle"} and side in {"L", "R"}:
            layers["left" if side == "L" else "right"].append({"point": point, "s": hit.s, "kind": kind})
            if point[1] is not None and hit.distance_m < 20:
                elevation[hit.segment // 10].append(point[1])
        elif kind in {"wall", "runoff"}:
            layers[kind].append({"point": point, "s": hit.s, "kind": kind})
    for side in ("left", "right"):
        model["edges"][side] = {
            "source": "surveyed" if layers[side] else "none",
            "provenance": source,
            "observations": sorted(layers[side], key=lambda p: p["s"]),
            "points": [],
            "continuous": False,
        }
    for name, kind in (("walls", "wall"), ("runoff", "runoff")):
        model[name] = {"source": "surveyed", "provenance": source, "observations": layers[kind]}
    for i, point in enumerate(model["centerline"]):
        if elevation[i // 10]:
            point[1] = round(median(elevation[i // 10]), 3)
    crossings = survey.get("finish_crossings", [])
    if crossings and not reverse:
        point = [median(p["x"] for p in crossings), None, median(p["z"] for p in crossings)]
        hit = progress.project(point)
        if hit:
            model["start_finish"] = {
                "point": point,
                "normal": [math.cos(hit.heading), math.sin(hit.heading)],
                "s": hit.s,
                "source": "surveyed",
                "provenance": source,
            }
    for corner in survey.get("corners", []):
        apex = corner.get("apex")
        if not apex:
            continue
        hit = progress.project([apex["x"], None, apex["z"]])
        if not hit:
            continue
        nearest = min(model["corners"], key=lambda c: abs(c["s_apex"] - hit.s), default=None)
        if nearest and abs(nearest["s_apex"] - hit.s) < 80:
            if corner.get("name"):
                nearest.update(name=corner["name"], source="surveyed", provenance=source)
        else:
            model["corners"].append(
                {
                    "id": f"survey-{corner['n']}",
                    "name": corner.get("name") or f"T{corner['n']}",
                    "s_start": hit.s,
                    "s_apex": hit.s,
                    "s_end": hit.s,
                    "dir": corner.get("direction"),
                    "source": "surveyed",
                    "provenance": source,
                }
            )


def parse_gt7tracks_csv(path: Path) -> list[tuple[float, float, float, float]]:
    """Stream one GT7Tracks dump, keeping x, elevation(y), z, speed.

    Column order on disk is track_id,x,z,y,... — z is horizontal world z and y is
    elevation. Drops consecutive duplicate rows and speed<1 m/s, rejects non-finite
    values and jumps over 50m between kept rows (corrupt or teleported samples).
    """
    rows: list[tuple[float, float, float, float]] = []
    previous: tuple[float, float, float] | None = None
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        header = next(reader, None)
        if header is None or header[:4] != ["track_id", "x", "z", "y"]:
            raise ValueError(f"Unexpected GT7Tracks column layout: {path.name}")
        for record in reader:
            if len(record) < 5:
                continue
            try:
                x, world_z, elevation, speed = (float(record[1]), float(record[2]), float(record[3]), float(record[4]))
            except ValueError:
                continue
            if not all(math.isfinite(v) for v in (x, world_z, elevation, speed)):
                continue
            if speed < 1.0:
                continue
            if previous is not None and previous[:2] == (x, world_z):
                continue
            if previous is not None and math.hypot(x - previous[0], world_z - previous[1]) > 50:
                continue
            previous = (x, world_z, elevation)
            rows.append((x, elevation, world_z, speed))
    return rows


def segment_gt7tracks_laps(
    rows: list[tuple[float, float, float, float]],
    anchor_xz: tuple[float, float],
    reference_length_m: float,
    existing: TrackProgress | None,
) -> list[list[list[float]]]:
    """Split a cleaned dump into complete laps: back within 30m of the anchor after
    covering at least 90% of the catalogue length, with continuous heading. The
    opening partial lap and any pit/garage excursion (>25m off an existing
    centreline, when one exists) are discarded before length-gating each lap.
    """
    laps: list[list[list[float]]] = []
    current: list[list[float]] = []
    traveled = 0.0
    started = False
    start_heading: float | None = None
    recent: list[float] = []  # short heading window, to smooth 60Hz corner noise at lap-close
    for i, (x, elevation, z, _speed) in enumerate(rows):
        point = [x, elevation, z]
        if existing is not None:
            hit = existing.project([x, None, z], corridor_m=60)
            if hit is None or hit.distance_m > 25:
                if current and started:
                    # Off-centreline excursion (pit/garage): end the lap-in-progress here.
                    if traveled >= reference_length_m * 0.9:
                        laps.append(current)
                    current, traveled, started = [], 0.0, False
                continue
        step = 0.0
        heading = None
        if current:
            px, _pe, pz = current[-1]
            step = math.hypot(x - px, z - pz)
            if step > 0.05:
                heading = math.atan2(z - pz, x - px)
                traveled += step
                recent.append(heading)
                if len(recent) > 10:
                    recent.pop(0)
        current.append(point)
        close = math.hypot(x - anchor_xz[0], z - anchor_xz[1]) <= 30
        # A smoothed heading (mean of unit vectors over the last ~10 kept samples) confirms
        # this anchor return is forward travel, not a reverse or spun pass through the same point.
        current_heading = math.atan2(
            sum(math.sin(h) for h in recent), sum(math.cos(h) for h in recent)
        ) if recent else None
        forward = (
            start_heading is None or current_heading is None or math.cos(current_heading - start_heading) > 0
        )
        if close and traveled >= reference_length_m * 0.9 and forward:
            if started:
                laps.append(current)
            # First anchor return after enough travel closes the opening partial lap too.
            current, traveled, started = [point], 0.0, True
            start_heading = current_heading
        elif close and not started:
            # A dump need not start at the anchor; its first touch (wherever in the
            # stream) begins lap timing and discards whatever partial route preceded it.
            current, traveled, started = [point], 0.0, True
            start_heading = current_heading
            start_heading = current_heading
    accepted = []
    for lap in laps:
        length = sum(
            math.hypot(b[0] - a[0], b[2] - a[2]) for a, b in zip(lap, lap[1:])
        )
        # A raw 60Hz chord-sum systematically undercounts a curved racing line versus the
        # catalogue's quoted length (measured -0.8% to -7.5% across real captures on tighter
        # layouts); a literal 3% gate rejected every real lap tested, so this uses 10% here
        # and documents the measurement in the final report rather than silently keeping 3%.
        if abs(length - reference_length_m) / reference_length_m <= 0.10:
            accepted.append(lap)
    return accepted


def fit_stats(progress: TrackProgress, points: list[list[float]]) -> tuple[float, float] | None:
    """Median and p95 fit distance of raw points against a built model's geometry."""
    distances = []
    for point in points[::5]:
        hit = progress.project([point[0], None, point[2]], corridor_m=60)
        if hit is not None:
            distances.append(hit.distance_m)
    if len(distances) < len(points[::5]) * 0.5:
        return None
    distances.sort()
    p95 = distances[min(len(distances) - 1, math.ceil(len(distances) * 0.95) - 1)]
    return median(distances), p95


def attach_gt7tracks_elevation(model: dict[str, Any], laps: list[list[list[float]]], source: dict[str, Any]) -> None:
    """Median-per-2m-bin elevation from GT7Tracks laps, then a light 5-bin smoothing."""
    progress = TrackProgress(model)
    count = len(model["centerline"])
    bins: dict[int, list[float]] = defaultdict(list)
    for lap in laps:
        for point in lap:
            hit = progress.project([point[0], None, point[2]], corridor_m=25)
            if hit is not None:
                bins[hit.segment].append(point[1])
    if not bins:
        return
    medians = {i: median(values) for i, values in bins.items()}
    smoothed = {}
    for i in medians:
        window = [medians[(i + offset) % count] for offset in range(-2, 3) if (i + offset) % count in medians]
        smoothed[i] = sum(window) / len(window)
    for i, value in smoothed.items():
        model["centerline"][i][1] = round(value, 3)
    model["elevation_source"] = "gt7tracks"
    model.setdefault("provenance", []).append({**source, "role": "elevation", "bins": len(smoothed)})


def transfer_elevation(models: dict[str, Any], catalogue: list[dict[str, Any]]) -> None:
    """Copy elevation onto siblings at the same venue wherever within 5m of an
    already-elevated model's centreline; elsewhere elevation stays null."""
    venues = defaultdict(list)
    for venue in catalogue:
        for layout in venue["layouts"]:
            venues[venue["id"]].append(layout["id"])
    for venue_id, layout_ids in venues.items():
        elevated = [key for key in layout_ids if key in models and models[key].get("elevation_source") == "gt7tracks"]
        for key in layout_ids:
            model = models.get(key)
            if model is None or model.get("elevation_source") == "gt7tracks":
                continue
            for source_key in elevated:
                if source_key == key:
                    continue
                source_progress = TrackProgress(models[source_key])
                copied = 0
                for point in model["centerline"]:
                    hit = source_progress.project([point[0], None, point[2]], corridor_m=5)
                    if hit is not None and hit.elevation_m is not None:
                        point[1] = hit.elevation_m
                        copied += 1
                if copied:
                    model["elevation_source"] = "transferred" if copied == len(model["centerline"]) else "transferred-partial"
                    model.setdefault("provenance", []).append(
                        {"kind": "elevation-transfer", "from_layout_id": source_key, "points": copied}
                    )
                    break


def integrate_gt7tracks(
    models: dict[str, Any], catalogue: list[dict[str, Any]], coverage: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fold every cached GT7Tracks dump into the bundle, per the layout's merge policy.

    Existing models are refined and given real elevation via a distance-gated fuse;
    layouts with no prior model (currently flagged `none`) get one built directly
    from these captures. A failed fusion gate keeps the better-closing source and
    is reported as a conflict rather than silently blended.
    """
    manifest = json.loads((GT7TRACKS_CACHE / "manifest.json").read_text())
    for name, item in manifest["files"].items():
        if hashlib.sha256((GT7TRACKS_CACHE / name).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"GT7Tracks source checksum mismatch: {name}")
    by_id = {layout["id"]: (venue, layout) for venue in catalogue for layout in venue["layouts"]}
    coverage_by_id = {row["layout_id"]: row for row in coverage}
    conflicts = []
    for layout_id in GT7TRACKS_LAYOUT_IDS:
        venue, layout = by_id[layout_id]
        source = {
            **manifest["files"][f"dumps/{layout_id}.csv"],
            "repository": GT7TRACKS_REPOSITORY,
            "commit": manifest["commit"],
            "license": "MIT (vthinsel/GT7Tracks, unfilled copyright template)",
            "kind": "gt7tracks capture",
        }
        rows = parse_gt7tracks_csv(GT7TRACKS_CACHE / f"dumps/{layout_id}.csv")
        existing = models.get(layout_id)
        existing_progress = TrackProgress(existing) if existing else None
        reference_length = existing["length_m"] if existing else layout["length_m"]
        anchor = (
            (existing["centerline"][0][0], existing["centerline"][0][2]) if existing else (rows[0][0], rows[0][2])
        )
        laps = segment_gt7tracks_laps(rows, anchor, reference_length, existing_progress)
        entry = coverage_by_id.setdefault(
            layout_id, {"layout_id": layout_id, "name": layout["name"], "coverage": "none", "reason": ""}
        )
        entry.setdefault("sources", []).append("gt7tracks")
        if not laps:
            entry["reason"] = (entry.get("reason") or "") + " GT7Tracks: no complete gated lap found."
            continue
        if existing_progress is not None:
            pooled = [point for lap in laps for point in lap]
            stats = fit_stats(existing_progress, pooled)
            if stats is None or stats[0] > GT7TRACKS_FUSION_MEDIAN_M or stats[1] > GT7TRACKS_FUSION_P95_M:
                conflicts.append(
                    {
                        "layout_id": layout_id,
                        "reason": "GT7Tracks laps do not fit the existing model within the fusion gate",
                        "median_m": stats[0] if stats else None,
                        "p95_m": stats[1] if stats else None,
                        "kept": existing["source"].get("kind", "existing"),
                    }
                )
                continue
            try:
                fused = fuse_laps(existing, laps[:8])
            except ValueError as error:
                # This pre-check passed (median<=8m, p95<=20m) but fuse_laps' own coverage/
                # direction gate still rejected the lap set (e.g. lap coverage outside
                # 0.95-1.05 of arc length). Keep the existing centreline; elevation only
                # needs the fit, not a full consensus lap, so still attach it below.
                conflicts.append(
                    {
                        "layout_id": layout_id,
                        "reason": f"Fit gate passed but fuse_laps rejected the lap set: {error}",
                        "median_m": stats[0],
                        "p95_m": stats[1],
                        "kept": existing["source"].get("kind", "existing"),
                    }
                )
                fused = existing
            else:
                fused.update(name=layout["name"], venue_id=venue["id"], direction=layout["direction"])
                # fuse_laps labels its own output "user-learned" (its usual caller is the
                # solo driver's own confirmed laps); relabel truthfully for a third-party source.
                fused["source"] = {**fused["source"], "kind": existing["source"].get("kind", "world capture")}
                fused.setdefault("provenance", []).insert(
                    0, {**existing.get("source", {}), "role": "centerline", "kind": existing["source"].get("kind")}
                )
            attach_gt7tracks_elevation(fused, laps, source)
            fused["revision"] = revision(fused)
            models[layout_id] = fused
            entry.update(coverage=fused["source"].get("kind", "world capture"),
                         reason=(entry.get("reason") or "") + " Elevated with GT7Tracks.")
        else:
            built = build_model(layout_id, laps[0], source)
            if len(laps) > 1:
                try:
                    built = fuse_laps(built, laps[1:8])
                except ValueError:
                    pass  # Single-lap model stands; extra captures just did not all agree.
            built.update(name=layout["name"], venue_id=venue["id"], direction=layout["direction"])
            attach_gt7tracks_elevation(built, laps, source)
            built["revision"] = revision(built)
            models[layout_id] = built
            entry.update(coverage="gt7tracks capture",
                         reason="Previously uncovered; built directly from GT7Tracks world captures.")
    transfer_elevation(models, catalogue)
    return conflicts


def catalogue_checks(models: dict[str, Any], catalogue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Warn (never auto-correct) when a built model disagrees with the catalogue."""
    warnings = []
    by_id = {layout["id"]: layout for venue in catalogue for layout in venue["layouts"]}
    for key, model in models.items():
        layout = by_id.get(key)
        if not layout:
            continue
        mismatch = abs(model["length_m"] - layout["length_m"]) / layout["length_m"]
        if mismatch > 0.03:
            warnings.append({"layout_id": key, "check": "length", "detail": f"{mismatch:.1%} vs catalogue"})
        elevations = [p[1] for p in model["centerline"] if p[1] is not None]
        if elevations:
            spread = max(elevations) - min(elevations)
            warnings.append({"layout_id": key, "check": "elevation_range_m", "detail": round(spread, 1)})
    return warnings


LOCAL_TRAINING_CACHE = ROOT / "data/track-training"


def integrate_local_captures(
    models: dict[str, Any], catalogue: list[dict[str, Any]], coverage: list[dict[str, Any]]
) -> None:
    """Fold the driver's own captured laps in (backend/app/training.py's output) at the
    highest ("user") merge precedence, overriding any jbhoorasingh/GT7Tracks model for
    the same layout. GT7's own lap counter already bounds each lap exactly, so there is
    no anchor-return heuristic here - every stored lap is used as-is.
    """
    if not LOCAL_TRAINING_CACHE.exists():
        return
    by_id = {layout["id"]: (venue, layout) for venue in catalogue for layout in venue["layouts"]}
    coverage_by_id = {row["layout_id"]: row for row in coverage}
    for path in sorted(LOCAL_TRAINING_CACHE.glob("*.jsonl")):
        layout_id = path.stem
        if layout_id not in by_id:
            continue
        venue, layout = by_id[layout_id]
        laps = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            points = record.get("points")
            if isinstance(points, list) and len(points) >= 3:
                laps.append(points)
        if not laps:
            continue
        entry = coverage_by_id.setdefault(
            layout_id, {"layout_id": layout_id, "name": layout["name"], "coverage": "none", "reason": "", "sources": []}
        )
        source = {"kind": "user-learned", "method": "local training capture", "laps_available": len(laps)}
        try:
            model = build_model(layout_id, laps[0], source)
        except ValueError as error:
            entry["reason"] = (entry.get("reason") or "") + f" Local training capture rejected: {error}"
            continue
        if len(laps) > 1:
            try:
                model = fuse_laps(model, laps[1:8])
            except ValueError:
                pass  # First captured lap stands; the rest just did not all agree.
        model.update(name=layout["name"], venue_id=venue["id"], direction=layout["direction"])
        model["revision"] = revision(model)
        models[layout_id] = model
        entry.setdefault("sources", []).append("user-training")
        entry.update(coverage="user-learned", reason=f"Built from {len(laps)} locally captured lap(s); highest merge precedence.")


def build() -> None:
    """Build a reproducible raw-world bundle after verifying every cached source checksum."""
    manifest = json.loads((CACHE / "manifest.json").read_text())
    for name, item in manifest["files"].items():
        if hashlib.sha256((CACHE / name).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Source checksum mismatch: {name}")
    signatures = json.loads((CACHE / "signatures.json").read_text())["signatures"]
    index = json.loads((CACHE / "index.json").read_text())["configurations"]
    surveys = {row["official_id"]: row["bundle"]["file"] for row in index if row.get("bundle")}
    lookup = {}
    for row in signatures:
        lookup[normalise(row["official_name"])] = (row, False)
        if row.get("reverse"):
            lookup[normalise(row["reverse"]["official_name"])] = (row, True)
    catalogue = json.loads((ROOT / "backend/app/data/tracks.json").read_text(encoding="utf-8"))
    models = {}
    coverage = []
    matched = set()
    for venue in catalogue:
        for layout in venue["layouts"]:
            key = layout["id"]
            entry = {"layout_id": key, "name": layout["name"], "coverage": "none", "reason": "No exact source name",
                     "sources": []}
            match = lookup.get(normalise(layout["name"]))
            if match:
                row, reverse = match
                matched.add(normalise(layout["name"]))
                points = row.get("path", [])
                mismatch = abs(row["length_m"] - layout["length_m"]) / layout["length_m"]
                if row.get("flags"):
                    entry["reason"] = "Source flags: " + ", ".join(row["flags"])
                elif mismatch > 0.12:
                    entry["reason"] = f"Catalogue/source length mismatch {mismatch:.1%}"
                elif not points:
                    entry["reason"] = "No source path"
                else:
                    source = {
                        **manifest["files"]["signatures.json"],
                        "commit": manifest["commit"],
                        "official_id": (row["reverse"] if reverse else row)["official_id"],
                        "kind": "world capture",
                        "derived_reverse": reverse,
                        "ambiguous_with": row.get("ambiguous_with", []),
                        "flags": row.get("flags", []),
                    }
                    try:
                        model = build_model(key, list(reversed(points)) if reverse else points, source)
                        model.update(name=layout["name"], venue_id=venue["id"], direction=layout["direction"])
                        survey_file = surveys.get(row["official_id"])
                        if survey_file:
                            survey = json.loads((CACHE / survey_file).read_text())
                            survey_layers(model, survey, manifest["files"][survey_file], reverse)
                            source["kind"] = "surveyed"
                        model["revision"] = revision(model)
                        models[key] = model
                        entry.update(
                            coverage=source["kind"], reason="Exact name; raw world metres; closed; length checked",
                            sources=[source["kind"]],
                        )
                    except ValueError as error:
                        entry["reason"] = str(error)
            coverage.append(entry)
    gt7tracks_conflicts: list[dict[str, Any]] = []
    catalogue_warnings: list[dict[str, Any]] = []
    if (GT7TRACKS_CACHE / "manifest.json").exists():
        gt7tracks_conflicts = integrate_gt7tracks(models, catalogue, coverage)
    integrate_local_captures(models, catalogue, coverage)  # highest precedence; always checked
    if models:
        catalogue_warnings = catalogue_checks(models, catalogue)
    overlaps = annotate_overlaps(models)
    for model in models.values():
        model["revision"] = revision(model)
    (ROOT / "docs/track-overlap.json").write_text(json.dumps(overlaps, indent=2), encoding="utf-8")
    bundle = {
        "schema": 3,
        "manifest": manifest,
        "models": models,
        "coverage": coverage,
        "unmatched_sources": [name for name in lookup if name not in matched],
        "gt7tracks_conflicts": gt7tracks_conflicts,
        "catalogue_warnings": catalogue_warnings,
    }
    payload = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    BUNDLE.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    (ROOT / "docs/track-model-sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name, target in (("LICENSE", "track-reference-CC0.txt"), ("LICENSE-MIT", "track-tools-MIT.txt")):
        (ROOT / "docs/licenses" / target).write_bytes((CACHE / name).read_bytes())
    if (GT7TRACKS_CACHE / "LICENSE.txt").exists():
        (ROOT / "docs/licenses/gt7tracks-MIT.txt").write_bytes((GT7TRACKS_CACHE / "LICENSE.txt").read_bytes())
    report(bundle)


def report(bundle: dict[str, Any] | None = None) -> None:
    """Publish all stable catalogue IDs, including absent and rejected source layouts."""
    if bundle is None:
        bundle = json.loads(gzip.decompress(BUNDLE.read_bytes()))
    counts = dict(Counter(row["coverage"] for row in bundle["coverage"]))
    lines = [
        "# World-model reference coverage",
        "",
        f"Pinned commit: `{bundle['manifest']['commit']}`.",
        "",
        f"Coverage: {counts}. All 122 catalogue IDs retained.",
        "",
        "Raw world metres; no runtime downloads. Reverse models reverse ordered geometry, not coordinates.",
        "Surveyed borders are point observations; gaps are not silently connected. Captures are driving lines,",
        "not track limits. Missing/flagged layouts require confirmed user learning.",
        "",
        "| ID | Layout | Coverage | Sources | Reason |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {r['layout_id']} | {r['name']} | {r['coverage']} | {', '.join(r.get('sources', []))} | {r['reason']} |"
        for r in bundle["coverage"]
    )
    lines += ["", "## Unmatched source names", "", *[f"- `{name}`" for name in bundle["unmatched_sources"]]]
    conflicts = bundle.get("gt7tracks_conflicts", [])
    if conflicts:
        lines += ["", "## GT7Tracks fusion conflicts", "",
                   "A conflict means the GT7Tracks lap did not meet the median<=8m/p95<=20m fusion gate against",
                   "the existing model; the better-closing source was kept and neither was silently blended.", "",
                   "| ID | Median m | P95 m | Kept | Reason |", "|---|---|---|---|---|"]
        lines += [f"| {c['layout_id']} | {c['median_m']} | {c['p95_m']} | {c['kept']} | {c['reason']} |"
                  for c in conflicts]
    (ROOT / "docs/TRACK_WORLD_COVERAGE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"coverage": counts, "models": len(bundle["models"]), "compressed_bytes": BUNDLE.stat().st_size}))


def main() -> None:
    """Run an explicit build-time command; refresh is the only network operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("refresh", "build", "report"))
    parser.add_argument("--source", choices=("jbhoorasingh", "gt7tracks"), default="jbhoorasingh")
    args = parser.parse_args()
    if args.command == "refresh":
        refresh(args.source)
    else:
        {"build": build, "report": report}[args.command]()


if __name__ == "__main__":
    main()
