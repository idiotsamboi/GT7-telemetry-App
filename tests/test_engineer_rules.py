"""Declarative engineer rules: registry shape, per-rule positive/negative/noisy/stale cases and parity with the
pre-port implementation (tests/fixtures/legacy_engineer.py, an oracle only)."""
import importlib.util
import random
import sys
from pathlib import Path

import pytest

from backend.app import engineer as new
from backend.app.config import Settings
from backend.app.core.registry import DuplicateRegistration
from backend.app.telemetry import demo_sample

FIXTURE = Path(__file__).parent / 'fixtures' / 'legacy_engineer.py'


def load_legacy():
    spec = importlib.util.spec_from_file_location('legacy_engineer_oracle', FIXTURE)
    module = importlib.util.module_from_spec(spec)
    sys.modules['legacy_engineer_oracle'] = module
    spec.loader.exec_module(module)
    return module


def frame(t, **values):
    s = demo_sample(t, int(t * 20))
    s.mono = t
    s.values.update(values)
    return s


# ---- registry ----------------------------------------------------------------------------------------------
def test_rule_registry_matches_documented_rules():
    assert list(new.RULES) == ['low_fuel', 'fuel_critical', 'tyre_hot', 'tyre_imbalance', 'limiter', 'handbrake',
                               'off_surface', 'pedal_overlap', 'pit_speed', 'tyre_heat_rate']
    assert set(new.RULES) == set(new.RULE_SPECS.ids())
    for rule in new.RULES.values():
        assert set(rule) == {'priority', 'persist', 'prerequisite', 'entry', 'exit'}
    assert new.RULES['fuel_critical']['priority'] == 0
    with pytest.raises(DuplicateRegistration):
        new.RULE_SPECS.register(new.RULE_SPECS.require('low_fuel'))
    public = {r['id']: r for r in new.RULE_SPECS.to_public()}
    assert public['limiter']['entry'] == 'flag set' and 'entry' in public['tyre_heat_rate']


def test_legacy_oracle_has_identical_rules_table():
    assert load_legacy().RULES == new.RULES


# ---- per-rule behaviour (positive / negative / noisy / stale) -----------------------------------------------------
def run(rules, samples):
    out = []
    for s in samples:
        out += rules.evaluate(s, 'S')
    return out


def test_low_fuel_positive_negative_noisy_and_cooldown():
    def only(events):
        return [e for e in events if e.category == 'low_fuel']

    rules = new.Rules(Settings(low_fuel_l=3, alert_cooldown=60))
    low = lambda t, fuel: frame(t, fuel=fuel, fuel_capacity=50)
    assert only(run(rules, [low(0, 2.0), low(1, 2.0)])) == []                              # not persisted for 3 s yet
    fired = only(run(rules, [low(3, 2.0)]))
    assert len(fired) == 1 and fired[0].message == 'Fuel low. 2.0 litres remaining.' and fired[0].priority == 1
    assert only(run(rules, [low(4, 2.0), low(30, 2.0)])) == []                             # cooldown suppresses repeats
    noisy = new.Rules(Settings(low_fuel_l=3))
    assert only(run(noisy, [low(t, 2.0 if t % 2 else 3.6) for t in range(20)])) == []      # flapping across the exit threshold never persists
    unmet = new.Rules(Settings())
    assert only(run(unmet, [frame(0, fuel=1, fuel_capacity=0), frame(5, fuel=1, fuel_capacity=0)])) == []   # no capacity: prerequisite unmet


def test_fuel_critical_is_priority_zero_and_needs_motion():
    rules = new.Rules(Settings())
    events = run(rules, [frame(t, fuel=.2, fuel_capacity=50, speed_kmh=80) for t in (0, 2)])
    crit = [e for e in events if e.category == 'fuel_critical']
    assert crit and crit[0].priority == 0
    assert not [e for e in run(new.Rules(Settings()), [frame(t, fuel=.2, fuel_capacity=50, speed_kmh=0) for t in (0, 3)]) if e.category == 'fuel_critical']


def test_pause_or_off_track_clears_active_conditions():
    rules = new.Rules(Settings())
    rules.evaluate(frame(0, fuel=.2, fuel_capacity=50, speed_kmh=80), 'S')
    assert rules.active
    assert rules.evaluate(frame(1, flags=3), 'S') == [] and not rules.active               # paused: stale evidence dropped


