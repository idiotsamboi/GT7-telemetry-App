"""TelemetryFrame (one parsed packet + cheap metadata) and the channel catalogue.

Truthfulness: every channel declares where its value comes from.

  reported      decoded directly from a documented GT7 packet field
  calculated    derived by this app from reported fields (never invented)
  experimental  present on the wire but undocumented or unverified upstream; UI must label it
  unavailable   GT7 does not provide it at all; registered so the UI can say *why* it is missing

Channel ids equal the keys of `Sample.values`, so `frame.values[channel.id]` (or `channel.accessor`) works
without translation and the frontend can use the same ids.
"""
from dataclasses import dataclass
from typing import NamedTuple, Any, Callable, Literal, Optional

from ..core.registry import Registry
from .parser import CAPABILITIES, FIELDS, UNSUPPORTED, Sample

Source = Literal['reported', 'calculated', 'experimental', 'unavailable']
Group = Literal['identity', 'timing', 'motion', 'engine', 'controls', 'fuel', 'tyres', 'wheels',
                'chassis', 'session', 'packet']
Sampling = Literal['full', 'ui', 'lap']
VARIANT_ORDER = {'A': 0, 'B': 1, '~': 2, 'C': 3}


class FrameMeta(NamedTuple):
    """Per-packet metadata. Kept separate from the values so consumers can ignore it.
    A NamedTuple: immutable like a frozen dataclass, but built once per packet on the 60 Hz path
    (measured ~5x cheaper than a frozen slots dataclass)."""
    mono: float
    utc: str
    packet_id: Optional[int]
    variant: str
    provenance: str
    parser_version: str
    wire_length: Optional[int]
    quality: tuple = ()
    sequence_gap: Optional[int] = None    # packets missed immediately before this one (None = unknown/first)
    duplicate: bool = False
    source_addr: Optional[str] = None


class TelemetryFrame:
    """A parsed packet plus metadata. `values` is the Sample's own dict (no copy): treat it as read-only."""
    __slots__ = ('sample', 'meta')

    def __init__(self, sample: Sample, meta: FrameMeta):
        self.sample = sample
        self.meta = meta

    @property
    def values(self) -> dict:
        return self.sample.values

    def get(self, channel_id: str, default: Any = None) -> Any:
        value = self.sample.values.get(channel_id)
        return default if value is None else value

    @classmethod
    def from_sample(cls, sample: Sample, *, sequence_gap: Optional[int] = None, duplicate: bool = False,
                    source_addr: Optional[str] = None) -> 'TelemetryFrame':
        values = sample.values
        meta = FrameMeta(sample.mono, sample.utc, values.get('packet_id'), sample.variant, sample.provenance,
                         sample.parser_version, sample.wire_length, tuple(sample.quality), sequence_gap,
                         duplicate, source_addr)
        return cls(sample, meta)


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    group: Group
    unit: str
    source: Source
    min_variant: str
    accessor: Callable[[dict], Any]
    color_role: Optional[str] = None
    formatter: str = 'number:1'
    availability: str = ''
    sampling: Sampling = 'full'

    def available_in(self, variant: str) -> bool:
        return self.source != 'unavailable' and VARIANT_ORDER[variant] >= VARIANT_ORDER[self.min_variant]


def channel_public(channel: Channel) -> dict:
    """JSON-safe description: every dataclass field except the accessor callable, plus extras of subclasses."""
    out = {k: getattr(channel, k) for k in channel.__dataclass_fields__
           if not callable(getattr(channel, k)) and k != 'accessor'}
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in out.items()}


CHANNELS: Registry[Channel] = Registry('channels', public=channel_public)


def _getter(name: str) -> Callable[[dict], Any]:
    return lambda values: values.get(name)


# Fields whose meaning is undocumented or unverified upstream. Everything else in FIELDS is `reported`.
EXPERIMENTAL = frozenset({'surface', 'current_ms', 'wheel_steering', 'wheelbase', 'category',
                          'unknown_a', 'unknown_t_bytes', 'unknown_t', 'torque_vectors',
                          'energy_recovery', 'acceleration_raw', 'steering_rotation'})

