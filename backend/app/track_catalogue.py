"""Shared read-only packed catalogue; each tracker owns its own recognition state."""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from .track_bundle import get_model, iter_models
from .track_model import TrackProgress
from .track_recognition import TrackRecognizer

_lock = threading.RLock()
_template: TrackRecognizer | None = None


def load_user_models(root: Any) -> list[dict[str, Any]]:
    """Read locally saved schema-3 world models that should override the bundle.

    This is a read-only extension point: nothing writes here yet. It exists so a
    future local capture/build step (see track_bundle for the offline pipeline)
    has a place to install a per-installation replacement without touching the
    shared, build-time bundle. Unreadable or malformed files are skipped rather
    than failing catalogue construction.
    """
    directory = Path(root) / "track-models-user"
    if not directory.is_dir():
        return []
    models = []
    for path in sorted(directory.glob("*.json")):
        try:
            model = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(model, dict) and model.get("frame") == "gt7-world" and model.get("layout_id"):
            models.append(model)
    return models


def new_recognizer(overrides: list[dict[str, Any]] | None = None) -> TrackRecognizer:
    """Share immutable built-ins while isolating mutable hypotheses and user replacements."""
    global _template
    with _lock:
        if _template is None:
            _template = TrackRecognizer(iter_models())
        result = TrackRecognizer([])
        result.models = dict(_template.models)
        result.meta = dict(_template.meta)
        result.grid = dict(_template.grid)
        result.venues = dict(_template.venues)
    for model in overrides or []:
        key = model["layout_id"]
        old = result.models.get(key)
        geometry = TrackProgress(model)
        result.models[key] = geometry
        result.meta[key] = {name: model.get(name) for name in ("name", "venue_id", "direction", "start_finish",
                                                              "distinguishing", "equivalence_class")}
        for cell in set(old.grid if old else {}) | set(geometry.grid):
            members = set(result.grid.get(cell, ()))
            members.discard(key)
            if cell in geometry.grid:
                members.add(key)
            result.grid[cell] = members
    return result


@lru_cache(maxsize=2)
def bundled_document(layout_id: str) -> dict[str, Any] | None:
    """Cache at most two display documents; callers must not mutate these shared values."""
    return get_model(layout_id)
