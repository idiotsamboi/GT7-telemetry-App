"""Atomic v3 user-model storage, lossless migration, layers and bounded track packs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
from pathlib import Path
from typing import Any

from .track_model import build_model, revision, world_points

MAX_DOCUMENT = 16 * 1024 * 1024
MAX_PACK = 32 * 1024 * 1024


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    """Durably replace one document; a failed write never changes the previous model."""
    encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_DOCUMENT:
        raise ValueError("Model exceeds 16 MiB limit")
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_model(document: dict[str, Any], known_ids: set[str]) -> dict[str, Any]:
    """Reject untrusted geometry and identity without trusting stored derived arrays."""
    if not isinstance(document, dict) or document.get("schema") != 3:
        raise ValueError("Expected a version-three model")
    if document.get("layout_id") not in known_ids:
        raise ValueError("Unknown catalogue layout ID")
    points = world_points(document.get("centerline", []))
    rebuilt = build_model(document["layout_id"], points, document.get("source", {}), frame=document.get("frame"))
    if abs(rebuilt["length_m"] - document.get("length_m", 0)) > 5:
        raise ValueError("Model length differs from geometry")
    if document.get("revision") != revision(document):
        raise ValueError("Model revision checksum mismatch")
    n = len(points)
    for name in ("s", "heading", "curvature"):
        values = document.get(name)
        if not isinstance(values, list) or len(values) != n:
            raise ValueError(f"Invalid {name} array")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
            raise ValueError(f"Invalid {name} value")
    if document["s"][0] != 0 or any(b <= a for a, b in zip(document["s"], document["s"][1:])):
        raise ValueError("Stations must increase from zero")
    if document["s"][-1] >= document["length_m"]:
        raise ValueError("Station outside lap")
    return copy.deepcopy(document)


def validate_layers(layers: dict[str, Any], length: float) -> dict[str, Any]:
    """Validate user-authored metres and labels; never allow arbitrary model replacement."""
    if not isinstance(layers, dict) or set(layers) - {"corners", "sectors", "zones", "start_finish", "pit"}:
        raise ValueError("Unsupported user layer")

    def station(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError("A station must be finite metres")
        if not 0 <= value < length:
            raise ValueError("Station outside the lap")
        return float(value)

    result = {}
    for name in ("corners", "sectors", "zones"):
        if name not in layers:
            continue
        rows = layers[name]
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("At most 100 elements per layer")
        seen = set()
        clean = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid layer element")
            key = row.get("id")
            label = row.get("name")
            if not isinstance(key, str) or not 1 <= len(key) <= 80 or key in seen:
                raise ValueError("Layer IDs must be unique bounded strings")
            if not isinstance(label, str) or len(label) > 100:
                raise ValueError("Layer names must be bounded strings")
            seen.add(key)
            item = {"id": key, "name": label, "source": "user"}
            fields = ("s_start", "s_apex", "s_end") if name == "corners" else ("s_start", "s_end")
            for field in fields:
                item[field] = station(row.get(field))
            if name == "corners":
                direction = row.get("dir")
                if direction not in {None, "left", "right", "chicane"}:
                    raise ValueError("Invalid corner direction")
                item["dir"] = direction
            clean.append(item)
        result[name] = clean
    if "start_finish" in layers:
        result["start_finish"] = {"s": station(layers["start_finish"].get("s")), "source": "user"}
    if "pit" in layers:
        pit = layers["pit"]
        points = world_points(pit.get("points", []))
        if len(points) > 6000:
            raise ValueError("Pit path exceeds 6000 points")
        result["pit"] = {
            "points": points,
            "entry_s": station(pit.get("entry_s")),
            "exit_s": station(pit.get("exit_s")),
            "source": "user",
        }
    return result


class TrackModelStore:
    """User files overlay bundled models; original legacy files remain byte-for-byte intact."""

    def __init__(self, root: Path, known_ids: set[str]) -> None:
        self.root = Path(root) / "track-models"
        self.root.mkdir(parents=True, exist_ok=True)
        self.legacy_root = Path(root) / "track-maps"
        self.known_ids = known_ids
        self.lock = threading.RLock()
        self.migration_errors: dict[str, str] = {}

    def load(self, layout_id: str) -> dict[str, Any] | None:
        """Read a bounded user model, reporting corruption rather than replacing it."""
        if layout_id not in self.known_ids:
            raise ValueError("Unknown layout ID")
        path = self.root / f"{layout_id}.json"
        if not path.exists():
            return None
        if path.stat().st_size > MAX_DOCUMENT:
            raise ValueError("User model exceeds size limit")
        return validate_model(json.loads(path.read_text(encoding="utf-8")), self.known_ids)

    def save(self, model: dict[str, Any], *, provenance: str = "live") -> dict[str, Any]:
        """Commit a validated live model before exposing its new revision."""
        if provenance != "live":
            raise ValueError("Demo and replay cannot persist live models")
        clean = validate_model(model, self.known_ids)
        key = clean["layout_id"]
        with self.lock:
            previous = self.load(key)
            history = previous.get("history", []) if previous else []
            if previous and previous["revision"] != clean["revision"]:
                history = history + [{k: v for k, v in previous.items() if k != "history"}]
            clean["history"] = history[-8:]
            atomic_json(self.root / f"{key}.json", clean)
        return clean

    def migrate(self) -> list[str]:
        """Migrate exact legacy points, assignments and revision history without deleting originals."""
        migrated = []
        for path in self.legacy_root.glob("*.json"):
            key = path.stem
            if key not in self.known_ids or (self.root / f"{key}.json").exists():
                continue
            if path.stat().st_size > 4 * 1024 * 1024:
                continue
            try:
                legacy = json.loads(path.read_text(encoding="utf-8"))
                if legacy.get("provenance", "live") in {"demo", "replay"}:
                    continue
                model = build_model(
                    key, legacy["points"], {"kind": "user-learned", "migration": "legacy map"}, preserve=legacy
                )
                self.save(model)
                migrated.append(key)
            except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
                self.migration_errors[key] = str(error)[:200]
        return migrated

    def save_layers(self, model: dict[str, Any], layers: dict[str, Any]) -> dict[str, Any]:
        """Store an independent user-layer revision over a read-only model."""
        clean = validate_layers(layers, model["length_m"])
        key = model["layout_id"]
        if key not in self.known_ids:
            raise ValueError("Unknown layout ID")
        path = self.root / f"{key}.layers.json"
        with self.lock:
            previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            document = {"schema": 1, "layout_id": key, "base_revision": model["revision"], "layers": clean}
            document["revision"] = revision(document)
            history = previous.get("history", []) if previous else []
            if previous and previous["revision"] != document["revision"]:
                history = history + [{k: v for k, v in previous.items() if k != "history"}]
            document["history"] = history[-8:]
            atomic_json(path, document)
        return document

    def export_pack(self, layout_ids: list[str]) -> bytes:
        """Export only selected user models; credentials and unrelated recordings are excluded."""
        entries = []
        for key in dict.fromkeys(layout_ids):
            model = self.load(key)
            if model:
                raw = json.dumps(model, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                entries.append({"sha256": hashlib.sha256(raw).hexdigest(), "model": model})
        payload = json.dumps({"format": "gt7-track-pack", "version": 1, "models": entries}, allow_nan=False).encode()
        if len(payload) > MAX_PACK:
            raise ValueError("Track pack exceeds 32 MiB; export fewer layouts")
        return payload

    def import_pack(self, payload: bytes) -> list[str]:
        """Validate an entire bounded pack before merging any revisions into user storage."""
        if len(payload) > MAX_PACK:
            raise ValueError("Track pack exceeds 32 MiB")
        pack = json.loads(payload)
        if not isinstance(pack, dict) or pack.get("format") != "gt7-track-pack" or pack.get("version") != 1:
            raise ValueError("Unsupported track pack")
        rows = pack.get("models")
        if not isinstance(rows, list) or len(rows) > len(self.known_ids):
            raise ValueError("Invalid track pack model count")
        validated = []
        seen = set()
        for row in rows:
            model = validate_model(row["model"], self.known_ids)
            raw = json.dumps(model, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            if hashlib.sha256(raw).hexdigest() != row.get("sha256") or model["layout_id"] in seen:
                raise ValueError("Invalid checksum or duplicate layout")
            seen.add(model["layout_id"])
            validated.append(model)
        for model in validated:
            self.save(model)
        return [model["layout_id"] for model in validated]
