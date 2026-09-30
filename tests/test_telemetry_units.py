import pytest

from backend.app.telemetry import units


@pytest.mark.parametrize('unit', ['kmh', 'mph'])
def test_speed_round_trip(unit):
    for v in (0.0, 1.0, 59.94, 123.456):
        assert units.speed_to_ms(units.speed(v, unit), unit) == pytest.approx(v)


def test_speed_known_values():
    assert units.speed(10, 'kmh') == pytest.approx(36)
    assert units.speed(26.8224, 'mph') == pytest.approx(60, rel=1e-4)


@pytest.mark.parametrize('unit', ['C', 'F'])
def test_temp_round_trip(unit):
    for v in (-40.0, 0.0, 78.5, 120.0):
        assert units.temp_to_c(units.temp(v, unit), unit) == pytest.approx(v)
    assert units.temp(100, 'F') == pytest.approx(212)


@pytest.mark.parametrize('unit', ['L', 'gal_us', 'gal_uk'])
def test_fuel_round_trip(unit):
    assert units.fuel_to_l(units.fuel(42.5, unit), unit) == pytest.approx(42.5)
    assert units.fuel(3.785411784, 'gal_us') == pytest.approx(1)
    assert units.fuel(4.54609, 'gal_uk') == pytest.approx(1)


@pytest.mark.parametrize('unit', ['m', 'km', 'mi'])
def test_distance_round_trip(unit):
    assert units.distance_to_m(units.distance(5432.1, unit), unit) == pytest.approx(5432.1)
    assert units.distance(1609.344, 'mi') == pytest.approx(1)


@pytest.mark.parametrize('unit', ['bar', 'psi'])
def test_pressure_round_trip(unit):
    assert units.pressure_to_bar(units.pressure(2.2, unit), unit) == pytest.approx(2.2)
    assert units.pressure(1, 'psi') == pytest.approx(14.5038, rel=1e-4)


def test_none_passes_through():
    for fn in (units.speed, units.speed_to_ms, units.temp, units.temp_to_c, units.fuel, units.fuel_to_l,
               units.distance, units.distance_to_m, units.pressure, units.pressure_to_bar):
        assert fn(None) is None


def test_unknown_units_raise():
    for fn in (units.speed, units.speed_to_ms, units.temp, units.temp_to_c, units.fuel, units.fuel_to_l,
               units.distance, units.distance_to_m, units.pressure, units.pressure_to_bar):
        with pytest.raises(ValueError):
            fn(1.0, 'furlongs')
        with pytest.raises(ValueError):
            fn(None, 'furlongs')      # validated even for None
    with pytest.raises(ValueError):
        units.label('speed', 'knots')
    with pytest.raises(ValueError):
        units.label('nonsense', 'kmh')


def test_labels():
    assert units.label('speed', 'kmh') == 'km/h'
    assert units.label('speed', 'mph') == 'mph'
    assert units.label('temp', 'F') == '°F'
    assert units.label('fuel', 'gal_us') == 'gal'
    assert units.label('pressure', 'psi') == 'psi'
    assert units.label('distance', 'mi') == 'mi'


def test_spoken_speed_both_systems():
    assert units.spoken_speed(215 / 3.6, 'kmh') == '215 kilometres per hour'
    assert units.spoken_speed(60, 'kmh') == '216 kilometres per hour'
    assert units.spoken_speed(60, 'mph') == '134 miles per hour'
    assert units.spoken_speed(None, 'mph') is None
    with pytest.raises(ValueError):
        units.spoken_speed(10, 'knots')
