import json
import time

import pytest

from backend.app.core.registry import DuplicateRegistration, Registry
from backend.app.telemetry import (CHANNELS, FIELDS, UNSUPPORTED, TelemetryFrame, demo_sample,
                                   experimental_channel_ids, public_channels)
from backend.app.telemetry.frame import Channel, FrameMeta


def test_every_field_registered():
    missing = [f[0] for f in FIELDS if f[0] not in CHANNELS]
    assert missing == []
    for name, _o, _f, _u, variant in FIELDS:
        assert CHANNELS.require(name).min_variant == variant


def test_normalised_keys_registered_and_ids_match_values():
    frame = TelemetryFrame.from_sample(demo_sample(5.0, 300))
    for key in ('gear', 'suggested_gear', 'throttle', 'brake', 'speed_kmh', 'wheel_speed_kmh',
                'wheel_speed_ratio', 'timing_raw_ms'):
        channel = CHANNELS.require(key)
        assert channel.source == 'calculated'
        assert channel.accessor(frame.values) == frame.values[key]
    # every non-unavailable channel id is an actual key of Sample.values
    for channel in CHANNELS:
        if channel.source != 'unavailable':
            assert channel.id in frame.values, channel.id


def test_experimental_flags():
    expected = {'surface', 'current_ms', 'wheel_steering', 'wheelbase', 'category', 'unknown_a',
                'unknown_t_bytes', 'unknown_t', 'torque_vectors', 'energy_recovery', 'acceleration_raw',
                'steering_rotation'}
    assert set(experimental_channel_ids()) == expected
    for name in ('speed', 'rpm', 'fuel', 'tyres', 'steering_velocity', 'throttle_raw'):
        assert CHANNELS.require(name).source == 'reported'


def test_unavailable_channels_present_with_reason():
    for name in UNSUPPORTED:
        channel = CHANNELS.require(name)
        assert channel.source == 'unavailable' and channel.availability
    for name in ('race_position', 'gap_ahead', 'gap_behind', 'sector_times', 'race_flags', 'tyre_compound',
                 'lateral_g'):
        channel = CHANNELS.require(name)
        assert channel.source == 'unavailable' and channel.availability
    # world position from the packet is real; race position is not
    assert CHANNELS.require('position').source == 'reported'


def test_channel_vocabulary():
    groups = {'identity', 'timing', 'motion', 'engine', 'controls', 'fuel', 'tyres', 'wheels', 'chassis',
              'session', 'packet'}
    for c in CHANNELS:
        assert c.group in groups, c.id
        assert c.source in ('reported', 'calculated', 'experimental', 'unavailable')
        assert c.min_variant in ('A', 'B', '~', 'C')
        assert c.sampling in ('full', 'ui', 'lap')


def test_public_serialisation_has_no_callables():
    data = public_channels()
    assert len(data) == len(CHANNELS)
    json.dumps(data)
    assert all('accessor' not in row for row in data)
    assert all(not callable(v) for row in data for v in row.values())


def test_duplicate_registration_detected():
    registry = Registry('t')
    channel = Channel('x', 'X', 'motion', 'm', 'reported', 'A', lambda v: v.get('x'))
    registry.register(channel)
    with pytest.raises(DuplicateRegistration):
        registry.register(channel)
    with pytest.raises(DuplicateRegistration):
        CHANNELS.register(CHANNELS.require('speed'))


def test_channel_is_frozen_and_availability_by_variant():
    channel = CHANNELS.require('steering_velocity')
    with pytest.raises(Exception):
        channel.id = 'other'
    assert not channel.available_in('A') and channel.available_in('B') and channel.available_in('C')
    assert not CHANNELS.require('leaderboard').available_in('C')


def test_frame_from_sample():
    sample = demo_sample(12.5, 750)
    frame = TelemetryFrame.from_sample(sample, sequence_gap=2, duplicate=False, source_addr='192.168.1.9')
    assert frame.values is sample.values                   # no copy
    assert frame.get('speed') == sample.values['speed']
    assert frame.get('nope') is None and frame.get('nope', 7) == 7
    meta = frame.meta
    assert isinstance(meta, FrameMeta)
    assert (meta.mono, meta.packet_id, meta.variant, meta.provenance) == (12.5, 750, 'C', 'demo')
    assert meta.sequence_gap == 2 and meta.source_addr == '192.168.1.9' and meta.duplicate is False
    assert isinstance(meta.quality, tuple)
    with pytest.raises(Exception):
        meta.mono = 1.0                                     # frozen
    with pytest.raises(AttributeError):
        frame.extra = 1                                     # slots
    assert not hasattr(meta, '__dict__')


def test_from_sample_is_cheap():
    sample = demo_sample(1.0, 60)
    start = time.perf_counter()
    for _ in range(2000):
        TelemetryFrame.from_sample(sample)
    assert (time.perf_counter() - start) / 2000 < 50e-6
