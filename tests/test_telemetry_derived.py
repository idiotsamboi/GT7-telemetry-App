import json
import time
from pathlib import Path

import pytest

from backend.app.core.registry import DuplicateRegistration
from backend.app.live_analysis import LiveAnalysis
from backend.app.telemetry import DERIVED, DerivedChannel, DerivedEngine, TelemetryFrame, demo_sample, parse
from backend.app.telemetry.derived import RATE_CLAMP, all_public_channels

FIXTURES = json.loads(Path('tests/fixtures/packets.json').read_text())


def frame_of(sample):
    return TelemetryFrame.from_sample(sample)


def demo_frame(t=5.0, index=300, **overrides):
    sample = demo_sample(t, index)
    for key, value in overrides.items():
        sample.values[key] = value
    return frame_of(sample)


def pedal_frame(mono, *, brake_raw=0, throttle_raw=0):
    sample = demo_sample(5.0, 1)
    sample.mono = mono
    sample.values.update(brake_raw=brake_raw, brake=brake_raw / 255, throttle_raw=throttle_raw,
                         throttle=throttle_raw / 255)
    return frame_of(sample)


# --- registration -----------------------------------------------------------------------------------
def test_expected_derived_set_registered():
    expected = {'speed_kmh', 'wheel_speed_fl', 'wheel_speed_fr', 'wheel_speed_rl', 'wheel_speed_rr',
                'slip_ratio_fl', 'slip_ratio_fr', 'slip_ratio_rl', 'slip_ratio_rr', 'longitudinal_g',
                'throttle_brake_overlap', 'steering_rate', 'fuel_per_lap', 'delta', 'brake_release_rate',
                'throttle_application_rate'}
    assert set(DERIVED.ids()) == expected
    assert all(c.source == 'calculated' for c in DERIVED)
    assert DERIVED.require('steering_rate').min_variant == 'B'


def test_duplicate_and_public():
    with pytest.raises(DuplicateRegistration):
        DERIVED.register(DERIVED.require('speed_kmh'))
    public = DERIVED.to_public()
    json.dumps(public)
    assert all(not callable(v) for row in public for v in row.values())
    assert all(isinstance(row['depends_on'], list) for row in public)
    assert all('compute' not in row and 'valid_when' not in row and 'accessor' not in row for row in public)
    merged = all_public_channels()
    ids = [row['id'] for row in merged]
    assert len(ids) == len(set(ids))
    json.dumps(merged)


def test_delta_is_external():
    delta = DERIVED.require('delta')
    assert delta.availability == 'computed by LiveDelta service'
    assert DerivedEngine().evaluate(demo_frame())['delta'] is None


# --- known packets --------------------------------------------------------------------------------------
def test_speed_kmh_on_fixture():
    frame = frame_of(parse(bytes.fromhex(FIXTURES['A'])))
    assert DerivedEngine().evaluate(frame)['speed_kmh'] == pytest.approx(180)


def test_wheel_speed_and_slip_on_demo():
    frame = demo_frame()
    speed = frame.values['speed']
    out = DerivedEngine().evaluate(frame)
    for wheel in ('fl', 'fr', 'rl', 'rr'):
        assert out[f'wheel_speed_{wheel}'] == pytest.approx(speed, rel=1e-4)
        assert out[f'slip_ratio_{wheel}'] == pytest.approx(0, abs=1e-4)


def test_slip_matches_parser_ratio():
    frame = demo_frame()
    ratio = frame.values['wheel_speed_ratio']
    out = DerivedEngine().evaluate(frame)
    for i, wheel in enumerate(('fl', 'fr', 'rl', 'rr')):
        assert out[f'slip_ratio_{wheel}'] == pytest.approx(ratio[i] - 1, abs=1e-6)


def test_slip_and_wheel_values_from_locked_wheel():
    frame = demo_frame()
    omega = list(frame.values['wheel_angular'])
    omega[0] = omega[0] * 0.5                      # front-left rotating at half speed = braking slip
    frame.values['wheel_angular'] = omega
    out = DerivedEngine().evaluate(frame)
    assert out['slip_ratio_fl'] == pytest.approx(-0.5, abs=1e-3)
    assert out['slip_ratio_fr'] == pytest.approx(0, abs=1e-3)


