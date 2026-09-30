import json

import pytest

from backend.app.telemetry import SCENARIOS, ScenarioDemo, Sequence, TelemetryFrame, DerivedEngine
from backend.app.telemetry import sources
from backend.app.core.lifecycle import ServiceState, ServiceStatus

EXPECTED = ['normal_laps', 'lap_transition', 'fuel_burn_and_refuel', 'braking_zones', 'packet_loss_burst',
            'out_of_order', 'stream_stale_10s', 'session_end', 'variant_switch_A_to_C']


def fingerprint(items):
    return [(i.mono_offset_s, i.packet_id, None if i.sample is None else
             (i.sample.mono, i.sample.utc, i.sample.variant, i.sample.provenance, json.dumps(i.sample.values, sort_keys=True)))
            for i in items]


def test_registry_lists_all_scenarios():
    assert SCENARIOS.ids() == EXPECTED
    assert all(s.description for s in SCENARIOS)
    json.dumps(SCENARIOS.to_public())
    assert all('build' not in row for row in SCENARIOS.to_public())


@pytest.mark.parametrize('name', EXPECTED)
def test_deterministic_and_synthetic(name):
    a = ScenarioDemo(seed=7, hz=30).items(name)
    b = ScenarioDemo(seed=7, hz=30).items(name)
    assert a and fingerprint(a) == fingerprint(b)
    demo = ScenarioDemo(seed=7, hz=30)
    assert fingerprint(demo.items(name)) == fingerprint(demo.items(name))       # run() restarts the RNG
    assert fingerprint(ScenarioDemo(seed=8, hz=30).items(name)) != fingerprint(a)   # seed matters (jitter)
    offsets = [i.mono_offset_s for i in a]
    assert offsets == sorted(offsets)
    for item in a:
        if item.sample is not None:
            assert item.sample.provenance == 'demo'
            assert item.sample.mono == pytest.approx(1000.0 + item.mono_offset_s)


def test_normal_laps_cross_lap_boundary():
    items = ScenarioDemo(hz=20).items('normal_laps')
    laps = {i.sample.values['lap'] for i in items}
    assert laps == {1, 2, 3}
    seq = Sequence()
    assert all(seq.accept(i.packet_id) for i in items)
    assert seq.counts['gaps'] == 0


def test_lap_transition():
    items = ScenarioDemo(hz=20).items('lap_transition')
    laps = [i.sample.values['lap'] for i in items]
    assert laps[0] == 1 and laps[-1] == 2
    assert items[0].sample.values['last_ms'] is None and items[-1].sample.values['last_ms'] == 30000


def test_fuel_burn_and_refuel_seen_by_derived_engine():
    engine, burns = DerivedEngine(), []
    for item in ScenarioDemo(hz=10).run('fuel_burn_and_refuel'):
        out = engine.evaluate(TelemetryFrame.from_sample(item.sample))
        if out['fuel_per_lap'] is not None and (not burns or burns[-1] != out['fuel_per_lap']):
            burns.append(out['fuel_per_lap'])
    assert burns and burns[0] == pytest.approx(2.5, abs=0.05)         # lap 2 (first full lap): clean burn
    fuels = [i.sample.values['fuel'] for i in ScenarioDemo(hz=10).run('fuel_burn_and_refuel')]
    assert max(b - a for a, b in zip(fuels, fuels[1:])) == pytest.approx(20, abs=0.5)     # the refuel jump


def test_braking_zones_have_three_brake_applications():
    items = ScenarioDemo(hz=30).items('braking_zones')
    braking = [i.sample.values['brake'] > 0.1 for i in items]
    starts = sum(1 for a, b in zip(braking, braking[1:]) if b and not a)
    assert starts == 3
    assert max(i.sample.values['brake'] for i in items) == 1.0


def test_packet_loss_burst_produces_gaps():
    items = ScenarioDemo(hz=60).items('packet_loss_burst')
    seq = Sequence()
    accepted = [seq.accept(i.packet_id) for i in items]
    assert all(accepted)                                   # gaps are still forward progress
    assert seq.counts['gaps'] == 30 + 12
    assert len(items) == 600 - 42


def test_out_of_order_produces_reorders():
    items = ScenarioDemo(hz=60).items('out_of_order')
    seq = Sequence()
    accepted = [seq.accept(i.packet_id) for i in items]
    assert seq.counts['reordered'] >= 10
    assert not all(accepted)                               # late packets are rejected by Sequence
    assert len(items) == 300


def test_stream_stale_has_ten_second_silence():
    items = ScenarioDemo(hz=20).items('stream_stale_10s')
    gaps = [b.mono_offset_s - a.mono_offset_s for a, b in zip(items, items[1:])]
    assert max(gaps) >= 10.0
    assert sum(1 for g in gaps if g >= 1.0) == 1


def test_session_end_finishes_with_none_after_pause():
    items = ScenarioDemo(hz=20).items('session_end')
    assert items[-1].sample is None
    last = items[-2].sample.values
    assert last['flags'] & 2 and not last['flags'] & 1
    assert items[0].sample.values['flags'] & 1


def test_variant_switch_A_to_C():
    items = ScenarioDemo(hz=20).items('variant_switch_A_to_C')
    variants = [i.sample.variant for i in items]
    assert variants[0] == 'A' and variants[-1] == 'C' and set(variants) == {'A', 'C'}
    a = next(i.sample for i in items if i.sample.variant == 'A')
    assert a.wire_length == 296 and a.values['surface'] is None and a.values['current_ms'] is None
    assert a.values['steering_velocity'] is None and a.values['speed'] is not None
    c = items[-1].sample
    assert c.wire_length == 368 and c.values['surface'] is not None
    # derived channels respect the variant switch
    engine = DerivedEngine()
    assert engine.evaluate(TelemetryFrame.from_sample(a))['steering_rate'] is None


def test_unknown_scenario_and_source_protocols():
    with pytest.raises(KeyError):
        ScenarioDemo().run('nope')

    class Fake:
        kind = 'demo'

        def status(self):
            return ServiceStatus('demo', ServiceState.RUNNING)

    assert isinstance(Fake(), sources.TelemetrySource)

    class Replay:
        def pause(self): ...
        def resume(self): ...
        def seek(self, target): ...
        def set_speed(self, factor): ...

    assert isinstance(Replay(), sources.ReplayControls)
    assert not isinstance(object(), sources.ReplayControls)