def test_c_field_rule_needs_the_feature_flag():
    off = [frame(t, surface='GGSS', flags=1) for t in (0, 2)]
    assert not [e for e in run(new.Rules(Settings(trust_c_fields=False)), off) if e.category == 'off_surface']
    on = run(new.Rules(Settings(trust_c_fields=True)), [frame(t, surface='GGSS', flags=1) for t in (0, 2)])
    assert [e.category for e in on if e.category == 'off_surface']


def test_pit_speed_uses_configured_region_and_limit():
    cfg = Settings(pit_region=[-10, -10, 10, 10], pit_limit_kmh=60)
    inside = [frame(t, position=[0, 0, 0], speed_kmh=90) for t in (0, 2)]
    assert [e.category for e in run(new.Rules(cfg), inside) if e.category == 'pit_speed']
    outside = [frame(t, position=[500, 0, 500], speed_kmh=90) for t in (0, 2)]
    assert not [e for e in run(new.Rules(cfg), outside) if e.category == 'pit_speed']
    assert not [e for e in run(new.Rules(Settings()), inside) if e.category == 'pit_speed']   # nothing configured


# ---- parity ------------------------------------------------------------------------------------------------------
def random_frames(seed, n):
    """Regimes that hold for 1-15 s, so persistence/cooldown/exit hysteresis all get exercised (pure noise never fires)."""
    rnd = random.Random(seed)
    hold, regime = 0, {}
    for i in range(n):
        if hold <= 0:
            hold = rnd.randint(20, 300)
            regime = {
                'flags': rnd.choice([1, 1, 1, 1, 33, 65, 97, 3, 0, 1 | 32 | 64]),
                'fuel': rnd.choice([None, 0.1, 0.4, 0.7, 2.0, 2.4, 3.2, 3.6, 30.0]),
                'fuel_capacity': rnd.choice([50, 50, 100, 0]),
                'tyres': [rnd.choice([None, 60, 90, 101, 125, 70]) for _ in range(4)] if rnd.random() < .5 else [rnd.uniform(60, 130) for _ in range(4)],
                'speed_kmh': rnd.choice([None, 0, 4, 6, 25, 31, 37, 60, 120]),
                'throttle': rnd.choice([0, .05, .15, .25, 1.0]),
                'brake': rnd.choice([0, .05, .15, .25, 1.0]),
                'surface': rnd.choice(['TTTT', 'DDTT', 'GGSS', 'TTTD', None, '']),
                'position': rnd.choice([[0, 0, 0], [5, 0, 5], [50, 0, 50], [None, 0, 1]]),
            }
        hold -= 1
        s = frame(i / 20)
        s.values.update(regime)
        s.values['lap'] = i // 200
        yield s


@pytest.mark.parametrize('seed', range(8))
def test_declarative_rules_are_behaviourally_identical_to_the_legacy_implementation(seed):
    legacy = load_legacy()
    rnd = random.Random(seed)
    cfg = Settings(tyre_limit_c=rnd.choice([None, 95, 110]), trust_c_fields=bool(seed % 2), pit_limit_kmh=rnd.choice([None, 60]),
                   pit_region=[-10, -10, 20, 20] if seed % 3 == 0 else None, alert_cooldown=5, low_fuel_l=3, tyre_imbalance_c=10)
    old, cur = legacy.Rules(cfg), new.Rules(cfg)
    heat = {'rates': [.2, .2, .01, .3], 'anomalies': [5, 6, 0, 8], 'method': 'time'}
    total = 0
    for j, s in enumerate(random_frames(seed, 600)):
        tyre_heat = heat if j % 7 else None
        a = [(e.category, e.message, e.priority, e.timestamp, e.session, e.evidence) for e in old.evaluate(s, 'S', tyre_heat=tyre_heat)]
        b = [(e.category, e.message, e.priority, e.timestamp, e.session, e.evidence) for e in cur.evaluate(s, 'S', tyre_heat=tyre_heat)]
        assert a == b, (seed, j)
        total += len(b)
    assert total > 0            # the comparison exercised firing paths, not just silence