@pytest.mark.parametrize('overrides', [
    {'speed': 30 / 3.6 - 0.1},                       # under 30 km/h
    {'road_distance': 1.0},                          # airborne / not grounded
    {'angular_velocity': [0.0, 0.4, 0.0]},           # turning
    {'road_distance': None},
])
def test_slip_suppressed(overrides):
    out = DerivedEngine().evaluate(demo_frame(**overrides))
    assert all(out[f'slip_ratio_{w}'] is None for w in ('fl', 'fr', 'rl', 'rr'))


def test_wheel_speed_implausible_radius_is_none():
    frame = demo_frame(tyre_radius=[0.0, 0.33, 0.33, 2.0])
    out = DerivedEngine().evaluate(frame)
    assert out['wheel_speed_fl'] is None and out['wheel_speed_rr'] is None and out['wheel_speed_fr'] is not None


def test_missing_dependency_gives_none():
    out = DerivedEngine().evaluate(demo_frame(speed=None))
    assert out['speed_kmh'] is None and out['slip_ratio_fl'] is None and out['longitudinal_g'] is None


def test_steering_rate_variants():
    engine = DerivedEngine()
    assert engine.evaluate(frame_of(parse(bytes.fromhex(FIXTURES['A']))))['steering_rate'] is None
    for variant in ('B', '~', 'C'):
        frame = frame_of(parse(bytes.fromhex(FIXTURES[variant])))
        assert engine.evaluate(frame)['steering_rate'] == pytest.approx(0.3)


def test_pedal_overlap():
    engine = DerivedEngine()
    assert engine.evaluate(pedal_frame(1.0, brake_raw=200, throttle_raw=200))['throttle_brake_overlap'] is True
    assert engine.evaluate(pedal_frame(1.1, brake_raw=200, throttle_raw=10))['throttle_brake_overlap'] is False
    assert engine.evaluate(pedal_frame(1.2))['throttle_brake_overlap'] is False


# --- longitudinal G mirrors live_analysis ----------------------------------------------------------------------
def test_longitudinal_g_matches_live_analysis():
    engine, live = DerivedEngine(), LiveAnalysis()
    compared = 0
    for i in range(1, 900):
        sample = demo_sample(i / 60, i)
        out = engine.evaluate(frame_of(sample))
        live.consume(sample)
        expected = live.result.get('longitudinal_g')
        if expected is not None:
            assert out['longitudinal_g'] == pytest.approx(expected, abs=0.006)
            compared += 1
    assert compared > 50


def test_longitudinal_g_suppressed_when_paused_and_after_gap():
    engine = DerivedEngine()
    for i in range(1, 60):
        engine.evaluate(demo_frame(t=i / 60, index=i))
    paused = demo_frame(t=1.2, index=72, flags=3)
    assert engine.evaluate(paused)['longitudinal_g'] is None
    # after a >0.5 s gap the window restarts, so the first value is None again
    assert engine.evaluate(demo_frame(t=3.0, index=180))['longitudinal_g'] is None


# --- pedal rates -----------------------------------------------------------------------------------------
def test_brake_release_and_throttle_rates():
    engine = DerivedEngine()
    first = engine.evaluate(pedal_frame(10.0, brake_raw=204, throttle_raw=0))
    assert first['brake_release_rate'] is None and first['throttle_application_rate'] is None
    second = engine.evaluate(pedal_frame(10.1, brake_raw=102, throttle_raw=51))
    assert second['brake_release_rate'] == pytest.approx(4.0)            # 0.8 -> 0.4 in 0.1 s: releasing
    assert second['throttle_application_rate'] == pytest.approx(2.0)     # 0 -> 0.2 in 0.1 s
    third = engine.evaluate(pedal_frame(10.2, brake_raw=153, throttle_raw=51))
    assert third['brake_release_rate'] == pytest.approx(-2.0)           # brake applied again
    assert third['throttle_application_rate'] == pytest.approx(0.0)


