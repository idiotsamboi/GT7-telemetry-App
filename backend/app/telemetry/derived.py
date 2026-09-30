"""Derived (calculated) channels and the engine that evaluates them per frame.

Only calculations that already exist in the app (parser normalisation, live_analysis, analytics) are
mirrored here, plus two new pedal-rate channels.  Nothing is inferred beyond the packet: if a
dependency is missing, or `valid_when` says the maths would be meaningless, the value is `None`.

Contract
  * `DerivedChannel.compute(frame, state) -> value`: pure given `state`; it may mutate `state` only.
  * One `DerivedState` (or subclass produced by `state_factory`) exists per channel per `DerivedEngine`,
    so two pipelines (live + replay) never share state.
  * `DerivedEngine.evaluate(frame)` returns `{channel_id: value}`; it never mutates the frame and a
    channel that raises yields `None` (counted in `engine.errors`) instead of breaking the frame.
"""
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from ..core.registry import Registry
from .frame import CHANNELS, VARIANT_ORDER, Channel, TelemetryFrame, channel_public

G = 9.80665
RATE_CLAMP = 20.0            # pedal rates are clamped to +/-20 per second (full travel in 50 ms)
RATE_MAX_DT = 1.0            # a longer gap between frames means no meaningful rate
MIN_SLIP_SPEED_KMH = 30.0    # slip ratio is noise below this speed
LONG_G_MIN_INTERVAL = 0.19   # live_analysis samples at ~5 Hz
LONG_G_MAX_GAP = 0.5         # live_analysis restarts its window after a gap this long
REFUEL_JUMP_L = 0.2          # analytics.Accumulator treats a rise above this as a refuel
WHEELS = ('fl', 'fr', 'rl', 'rr')


class DerivedState:
    """Base for per-channel mutable state (stateless channels use it as-is)."""
    __slots__ = ()


@dataclass(frozen=True, kw_only=True)
class DerivedChannel(Channel):
    depends_on: tuple[str, ...] = ()
    compute: Callable[[TelemetryFrame, Any], Any] = lambda frame, state: None
    valid_when: Callable[[TelemetryFrame], bool] = lambda frame: True
    state_factory: Callable[[], Any] = DerivedState


DERIVED: Registry[DerivedChannel] = Registry('derived', public=channel_public)


def _finite(*values: Any) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _on_track(values: dict) -> bool:
    flags = values.get('flags') or 0
    return bool(flags & 1) and not flags & 6


# --- speed and wheels ----------------------------------------------------------------------------
def _speed_kmh(frame: TelemetryFrame, state: Any) -> Optional[float]:
    speed = frame.values.get('speed')
    return None if speed is None else speed * 3.6


def _wheel_speed(index: int) -> Callable[[TelemetryFrame, Any], Optional[float]]:
    def compute(frame: TelemetryFrame, state: Any) -> Optional[float]:
        values = frame.values
        omega, radius = values['wheel_angular'][index], values['tyre_radius'][index]
        # Same plausibility window as parser.wheel_speed_kmh.
        if omega is None or radius is None or not 0.05 < radius < 1:
            return None
        return abs(omega * radius)
    return compute


def _slip_ratio(index: int) -> Callable[[TelemetryFrame, Any], Optional[float]]:
    def compute(frame: TelemetryFrame, state: Any) -> Optional[float]:
        values = frame.values
        speed = values['speed']
        if speed * 3.6 < MIN_SLIP_SPEED_KMH:
            return None
        # Same conditions as parser's wheel_speed_ratio: wheels on the ground, car near-straight.
        road_distance = values.get('road_distance')
        yaw_rate = (values.get('angular_velocity') or [None, None])[1]
        if road_distance is None or abs(road_distance) >= 0.25 or yaw_rate is None or abs(yaw_rate) >= 0.15:
            return None
        omega, radius = values['wheel_angular'][index], values['tyre_radius'][index]
        if omega is None or radius is None or not 0.05 < radius < 1:
            return None
        return abs(omega * radius) / speed - 1.0
    return compute


