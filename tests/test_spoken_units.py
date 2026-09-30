"""Server-spoken phrasing follows Settings.units; default units keep the previous wording byte-for-byte."""
import pytest

from backend.app.config import Config
from backend.app.requests import answer
from backend.app.runtime import Runtime
from backend.app.storage import Store
from backend.app.telemetry import demo_sample
from backend.app.telemetry.units import spoken_measure


def make(tmp_path, **units):
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False, 'units': units or cfg.settings.units.model_dump()})
    store = Store(tmp_path / 't.db')
    r = Runtime(cfg, store)
    for i in range(30):
        r.consume(demo_sample(i / 60, i))
    r.sample.values['speed_kmh'] = 160.9344            # exactly 100 mph
    r.sample.values['fuel'] = 37.85411784               # exactly 10 US gallons
    r.sample.values['tyres'] = [100.0, 100.0, 50.0, None]
    return r, store


def texts(r, action):
    return [answer(r, action, 'base')[0] for _ in range(3)]


def test_default_units_keep_the_original_wording(tmp_path):
    r, store = make(tmp_path)
    assert r.execute('status')['answer'].endswith('161 kilometres per hour.')
    assert r.execute('fuel')['answer'].startswith('37.9 litres remaining.') or 'litres remaining' in r.execute('fuel')['answer']
    assert any('161 kilometres per hour' in t or '160.9 kilometres per hour' in t for t in texts(r, 'speed'))
    store.close()


def test_mph_gallons_and_fahrenheit_phrasing(tmp_path):
    r, store = make(tmp_path, speed='mph', fuel='gal_us', temperature='F')
    assert r.execute('status')['answer'].endswith('100 miles per hour.')
    assert 'kilometres' not in r.execute('status')['answer']
    assert '10.0 US gallons remaining' in r.execute('fuel')['answer']
    speeds = texts(r, 'speed')
    assert all('miles per hour' in t and 'kilometres' not in t for t in speeds) and all('100' in t for t in speeds)
    capacity = texts(r, 'capacity')
    assert all('US gallons' in t and 'litres' not in t for t in capacity)
    tyres = r.execute('tyres')['answer']
    assert tyres.startswith('Tyre surface temperatures: 212, 212, 122, unavailable degrees Fahrenheit')
    store.close()


def test_uk_gallons_and_unrelated_units_pass_through(tmp_path):
    r, store = make(tmp_path, fuel='gal_uk')
    assert all('UK gallons' in t for t in texts(r, 'capacity'))
    assert all('revolutions per minute' in t for t in texts(r, 'rpm'))          # not a unit preference: untouched
    store.close()


@pytest.mark.parametrize('word,units,expect', [
    ('kilometres per hour', {'speed': 'mph'}, (62.1371192, 'miles per hour')),
    ('litres', {'fuel': 'gal_uk'}, (1 / 4.54609, 'UK gallons')),
    ('litres, not a guarantee', {'fuel': 'gal_us'}, (1 / 3.785411784, 'US gallons, not a guarantee')),
    ('degrees Celsius', {'temperature': 'F'}, (33.8, 'degrees Fahrenheit')),
    ('seconds', {'speed': 'mph'}, (1, 'seconds')),
])
def test_spoken_measure_conversions(word, units, expect):
    from types import SimpleNamespace
    value = {'kilometres per hour': 100, 'degrees Celsius': 1}.get(word, 1)
    number, out = spoken_measure(value, word, SimpleNamespace(**{'speed': 'kmh', 'fuel': 'L', 'temperature': 'C', **units}))
    assert out == expect[1] and number == pytest.approx(expect[0], rel=1e-6)


def test_missing_values_pass_through():
    from types import SimpleNamespace
    assert spoken_measure(None, 'litres', SimpleNamespace(fuel='gal_us')) == (None, 'US gallons')
