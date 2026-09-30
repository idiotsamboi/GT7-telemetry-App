"""Telemetry source contract and deterministic synthetic scenarios.

This module holds only pure data types and generators; it has no runtime coupling (no sockets, threads or
Runtime imports).  A runtime adapter (UDP, demo, replay) implements `TelemetrySource`.

Scenario contract (`ScenarioDemo.run(name)`)
  Yields `ScenarioItem(mono_offset_s, packet_id, sample)` in *delivery* order.

  * `mono_offset_s`  seconds since the scenario started; non-decreasing.  A caller replaying in real time
                     sleeps until `start + offset`; a test just iterates.  `sample.mono` is
                     `base_mono + offset`, so the sample is self-consistent when fed straight to consumers.
  * `packet_id`      the wire packet counter of this delivery.  Feed it to `parser.Sequence.accept()`:
                     `packet_loss_burst` skips ids (gaps), `out_of_order` delivers ids swapped (reordered),
                     `stream_stale_10s` has a 10 s silence, `session_end` finishes with a `None` sample.
  * `sample`         a `parser.Sample` with `provenance='demo'` (SYNTHETIC; never present it as real driving),
                     or `None` = "the stream closed here" (only `session_end` yields it, as its last item).

Everything is deterministic: the same `seed`, `hz` and `base_mono` give an identical sequence (timestamps
included; `utc` is derived from a fixed epoch, never the wall clock).  `parser.demo_sample` is used as the
generator and its behaviour is untouched; scenarios only adjust the values of the samples it returns.
"""
import math
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, Literal, NamedTuple, Optional, Protocol, runtime_checkable

from ..core.lifecycle import ServiceStatus
from ..core.registry import Registry
from .parser import _LAYOUT, LENGTHS, Sample, demo_sample

SourceKind = Literal['live', 'demo', 'replay']


@runtime_checkable
class TelemetrySource(Protocol):
    """What the runtime needs to know about any source of frames."""
    kind: SourceKind

    def status(self) -> ServiceStatus: ...


@runtime_checkable
class ReplayControls(Protocol):
    """Optional capability of replay sources."""

    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def seek(self, target: 'int | float | str') -> None:
        """`target` is a record id (int/str) or a monotonic time (float)."""
    def set_speed(self, factor: float) -> None: ...


# --- scenarios --------------------------------------------------------------------------------------
class ScenarioItem(NamedTuple):
    mono_offset_s: float
    packet_id: int
    sample: Optional[Sample]


_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_VARIANT_LENGTH = {v: n for n, v in LENGTHS.items()}
_CAPACITY_L = 100.0


class _Builder:
    """Shared machinery: deterministic timestamps and sample construction."""

    def __init__(self, rng: random.Random, hz: float, base_mono: float):
        self.rng, self.hz, self.base_mono = rng, hz, base_mono

    def jitter(self) -> float:
        return self.rng.uniform(-0.0005, 0.0005)          # small receive-time jitter, < half a frame at 60 Hz

    def retime(self, sample: Sample, offset: float) -> Sample:
        return replace(sample, mono=self.base_mono + offset, utc=(_EPOCH + timedelta(seconds=offset)).isoformat())

    def make(self, sim_t: float, packet_id: int, offset: float, mutate: Optional[Callable] = None,
             variant: str = 'C') -> Sample:
        sample = demo_sample(sim_t, packet_id)            # already provenance='demo'
        if mutate is not None:
            mutate(sample.values, sim_t)
        sample = self.retime(sample, offset)
        return _as_variant(sample, variant) if variant != 'C' else sample

    def stream(self, t0: float, t1: float, first_id: int, *, offset0: float = 0.0, mutate=None,
               variant: str = 'C', skip: Callable[[int], bool] = lambda i: False) -> Iterator[ScenarioItem]:
        """Packets for simulated time [t0, t1); `skip(i)` drops packet i (ids still advance)."""
        count = int((t1 - t0) * self.hz)
        last = offset0
        for i in range(count):
            if skip(i):
                continue
            offset = max(last, offset0 + i / self.hz + self.jitter())
            last = offset
            yield ScenarioItem(offset, first_id + i, self.make(t0 + i / self.hz, first_id + i, offset, mutate, variant))


def _as_variant(sample: Sample, variant: str) -> Sample:
    """Make a smaller packet variant: fields beyond its wire length are absent (None), as parse() does."""
    length = _VARIANT_LENGTH[variant]
    for name, offset, decoder in _LAYOUT:
        if offset + decoder.size > length:
            sample.values[name] = None
    sample.values['timing_raw_ms'] = {k: sample.values.get(k) for k in ('best_ms', 'last_ms', 'current_ms')}
    return replace(sample, variant=variant, wire_length=length)


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    description: str
    build: Callable[[_Builder], Iterator[ScenarioItem]]


SCENARIOS: Registry[ScenarioSpec] = Registry('scenarios')