# --- longitudinal G (mirrors live_analysis.LiveAnalysis) ---------------------------------------------
@dataclass(slots=True)
class _LongGState(DerivedState):
    key: Any = None
    last_mono: Optional[float] = None
    last_speed: Optional[float] = None
    held: Optional[float] = None

    def reset(self) -> None:
        self.last_mono = self.last_speed = self.held = None


def _longitudinal_g(frame: TelemetryFrame, state: _LongGState) -> Optional[float]:
    values, mono = frame.values, frame.meta.mono
    key = (frame.meta.provenance, values.get('car_id'), values.get('lap'))
    if key != state.key or (state.last_mono is not None and (mono - state.last_mono > LONG_G_MAX_GAP or mono < state.last_mono)):
        state.reset()
        state.key = key
    if not _on_track(values):
        state.reset()
        return None
    if state.last_mono is not None and mono - state.last_mono < LONG_G_MIN_INTERVAL:
        return state.held                      # between 5 Hz updates: hold the last computed value
    speed, throttle, brake = values.get('speed'), values.get('throttle'), values.get('brake')
    if not _finite(speed, throttle, brake):
        state.reset()
        return None
    dt = mono - state.last_mono if state.last_mono is not None else 0.0
    accel = (speed - state.last_speed) / dt if dt and state.last_speed is not None else None
    state.last_mono, state.last_speed = mono, speed
    state.held = accel / G if accel is not None else None
    return state.held


def _pedal_overlap(frame: TelemetryFrame, state: Any) -> bool:
    values = frame.values
    return values['throttle'] > 0.1 and values['brake'] > 0.1   # thresholds from live_analysis


# --- pedal rates (new) --------------------------------------------------------------------------------
@dataclass(slots=True)
class _RateState(DerivedState):
    mono: Optional[float] = None
    value: Optional[float] = None


def _rate(pedal: str, sign: int) -> Callable[[TelemetryFrame, _RateState], Optional[float]]:
    """sign=+1: rising pedal is positive (application); sign=-1: falling pedal is positive (release)."""
    def compute(frame: TelemetryFrame, state: _RateState) -> Optional[float]:
        current, mono = frame.values.get(pedal), frame.meta.mono
        previous_mono, previous = state.mono, state.value
        state.mono, state.value = mono, current
        if previous_mono is None or previous is None:
            return None
        dt = mono - previous_mono
        if dt <= 0 or dt > RATE_MAX_DT:
            return None
        rate = sign * (current - previous) / dt
        return max(-RATE_CLAMP, min(RATE_CLAMP, rate))
    return compute


# --- fuel per lap (mirrors analytics.Accumulator, evaluated on lap boundaries) -----------------------
@dataclass(slots=True)
class _FuelState(DerivedState):
    lap: Optional[int] = None
    first: Optional[float] = None
    last: Optional[float] = None
    refuel: bool = False
    complete: bool = False      # False for the lap we joined part-way through
    held: Optional[float] = None


def _fuel_per_lap(frame: TelemetryFrame, state: _FuelState) -> Optional[float]:
    values = frame.values
    if not _on_track(values):
        return state.held
    lap, fuel = values['lap'], values['fuel']
    if state.lap is None or lap < state.lap:      # first frame, or the session restarted
        state.lap, state.first, state.last, state.refuel, state.complete, state.held = lap, fuel, fuel, False, False, None
        return None
    if lap != state.lap:
        # A lap just finished. Only a lap seen from its first frame, without refuelling, has a valid burn.
        used = state.first - state.last if state.complete and not state.refuel else None
        state.held = used if used is not None and used > 0 else None
        state.lap, state.first, state.last, state.refuel, state.complete = lap, fuel, fuel, False, True
        return state.held
    if fuel > state.last + REFUEL_JUMP_L:
        state.refuel = True
    state.last = fuel
    return state.held


def _no_value(frame: TelemetryFrame, state: Any) -> None:
    return None


