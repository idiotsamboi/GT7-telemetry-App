"""Bounded world-frame Viterbi recognition, intended for the track worker only."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .track_model import CELL_M, Progress, TrackProgress


@dataclass(slots=True)
class Hypothesis:
    """A layout's bounded set of Viterbi branch states and fading evidence."""

    cost: float = 0.0
    particles: list[tuple[float, Progress]] = field(default_factory=list)
    discriminated: set[str] = field(default_factory=set)


class TrackRecognizer:
    """Recognize metres and travel direction without normalization or shape fitting.

    Confidence is a model posterior, not a calibrated claim about official game
    identity. Unknown and same-geometry alternatives remain explicit hypotheses.
    """

    def __init__(self, models: Iterable[dict[str, Any]]) -> None:
        self.models: dict[str, TrackProgress] = {}
        self.meta: dict[str, dict[str, Any]] = {}
        self.grid: dict[tuple[int, int], set[str]] = defaultdict(set)
        self.venues: dict[str, set[str]] = defaultdict(set)
        for model in models:
            if model["frame"] != "gt7-world":
                continue
            key = model["layout_id"]
            geometry = TrackProgress(model)
            self.models[key] = geometry
            self.meta[key] = {
                name: model.get(name)
                for name in ("name", "venue_id", "direction", "start_finish", "distinguishing", "equivalence_class")
            }
            self.venues[model.get("venue_id", key)].add(key)
            for cell in geometry.grid:
                self.grid[cell].add(key)
        self.manual = ""
        self.rejected: set[str] = set()
        self.reset()

    def reset(self) -> None:
        """Clear route evidence without erasing a manual choice or stored models."""
        self.hypotheses: dict[str, Hypothesis] = {}
        self.previous: tuple[float, list[float | None]] | None = None
        self.identity = None
        self.distance = 0.0
        self.started = None
        self.locked = ""
        self.lock_time = None
        self.lock_distance = None
        self.unknown_cost = 0.0
        self.inactive_since = None
        self.unknown_since = None
        self.last_lap = None
        self.result = {
            "state": "searching",
            "candidates": [],
            "reason": "Waiting for moving world positions",
            "layout_id": "",
            "progress": None,
            "distance_m": 0.0,
            "elapsed_s": 0.0,
        }

    def select(self, layout_id: str) -> None:
        """Keep the user's choice authoritative even when geometry disagrees."""
        self.manual = layout_id
        self.rejected.clear()
        self.reset()

    def reject(self, layout_id: str) -> None:
        """Exclude a candidate for this recognition attempt."""
        self.rejected.add(layout_id)
        self.hypotheses.pop(layout_id, None)
        if self.locked == layout_id:
            self.locked = ""

    def update(
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
        """Consume a worker sample at no more than 5Hz; never persist demo/replay input."""
        identity = (car_id, provenance)
        if self.identity is not None and identity != self.identity:
            self.reset()
        self.identity = identity
        if not active:
            if self.inactive_since is None:
                self.inactive_since = timestamp
            if timestamp - self.inactive_since >= 3:
                self.reset()
            return self.result
        self.inactive_since = None
        if len(position) != 3 or any(position[i] is None or not math.isfinite(position[i]) for i in (0, 2)):
            return self.result
        if self.previous is not None and timestamp - self.previous[0] < 0.199:
            return self.result
        distance = 0.0
        dt = 0.2
        heading = None
        if velocity and math.hypot(velocity[0], velocity[2]) > 3:
            heading = math.atan2(velocity[2], velocity[0])
        if self.previous is not None:
            dt = timestamp - self.previous[0]
            before = self.previous[1]
            dx, dz = position[0] - before[0], position[2] - before[2]
            distance = math.hypot(dx, dz)
            if distance > 200 or dt > 3 or dt <= 0:
                self.reset()
                self.identity = identity
                distance = 0.0
                dt = 0.2
            elif distance > 2 and heading is None:
                heading = math.atan2(dz, dx)
            # Position noise while stopped must not satisfy the 400m evidence gate.
            distance = min(distance, max(0.0, speed) * dt)
        self.previous = (timestamp, list(position))
        if self.started is None:
            self.started = timestamp
        self.distance += distance
        gx, gz = math.floor(position[0] / CELL_M), math.floor(position[2] / CELL_M)
        nearby = set()
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                nearby.update(self.grid.get((gx + dx, gz + dz), ()))
        spatial_candidates = nearby.copy()
        # Include all known variants in a venue, not only the one under this point.
        # This prevents losing an alternative just before a shared section.
        for key in list(nearby):
            nearby.update(self.venues.get(self.meta[key]["venue_id"], ()))
        nearby.difference_update(self.rejected)
        for key in nearby:
            self.hypotheses.setdefault(key, Hypothesis(cost=self.unknown_cost))
        if self.manual in self.models:
            self.hypotheses.setdefault(self.manual, Hypothesis())
        decay = math.exp(-distance / 2000)
        weight = min(2.0, distance / 10.0)
        self.unknown_cost = self.unknown_cost * decay + 8.0 * weight
        fits = {}
        beam_floor = min((hyp.cost for hyp in self.hypotheses.values()), default=0.0)
        for key, hypothesis in self.hypotheses.items():
            geometry = self.models[key]
            competitive = hypothesis.cost <= beam_floor + 30 or key == self.manual or self.distance < 30
            branches = (
                geometry.candidates(position, heading=heading) if key in spatial_candidates and competitive else []
            )
            scored = []
            for emission, hit in branches:
                transition = 0.0
                if hypothesis.particles and distance > 0:
                    transitions = []
                    for old_cost, old in hypothesis.particles:
                        advance = (hit.s - old.s + geometry.length / 2) % geometry.length - geometry.length / 2
                        if advance >= -8:
                            transitions.append(
                                old_cost + ((advance - speed * dt) / max(10.0, speed * dt * 0.4)) ** 2 / 2
                            )
                    transition = min(transitions, default=30.0)
                if lap is not None and self.last_lap is not None and lap == self.last_lap + 1:
                    finish = self.meta[key]["start_finish"]
                    if finish and finish.get("source") == "surveyed":
                        gap = abs((hit.s - finish["s"] + geometry.length / 2) % geometry.length - geometry.length / 2)
                        emission += min((gap / 40) ** 2 / 2, 12)
                scored.append((min(emission + transition, 35.0), hit))
            scored.sort(key=lambda pair: pair[0])
            best_cost = scored[0][0] if scored else 35.0
            hypothesis.cost = hypothesis.cost * decay + best_cost * weight
            hypothesis.particles = [(cost - best_cost, hit) for cost, hit in scored[:8]]
            if scored:
                fits[key] = scored[0][1]
        self.last_lap = lap
        if not self.hypotheses:
            self.result = {**self.result, "state": "unknown", "reason": "No world model near this position"}
            return self.result
        ordered = sorted(self.hypotheses, key=lambda key: (self.hypotheses[key].cost, key))
        minimum = min(self.unknown_cost, self.hypotheses[ordered[0]].cost)
        masses = {key: math.exp(max(-700, minimum - self.hypotheses[key].cost)) for key in ordered}
        unknown_mass = math.exp(max(-700, minimum - self.unknown_cost))
        total = sum(masses.values()) + unknown_mass
        top = ordered[0]
        probability = masses[top] / total
        runner = max(unknown_mass, masses[ordered[1]] if len(ordered) > 1 else 0.0)
        ratio = masses[top] / max(runner, 1e-300)
        # A route must physically distinguish itself from every competing layout.
        # Opposite travel direction is discriminatory; coincident same-direction routes are not.
        hit = fits.get(top)
        if hit and heading is not None and hit.distance_m <= 20:
            for other in ordered[1:]:
                if other in self.hypotheses[top].discriminated:
                    continue
                ranges = (self.meta[top].get("distinguishing") or {}).get(other)
                if ranges is not None:
                    if any(start <= hit.s <= end for start, end in ranges):
                        self.hypotheses[top].discriminated.add(other)
                    continue
                alternative = fits.get(other)
                if alternative is None and other in spatial_candidates:
                    reference = self.models[top]
                    choices = self.models[other].candidates(
                        [reference.x[hit.segment], None, reference.z[hit.segment]],
                        heading=hit.heading,
                        corridor_m=20,
                    )
                    alternative = choices[0][1] if choices else None
                if alternative is None or alternative.distance_m > 20 or math.cos(heading - alternative.heading) < 0:
                    self.hypotheses[top].discriminated.add(other)
        distinguishable = all(key in self.hypotheses[top].discriminated for key in ordered[1:])
        state = "candidates"
        reason = "Collecting distance and distinguishing route evidence"
        if self.distance >= 400 and probability >= 0.98 and ratio >= 50 and distinguishable:
            if not self.locked:
                self.lock_time = timestamp - self.started
                self.lock_distance = self.distance
            self.locked = top
        if self.manual:
            self.locked = self.manual
            reason = "Manual selection"
            if (
                self.manual not in fits
                or fits[self.manual].distance_m > 25
                or heading is not None
                and math.cos(heading - fits[self.manual].heading) < 0
            ):
                reason = "Manual layout does not fit; confirm a different layout to switch"
        instant_unknown = not fits or min(hit.distance_m for hit in fits.values()) > 30
        if unknown_mass / total > 0.8 or instant_unknown:
            state = "unknown"
            reason = "World-model evidence is weaker than the unknown hypothesis"
            if self.unknown_since is None:
                self.unknown_since = timestamp
            if timestamp - self.unknown_since > 3 and not self.manual:
                self.reset()
                self.identity = identity
                return self.result
        else:
            self.unknown_since = None
        if self.locked:
            state = "locked"
            if not self.manual:
                reason = "World position, forward progress and distinguishing route agree"
        elif self.distance >= 400 and not distinguishable:
            state = "ambiguous"
            reason = "Shared geometry has not distinguished the remaining layouts"
        self.result = {
            "state": state,
            "layout_id": self.locked,
            "manual": bool(self.manual),
            "reason": reason,
            "candidates": [
                {"layout_id": key, "name": self.meta[key]["name"], "probability": masses[key] / total}
                for key in ordered[:5]
            ],
            "unknown_probability": unknown_mass / total,
            "likelihood_ratio": min(ratio, 1e100),
            "distance_m": self.distance,
            "elapsed_s": timestamp - self.started,
            "progress": asdict(fits[self.locked]) if self.locked in fits else None,
            "lock_time_s": getattr(self, "lock_time", None) if self.locked else None,
            "lock_distance_m": getattr(self, "lock_distance", None) if self.locked else None,
            "evidence": {
                "discriminated_layouts": sorted(self.hypotheses[top].discriminated),
                "source": provenance,
                "window_m": 2000,
                "particles_per_layout": 8,
                "equivalence_class": self.meta[top].get("equivalence_class") or [top],
            },
        }
        return self.result