def scenario(id_: str, description: str):
    def wrap(fn):
        SCENARIOS.register(ScenarioSpec(id_, description, fn))
        return fn
    return wrap


@scenario('normal_laps', 'Two clean 30 s laps at full rate.')
def _normal_laps(b: _Builder):
    yield from b.stream(0.0, 65.0, 0)


@scenario('lap_transition', 'Six seconds spanning the lap 1 -> 2 boundary, so lap and last-lap values change.')
def _lap_transition(b: _Builder):
    yield from b.stream(27.0, 33.0, 1000)


@scenario('fuel_burn_and_refuel', 'Steady 2.5 L/lap burn over three laps, then a +20 L refuel mid-lap 3.')
def _fuel(b: _Builder):
    def mutate(values, t):
        values['fuel'] = 45.0 - 2.5 * t / 30 + (20.0 if t >= 75 else 0.0)
        values['fuel_capacity'] = _CAPACITY_L
    yield from b.stream(0.0, 100.0, 0, mutate=mutate)


@scenario('braking_zones', 'Three hard braking zones (1.5 s each) on an otherwise flat-out run.')
def _braking(b: _Builder):
    zones = (3.0, 8.0, 13.0)

    def mutate(values, t):
        brake, speed = 0.0, 70.0
        for start in zones:
            p = (t - start) / 1.5
            if 0 <= p < 1:
                brake = min(1.0, p * 4) if p < 0.7 else max(0.0, (1 - p) / 0.3)
                speed = 70.0 - 40.0 * math.sin(math.pi * p)
        values['brake_raw'], values['brake'] = round(brake * 255), round(brake * 255) / 255
        values['throttle_raw'], values['throttle'] = (0, 0.0) if brake > 0 else (255, 1.0)
        values['speed'], values['speed_kmh'] = speed, speed * 3.6
    yield from b.stream(0.0, 18.0, 0, mutate=mutate)


@scenario('packet_loss_burst', 'Ten seconds of packets with two bursts of consecutive lost packets (30 and 12).')
def _packet_loss(b: _Builder):
    bursts = ((int(2 * b.hz), 30), (int(6 * b.hz), 12))
    yield from b.stream(0.0, 10.0, 0, skip=lambda i: any(s <= i < s + n for s, n in bursts))


@scenario('out_of_order', 'Five seconds where every 20th pair of packets arrives swapped.')
def _out_of_order(b: _Builder):
    items = list(b.stream(0.0, 5.0, 0))
    ordered = []
    i = 0
    while i < len(items):
        if i % 20 == 10 and i + 1 < len(items):
            first, second = items[i], items[i + 1]
            # Packet i+1 is delivered first (at the earlier time), then packet i; delivery times stay ordered.
            ordered.append(ScenarioItem(first.mono_offset_s, second.packet_id, b.retime(second.sample, first.mono_offset_s)))
            ordered.append(ScenarioItem(second.mono_offset_s, first.packet_id, b.retime(first.sample, second.mono_offset_s)))
            i += 2
        else:
            ordered.append(items[i])
            i += 1
    yield from ordered


@scenario('stream_stale_10s', 'Three seconds of packets, ten seconds of silence, then three more seconds.')
def _stale(b: _Builder):
    yield from b.stream(0.0, 3.0, 0)
    n = int(3.0 * b.hz)
    yield from b.stream(3.0, 6.0, n, offset0=13.0)


@scenario('session_end', 'Three seconds of driving, one second paused, then the stream closes (None sample).')
def _session_end(b: _Builder):
    yield from b.stream(0.0, 3.0, 0)
    n = int(3.0 * b.hz)

    def paused(values, t):
        values['flags'] = (values['flags'] & ~1) | 2      # not on track, paused
    yield from b.stream(3.0, 4.0, n, offset0=3.0, mutate=paused)
    end_id = n + int(1.0 * b.hz)
    yield ScenarioItem(4.0 + 1.0 / b.hz, end_id, None)


@scenario('variant_switch_A_to_C', 'Two seconds of 296-byte variant A packets, then two seconds of variant C.')
def _variant_switch(b: _Builder):
    yield from b.stream(0.0, 2.0, 0, variant='A')
    n = int(2.0 * b.hz)
    yield from b.stream(2.0, 4.0, n, offset0=2.0)


class ScenarioDemo:
    """Deterministic synthetic scenarios. `run(name)` restarts the RNG, so repeated runs are identical."""

    def __init__(self, seed: int = 0, *, hz: float = 60.0, base_mono: float = 1000.0):
        self.seed, self.hz, self.base_mono = seed, hz, base_mono

    @staticmethod
    def names() -> list[str]:
        return SCENARIOS.ids()

    def run(self, name: str) -> Iterator[ScenarioItem]:
        spec = SCENARIOS.require(name)
        return spec.build(_Builder(random.Random(self.seed), self.hz, self.base_mono))

    def items(self, name: str) -> list[ScenarioItem]:
        return list(self.run(name))