def test_rates_clamped_and_invalid_dt():
    engine = DerivedEngine()
    engine.evaluate(pedal_frame(1.0, brake_raw=255))
    out = engine.evaluate(pedal_frame(1.001, brake_raw=0))
    assert out['brake_release_rate'] == RATE_CLAMP
    out = engine.evaluate(pedal_frame(3.0, brake_raw=255))               # dt = 1.999 s > 1 s
    assert out['brake_release_rate'] is None
    out = engine.evaluate(pedal_frame(3.0, brake_raw=0))                 # dt == 0
    assert out['brake_release_rate'] is None
    out = engine.evaluate(pedal_frame(2.9, brake_raw=255))               # time went backwards
    assert out['brake_release_rate'] is None
    out = engine.evaluate(pedal_frame(2.95, brake_raw=0))                # recovers on the next frame
    assert out['brake_release_rate'] == pytest.approx(20.0)


# --- fuel per lap --------------------------------------------------------------------------------------------------
def fuel_frame(lap, fuel, mono, flags=9):
    sample = demo_sample(5.0, 1)
    sample.mono = mono
    sample.values.update(lap=lap, fuel=fuel, flags=flags)
    return frame_of(sample)


def test_fuel_per_lap_on_lap_boundaries():
    engine = DerivedEngine()
    results, mono = [], 0.0

    def feed(lap, fuel, flags=9):
        nonlocal mono
        mono += 0.1
        results.append(engine.evaluate(fuel_frame(lap, fuel, mono, flags))['fuel_per_lap'])
        return results[-1]

    feed(1, 50.0); feed(1, 49.0)
    assert feed(2, 48.0) is None                          # joined mid-lap: partial lap is not a valid burn
    feed(2, 47.0)
    feed(2, 45.5)
    assert feed(3, 45.5) == pytest.approx(2.5)            # lap 2: 48.0 -> 45.5
    assert feed(3, 45.0) == pytest.approx(2.5)            # held until the next boundary
    feed(3, 65.0)                                         # refuel
    feed(3, 64.0)
    assert feed(4, 63.5) is None                          # refuelled lap invalid
    feed(4, 61.0)
    assert feed(5, 61.0) == pytest.approx(2.5, abs=1e-9)  # lap 4: 63.5 -> 61.0
    assert feed(1, 40.0) is None                          # lap counter went backwards: session restart


def test_fuel_per_lap_ignores_paused_frames_and_states_are_per_engine():
    a, b = DerivedEngine(), DerivedEngine()
    a.evaluate(fuel_frame(1, 50, 0.0))
    a.evaluate(fuel_frame(2, 48, 0.1))
    a.evaluate(fuel_frame(2, 46, 0.2))
    a.evaluate(fuel_frame(2, 90, 0.3, flags=3))           # paused frame with junk fuel is ignored
    assert a.evaluate(fuel_frame(3, 46, 0.4))['fuel_per_lap'] == pytest.approx(2.0)
    assert b.evaluate(fuel_frame(3, 46, 0.4))['fuel_per_lap'] is None    # independent pipeline
    a.reset()
    assert a.evaluate(fuel_frame(4, 44, 0.5))['fuel_per_lap'] is None


# --- engine behaviour ---------------------------------------------------------------------------------------------
def test_engine_isolates_a_failing_channel():
    boom = DerivedChannel('boom', 'Boom', 'motion', '', 'calculated', 'A', lambda v: None,
                          depends_on=('speed',), compute=lambda frame, state: 1 / 0)
    fine = DERIVED.require('speed_kmh')
    engine = DerivedEngine([boom, fine])
    out = engine.evaluate(demo_frame())
    assert out['boom'] is None and out['speed_kmh'] == pytest.approx(demo_frame().values['speed'] * 3.6)
    assert engine.errors == {'boom': 1}


def test_engine_does_not_mutate_frame_values():
    frame = demo_frame()
    before = dict(frame.values)
    DerivedEngine().evaluate(frame)
    assert frame.values == before


def test_engine_per_frame_cost():
    engine = DerivedEngine()
    frames = [demo_frame(t=i / 60, index=i) for i in range(1, 121)]
    for f in frames:            # warm up
        engine.evaluate(f)
    start = time.perf_counter()
    rounds = 5
    for _ in range(rounds):
        for f in frames:
            engine.evaluate(f)
    per_frame = (time.perf_counter() - start) / (rounds * len(frames))
    assert per_frame < 250e-6, f'{per_frame * 1e6:.1f} us per frame (target 50 us, 5x margin)'