def _register() -> None:
    def add(id_, name, group, unit, formatter, depends, compute, *, color=None, min_variant='A',
            valid=lambda frame: True, note='', sampling='full', source='calculated', state=DerivedState):
        DERIVED.register(DerivedChannel(id_, name, group, unit, source, min_variant, lambda values, _k=id_: values.get(_k),
                                        color, formatter, note, sampling, depends_on=tuple(depends), compute=compute,
                                        valid_when=valid, state_factory=state))

    add('speed_kmh', 'Speed (km/h)', 'motion', 'km/h', 'number:0', ('speed',), _speed_kmh, color='speed')
    for i, w in enumerate(WHEELS):
        add(f'wheel_speed_{w}', f'Wheel speed {w.upper()}', 'wheels', 'm/s', 'number:1',
            ('wheel_angular', 'tyre_radius'), _wheel_speed(i), sampling='full')
    for i, w in enumerate(WHEELS):
        add(f'slip_ratio_{w}', f'Slip ratio {w.upper()}', 'wheels', 'ratio', 'number:2',
            ('speed', 'wheel_angular', 'tyre_radius', 'road_distance', 'angular_velocity'), _slip_ratio(i),
            note='Suppressed below 30 km/h, off the ground or while turning (yaw rate >= 0.15 rad/s)')
    add('longitudinal_g', 'Longitudinal G', 'motion', 'g', 'number:2', ('speed', 'throttle', 'brake', 'flags'),
        _longitudinal_g, state=_LongGState, sampling='ui',
        note='Speed derivative at ~5 Hz (as in live_analysis); only while on track')
    add('throttle_brake_overlap', 'Throttle/brake overlap', 'controls', 'bool', 'none', ('throttle', 'brake'),
        _pedal_overlap, note='Both pedals above 10%')
    add('steering_rate', 'Steering rate', 'controls', 'rad/s', 'number:2', ('steering_velocity',),
        lambda frame, state: frame.values['steering_velocity'], color='steering', min_variant='B',
        note='Reported steering velocity; packet variant B or newer')
    add('fuel_per_lap', 'Fuel used last lap', 'fuel', 'L', 'number:2', ('fuel', 'lap', 'flags'), _fuel_per_lap,
        state=_FuelState, sampling='lap', note='Litres burned over the last complete, refuel-free lap')
    add('delta', 'Delta to reference', 'timing', 's', 'delta', (), _no_value, valid=lambda frame: False,
        sampling='ui', note='computed by LiveDelta service')
    add('brake_release_rate', 'Brake release rate', 'controls', '1/s', 'number:1', ('brake',),
        _rate('brake', -1), color='brake', state=_RateState, note='Positive while releasing; per second, clamped to +/-20')
    add('throttle_application_rate', 'Throttle application rate', 'controls', '1/s', 'number:1', ('throttle',),
        _rate('throttle', +1), color='throttle', state=_RateState, note='Positive while applying; per second, clamped to +/-20')


_register()


class DerivedEngine:
    """Evaluates the derived channel set for each frame with dependency and validity checks."""

    def __init__(self, channels: Optional[Iterable[DerivedChannel]] = None):
        self._channels = tuple(channels if channels is not None else DERIVED)
        self.errors: dict[str, int] = {}
        self._states = self._new_states()

    def _new_states(self) -> list:
        return [c.state_factory() for c in self._channels]

    def reset(self) -> None:
        """Forget all per-channel state (new session, source change)."""
        self._states = self._new_states()

    def ids(self) -> list[str]:
        return [c.id for c in self._channels]

    def evaluate(self, frame: TelemetryFrame) -> dict[str, Any]:
        values = frame.values
        out: dict[str, Any] = {}
        states = self._states
        for index, channel in enumerate(self._channels):
            if VARIANT_ORDER[frame.meta.variant] < VARIANT_ORDER[channel.min_variant]:
                out[channel.id] = None
                continue
            for dep in channel.depends_on:
                if values.get(dep) is None:
                    out[channel.id] = None
                    break
            else:
                try:
                    out[channel.id] = channel.compute(frame, states[index]) if channel.valid_when(frame) else None
                except Exception:
                    self.errors[channel.id] = self.errors.get(channel.id, 0) + 1
                    out[channel.id] = None
        return out


def all_public_channels() -> list[dict]:
    """Reported/experimental/unavailable channels plus derived ones (derived wins on an id clash),
    for GET /api/channels."""
    derived = {c.id: c for c in DERIVED}
    out = [channel_public(c) for c in CHANNELS if c.id not in derived]
    out.extend(channel_public(c) for c in derived.values())
    return out
