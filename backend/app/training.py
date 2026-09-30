"""Live capture of raw world-frame laps for layouts with no offline model yet.

Segmentation uses GT7's own lap counter (exact), not a heuristic anchor-return,
because the driver declares the layout explicitly here - there is nothing to
recognize. Captured laps are appended locally, one file per layout, for later
inclusion by scripts/track-tool.py build under the "user" merge precedence.
This module never reads or writes the offline bundle itself.
"""
from __future__ import annotations
import json, math, time
from pathlib import Path
from typing import Any

MIN_LAP_POINTS = 50
# 60Hz telemetry gives roughly 216000/speed_kmh points per km per lap, so a single
# lap already clears almost any density target regardless of laps driven - density
# alone can't tell "one lap" from "several independently-fused laps" apart. Summing
# points across every SAVED lap fixes that: it only rises with repeat coverage.
# At a realistic 120-220 km/h lap average this target needs roughly 2-4 complete
# laps (slower/technical layouts finish sooner, flat-out ones need a couple more) -
# enough for fuse_laps' median-lateral consensus to be meaningful, not a single
# unverified pass, but short of an unreasonably long grind.
POINTS_PER_KM_TARGET = 2500


class TrainingRecorder:
    def __init__(self, root):
        self.root = Path(root) / 'track-training'
        self.root.mkdir(parents=True, exist_ok=True)
        self.active = False
        self.layout_id = ''
        self.layout_name = ''
        self.venue_name = ''
        self.direction = ''
        self.length_m = None
        self.current: list[list[float]] = []
        self.pending: list[list[float]] = []
        self.last_lap: int | None = None
        self.have_full_lap = False
        self.laps_this_session = 0
        self.points_this_session = 0
        self.retake_id = 0
        self.error = ''

    def start(self, layout_id: str, layout_meta: dict[str, Any]) -> None:
        self.active = True
        self.layout_id = layout_id
        self.layout_name = layout_meta.get('name', '')
        self.venue_name = layout_meta.get('track', '')
        self.direction = layout_meta.get('direction', '')
        self.length_m = layout_meta.get('length_m')
        self.current = []
        self.pending = []
        self.last_lap = None
        self.have_full_lap = False
        self.laps_this_session = 0
        self.points_this_session = 0
        self.retake_id = 0
        self.error = ''

    def stop(self) -> None:
        self.active = False
        self.current = []
        self.pending = []
        self.last_lap = None
        self.have_full_lap = False

    def discard_current_lap(self) -> None:
        """Abandon the in-progress (unsaved) lap only - already-saved laps and
        session totals are untouched. Lets a driver abort a bad attempt (off
        track, spin, wrong way) without ending the whole recording session.
        retake_id bumps so the frontend's live point-cloud preview, which has
        no per-lap boundaries of its own, knows to clear and start fresh."""
        if not self.active:
            return
        self.current = []
        self.pending = []
        self.last_lap = None
        self.have_full_lap = False
        self.retake_id += 1

    def restart_layout(self, layout_id: str) -> bool:
        """Permanently delete every saved lap for one layout so it can be
        recaptured from zero. Destructive - only for when previously saved
        data turned out bad. Refused while that layout is actively recording,
        so a live session's own file isn't pulled out from under it."""
        if self.active and self.layout_id == layout_id:
            return False
        try:
            (self.root / f'{layout_id}.jsonl').unlink(missing_ok=True)
        except OSError as error:
            self.error = 'Could not clear captures: ' + str(error)[:160]
        return True

    def _path(self) -> Path:
        return self.root / f'{self.layout_id}.jsonl'

    def saved_lap_count(self, layout_id: str | None = None) -> int:
        return self.capture_stats(layout_id)[0]

    def capture_stats(self, layout_id: str | None = None) -> tuple[int, int]:
        """(lap_count, total_points) actually written to disk for a layout."""
        path = self.root / f'{layout_id or self.layout_id}.jsonl'
        if not path.exists():
            return 0, 0
        laps = points = 0
        try:
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    laps += 1
                    points += len(record.get('points') or [])
        except OSError:
            return 0, 0
        return laps, points

    def goal(self, layout_id: str | None = None, length_m: float | None = None) -> dict[str, Any]:
        """Progress toward the points/km reliability goal for one layout."""
        laps, points = self.capture_stats(layout_id)
        km = (length_m or 0) / 1000
        per_km = points / km if km > 0 else 0.0
        percent = min(100.0, per_km / POINTS_PER_KM_TARGET * 100) if POINTS_PER_KM_TARGET else 0.0
        return {
            'laps_saved': laps,
            'points_saved': points,
            'points_per_km': round(per_km, 1),
            'points_per_km_target': POINTS_PER_KM_TARGET,
            'percent': round(percent, 1),
            'complete': per_km >= POINTS_PER_KM_TARGET,
        }

    def list_progress(self, layouts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Every layout with at least one saved lap, with its goal progress."""
        result = []
        for path in sorted(self.root.glob('*.jsonl')):
            layout_id = path.stem
            meta = layouts.get(layout_id)
            if not meta:
                continue
            goal = self.goal(layout_id, meta.get('length_m'))
            if not goal['laps_saved']:
                continue
            result.append({
                'layout_id': layout_id,
                'name': meta.get('name', ''),
                'venue_name': meta.get('track', ''),
                'direction': meta.get('direction', ''),
                'length_m': meta.get('length_m'),
                **goal,
            })
        return result

    def consume(self, sample) -> None:
        """Called once per accepted telemetry sample; a no-op unless capturing."""
        if not self.active:
            return
        v = sample.values
        flags = v.get('flags') or 0
        position = v.get('position')
        lap = v.get('lap')
        if not flags & 1 or flags & 6 or not position or None in position:
            return
        x, y, z = position
        if not all(isinstance(c, (int, float)) and math.isfinite(c) for c in (x, y, z)):
            return
        if self.last_lap is not None and lap is not None and lap > self.last_lap:
            # The segment active before the first observed lap boundary starts
            # mid-lap wherever the driver happened to be; discard it, once.
            if self.have_full_lap and len(self.current) >= MIN_LAP_POINTS:
                self._save_lap(self.current)
            self.current = []
            self.have_full_lap = True
        point = [round(x, 3), round(y, 3), round(z, 3)]
        self.current.append(point)
        self.pending.append(point)
        self.points_this_session += 1
        self.last_lap = lap

    def _save_lap(self, points: list[list[float]]) -> None:
        record = {'ts': time.time(), 'layout_id': self.layout_id, 'points': points}
        try:
            with self._path().open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, separators=(',', ':'), allow_nan=False) + '\n')
            self.laps_this_session += 1
        except OSError as error:
            self.error = 'Training capture not written: ' + str(error)[:160]

    def status(self) -> dict[str, Any]:
        # preview_points drains on read: this app assumes one connected viewer (the
        # /ws loop already has no publisher queue, same assumption everywhere else),
        # so each point is handed to the frontend's own growing display buffer once
        # rather than resending the whole accumulated lap on every tick.
        goal = self.goal(self.layout_id, self.length_m) if self.layout_id else None
        preview_points, self.pending = self.pending, []
        return {
            'active': self.active,
            'layout_id': self.layout_id,
            'layout_name': self.layout_name,
            'venue_name': self.venue_name,
            'direction': self.direction,
            'length_m': self.length_m,
            'laps_this_session': self.laps_this_session,
            'laps_saved_total': goal['laps_saved'] if goal else 0,
            'points_in_current_lap': len(self.current),
            'points_this_session': self.points_this_session,
            'preview_points': preview_points,
            'retake_id': self.retake_id,
            'goal': goal,
            'error': self.error,
        }
