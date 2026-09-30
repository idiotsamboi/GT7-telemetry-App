"""Runtime owner of the v3 recognizer and the currently locked TrackProgress.

Phase 0 of the broadcast/spatial build (docs/AI_CONTEXT.md): this wires the
previously dormant world-frame recognizer (track_recognition.py) into the live
runtime so later features can project a driven position onto real metres
along a locked layout. It does not change System A (tracks.py's TrackMap,
which still owns the legacy 2D learned-line map and stays authoritative for
that UI until it migrates).
"""
from __future__ import annotations

import math
from typing import Any

from .track_catalogue import load_user_models, new_recognizer
from .track_model import Progress, TrackProgress


class TrackService:
    """Owns one TrackRecognizer and exposes cheap per-sample projection once locked."""

    def __init__(self, root: Any, settings: Any = None) -> None:
        self.recognizer = new_recognizer(overrides=load_user_models(root))
        self.locked: TrackProgress | None = None
        self.locked_layout_id: str = ""
        self.state: str = "searching"
        self.reason: str = ""
        self.manual: bool = False
        self.confidence: float | None = None

    def observe(
        self,
        position: list[float | None],
        timestamp: float,
        *,
        speed: float = 0.0,
        velocity: list[float] | None = None,
        lap: int | None = None,
        car_id: int | None = None,
        provenance: str = "live",
        active: bool = True,
    ) -> dict[str, Any]:
        """Feed one sample to the recognizer; safe to call every sample (self-throttled)."""
        result = self.recognizer.update(
            position,
            timestamp,
            speed=speed,
            velocity=velocity,
            lap=lap,
            car_id=car_id,
            provenance=provenance,
            active=active,
        )
        self.state = result["state"]
        self.reason = result["reason"]
        self.manual = bool(result.get("manual"))
        layout_id = result["layout_id"]
        top = result["candidates"][0] if result["candidates"] else None
        self.confidence = top["probability"] if top and top["layout_id"] == layout_id else None
        if result["state"] == "locked" and layout_id != self.locked_layout_id:
            self.locked = self.recognizer.models.get(layout_id)
            self.locked_layout_id = layout_id if self.locked else ""
        elif result["state"] != "locked":
            self.locked = None
            self.locked_layout_id = ""
        return result

    def project(
        self,
        position: list[float | None],
        *,
        heading: float | None = None,
        previous_s: float | None = None,
        expected_m: float | None = None,
    ) -> Progress | None:
        """Cheap single-model projection against the already-locked layout only."""
        if not self.locked:
            return None
        branches = self.locked.candidates(position, heading=heading, previous_s=previous_s, expected_m=expected_m)
        return branches[0][1] if branches else None

    def reset(self) -> None:
        """Clear route evidence on a source switch, keeping any manual selection."""
        self.recognizer.reset()
        self.locked = None
        self.locked_layout_id = ""
        self.state = "searching"
        self.confidence = None

    def select(self, layout_id: str) -> None:
        """Manual selection is immediately authoritative, mirroring TrackMap.select."""
        self.recognizer.select(layout_id)
        self.locked = self.recognizer.models.get(layout_id) if layout_id else None
        self.locked_layout_id = layout_id if self.locked else ""
        self.state = "locked" if self.locked else "searching"
        self.manual = bool(layout_id)

    def corner_at(self, s: float) -> dict[str, Any] | None:
        """The locked model's surveyed/auto corner containing s, or None (never invented)."""
        if not self.locked:
            return None
        from .track_catalogue import bundled_document

        document = bundled_document(self.locked_layout_id)
        if not document:
            return None
        for corner in document.get("corners") or []:
            start, end = corner["s_start"], corner["s_end"]
            inside = start <= s <= end if start <= end else s >= start or s <= end
            if inside:
                return {"id": corner["id"], "name": corner.get("name") or corner["id"]}
        return None

    def snapshot(self, progress_s: float | None) -> dict[str, Any]:
        corner = self.corner_at(progress_s) if progress_s is not None else None
        return {
            "layout_id": self.locked_layout_id,
            "state": self.state,
            "confidence": self.confidence,
            "s": progress_s,
            "lap_fraction": (progress_s / self.locked.length) if self.locked and progress_s is not None else None,
            "corner": corner,
            "source": "v3" if self.locked else "none",
        }