# id -> (display name, group, canonical unit, formatter, color_role, sampling)
_META: dict[str, tuple[str, str, str, str, Optional[str], str]] = {
    'position': ('World position', 'motion', 'm', 'array', None, 'full'),
    'velocity': ('World velocity', 'motion', 'm/s', 'array', None, 'full'),
    'rotation': ('Rotation (pitch/yaw/roll)', 'motion', 'raw', 'array', None, 'full'),
    'north': ('North', 'motion', 'raw', 'number:2', None, 'full'),
    'angular_velocity': ('Angular velocity', 'motion', 'rad/s', 'array', None, 'full'),
    'body_height': ('Body height', 'chassis', 'm', 'number:3', None, 'full'),
    'rpm': ('Engine speed', 'engine', 'rpm', 'int', 'rpm', 'full'),
    'fuel': ('Fuel level', 'fuel', 'L', 'number:1', 'fuel', 'full'),
    'fuel_capacity': ('Fuel capacity', 'fuel', 'L', 'number:1', None, 'ui'),
    'speed': ('Speed', 'motion', 'm/s', 'number:1', 'speed', 'full'),
    'boost': ('Boost', 'engine', 'raw +1', 'number:2', None, 'full'),
    'oil_pressure': ('Oil pressure', 'engine', 'bar', 'number:2', None, 'ui'),
    'water_temp': ('Water temperature', 'engine', 'C', 'number:0', None, 'ui'),
    'oil_temp': ('Oil temperature', 'engine', 'C', 'number:0', None, 'ui'),
    'tyres': ('Tyre surface temperature', 'tyres', 'C', 'array', 'tyre', 'full'),
    'packet_id': ('Packet id', 'packet', 'count', 'int', None, 'ui'),
    'lap': ('Lap', 'timing', 'lap', 'int', None, 'lap'),
    'total_laps': ('Total laps', 'session', 'laps', 'int', None, 'ui'),
    'best_ms': ('Best lap time', 'timing', 'ms', 'laptime', None, 'lap'),
    'last_ms': ('Last lap time', 'timing', 'ms', 'laptime', None, 'lap'),
    'day_ms': ('Time of day', 'session', 'ms', 'clock', None, 'ui'),
    'start_position': ('Start position', 'session', 'position', 'int', None, 'ui'),
    'start_cars': ('Cars at start', 'session', 'cars', 'int', None, 'ui'),
    'rpm_min': ('Rev alert start', 'engine', 'rpm', 'int', None, 'ui'),
    'rpm_max': ('Rev limiter', 'engine', 'rpm', 'int', None, 'ui'),
    'transmission_max': ('Top speed at final gear', 'engine', 'km/h', 'int', None, 'ui'),
    'flags': ('Status flags', 'session', 'bits', 'flags', None, 'ui'),
    'gears': ('Gear nibbles', 'engine', 'nibbles', 'int', None, 'full'),
    'throttle_raw': ('Throttle (raw)', 'controls', '0-255', 'int', 'throttle', 'full'),
    'brake_raw': ('Brake (raw)', 'controls', '0-255', 'int', 'brake', 'full'),
    'road_plane': ('Road plane normal', 'chassis', 'raw', 'array', None, 'full'),
    'road_distance': ('Road distance', 'chassis', 'm', 'number:3', None, 'full'),
    'wheel_angular': ('Wheel angular speed', 'wheels', 'rad/s', 'array', None, 'full'),
    'tyre_radius': ('Tyre radius', 'wheels', 'm', 'array', None, 'ui'),
    'suspension': ('Suspension height', 'chassis', 'm', 'array', None, 'full'),
    'unknown_a': ('Unknown block A', 'packet', 'unknown', 'array', None, 'ui'),
    'clutch': ('Clutch', 'controls', 'ratio', 'number:2', None, 'full'),
    'clutch_engagement': ('Clutch engagement', 'controls', 'ratio', 'number:2', None, 'full'),
    'gearbox_rpm': ('Gearbox shaft speed', 'engine', 'rpm', 'int', None, 'full'),
    'transmission_ratio': ('Transmission ratio', 'engine', 'ratio', 'number:3', None, 'full'),
    'gear_ratios': ('Gear ratios', 'engine', 'ratio', 'array', None, 'ui'),
    'car_id': ('Car id', 'identity', 'ID', 'int', None, 'ui'),
    'steering_rotation': ('Steering rotation', 'controls', 'rad', 'number:3', 'steering', 'full'),
    'steering_velocity': ('Steering velocity', 'controls', 'rad/s', 'number:3', 'steering', 'full'),
    'acceleration_raw': ('Acceleration (raw)', 'motion', 'raw', 'array', None, 'full'),
    'throttle_filtered': ('Throttle (filtered)', 'controls', '0-255', 'int', 'throttle', 'full'),
    'brake_filtered': ('Brake (filtered)', 'controls', '0-255', 'int', 'brake', 'full'),
    'unknown_t_bytes': ('Unknown bytes T', 'packet', 'unknown', 'array', None, 'ui'),
    'torque_vectors': ('Torque vectors', 'wheels', 'raw', 'array', None, 'full'),
    'energy_recovery': ('Energy recovery', 'engine', 'raw', 'number:2', None, 'full'),
    'unknown_t': ('Unknown float T', 'packet', 'unknown', 'number:3', None, 'ui'),
    'surface': ('Surface codes', 'wheels', 'code', 'text', None, 'full'),
    'current_ms': ('Current lap time', 'timing', 'ms', 'laptime', None, 'full'),
    'wheel_steering': ('Wheel steering angle', 'controls', 'rad', 'array', 'steering', 'full'),
    'wheelbase': ('Wheelbase', 'chassis', 'm', 'number:2', None, 'ui'),
    'category': ('Car category', 'identity', 'text', 'text', None, 'ui'),
}

# Keys parse() adds on top of FIELDS: id -> (name, group, unit, source, formatter, color_role, sampling, note)
_NORMALIZED: dict[str, tuple[str, str, str, str, str, Optional[str], str, str]] = {
    'gear': ('Gear', 'engine', 'gear', 'calculated', 'int', 'gear', 'full', 'Low nibble of `gears`'),
    'suggested_gear': ('Suggested gear', 'engine', 'gear', 'calculated', 'int', None, 'full',
                       'High nibble of `gears`; null when the game reports 15 (none)'),
    'throttle': ('Throttle', 'controls', '0..1', 'calculated', 'percent', 'throttle', 'full', 'throttle_raw / 255'),
    'brake': ('Brake', 'controls', '0..1', 'calculated', 'percent', 'brake', 'full', 'brake_raw / 255'),
    'speed_kmh': ('Speed (km/h)', 'motion', 'km/h', 'calculated', 'number:0', 'speed', 'full', 'speed x 3.6'),
    'wheel_speed_kmh': ('Wheel speeds', 'wheels', 'km/h', 'calculated', 'array', None, 'full',
                        '|wheel_angular x tyre_radius| x 3.6 when the radius is plausible'),
    'wheel_speed_ratio': ('Wheel speed ratio', 'wheels', 'ratio', 'calculated', 'array', None, 'full',
                          'Only above 10 m/s, grounded and near-straight'),
    'timing_raw_ms': ('Raw timing values', 'timing', 'ms', 'calculated', 'none', None, 'lap',
                      'best/last/current before sentinel removal'),
    'packet_id_signed': ('Packet id (signed)', 'packet', 'count', 'calculated', 'int', None, 'ui',
                         'Same wire bytes as packet_id, read as int32'),
    'raw_nonfinite_fields': ('Non-finite fields', 'packet', 'list', 'calculated', 'none', None, 'ui',
                             'Names of fields that decoded to NaN/inf'),
    'invalid_wire_hex': ('Invalid packet hex', 'packet', 'hex', 'calculated', 'none', None, 'ui',
                         'Original datagram, kept only when quality flags were raised'),
}

# Things GT7 does not provide. id -> (name, group). Availability text comes from UNSUPPORTED where present.
_EXTRA_UNAVAILABLE: dict[str, tuple[str, str, str]] = {
    'race_position': ('Race position', 'session', 'GT7 does not send race position in the player-car stream'),
    'gap_ahead': ('Gap to car ahead', 'timing', 'GT7 does not send opponent data, so gaps cannot be known'),
    'gap_behind': ('Gap to car behind', 'timing', 'GT7 does not send opponent data, so gaps cannot be known'),
    'sector_times': ('Sector times', 'timing', 'GT7 does not send official sector times'),
    'race_flags': ('Race flags', 'session', 'GT7 does not send flag or safety-car state'),
    'tyre_compound': ('Tyre compound', 'tyres', 'GT7 does not send the fitted compound'),
    'lateral_g': ('Lateral G', 'motion', 'No verified lateral acceleration in the packet'),
}
_UNSUPPORTED_GROUP = {'leaderboard': 'session', 'opponents': 'session', 'penalties': 'session',
                      'tyre_wear': 'tyres', 'tyre_pressure': 'tyres', 'weather': 'session',
                      'official_lap_validity': 'timing', 'race_finish': 'session', 'track_name': 'session',
                      'damage': 'chassis', 'understeer_diagnosis': 'chassis'}


def _title(identifier: str) -> str:
    return identifier.replace('_', ' ').capitalize()


def _register_all() -> None:
    for name, _offset, _fmt, _units, variant in FIELDS:
        label, group, unit, formatter, color, sampling = _META[name]
        source = 'experimental' if name in EXPERIMENTAL else 'reported'
        if source == 'experimental':
            note = 'Undocumented or unverified upstream; shown for research only'
        elif variant != 'A':
            note = f'Only in packet variant {variant} and newer'
        else:
            note = ''
        CHANNELS.register(Channel(name, label, group, unit, source, variant, _getter(name),
                                  color, formatter, note, sampling))
    for name, (label, group, unit, source, formatter, color, sampling, note) in _NORMALIZED.items():
        CHANNELS.register(Channel(name, label, group, unit, source, 'A', _getter(name), color, formatter,
                                  note, sampling))
    for name, reason in UNSUPPORTED.items():
        CHANNELS.register(Channel(name, _title(name), _UNSUPPORTED_GROUP.get(name, 'session'), '', 'unavailable',
                                  'A', _getter(name), None, 'none', reason, 'ui'))
    for name, (label, group, reason) in _EXTRA_UNAVAILABLE.items():
        CHANNELS.register(Channel(name, label, group, '', 'unavailable', 'A', _getter(name), None, 'none',
                                  reason, 'ui'))


_register_all()
assert set(CAPABILITIES) <= set(CHANNELS.ids())


def experimental_channel_ids() -> list[str]:
    return [c.id for c in CHANNELS if c.source == 'experimental']


def public_channels() -> list[dict]:
    """JSON-safe channel catalogue for GET /api/channels (no callables)."""
    return CHANNELS.to_public()
