"""Unit conversion. Canonical (internal) units are m/s, m, degrees C, L, bar, s, rad, rad/s, rpm.

Everything stored, published on the bus or sent over the API is canonical; conversion to the driver's
preferred units happens at the edge (UI formatting, server-spoken phrasing).  `None` passes through
unchanged so callers never need to guard missing channels.  Unknown units raise ValueError.
"""
from typing import Optional

Number = Optional[float]

_MS_TO_KMH = 3.6
_MS_TO_MPH = 2.2369362920544
_GAL_US_L = 3.785411784
_GAL_UK_L = 4.54609
_MILE_M = 1609.344
_PSI_BAR = 14.503773773


def _bad(kind: str, unit: str) -> ValueError:
    return ValueError(f'unknown {kind} unit {unit!r}')


# --- speed: m/s <-> kmh | mph -------------------------------------------------------------------
def speed(m_s: Number, unit: str = 'kmh') -> Number:
    if unit == 'kmh':
        factor = _MS_TO_KMH
    elif unit == 'mph':
        factor = _MS_TO_MPH
    else:
        raise _bad('speed', unit)
    return None if m_s is None else m_s * factor


def speed_to_ms(value: Number, unit: str = 'kmh') -> Number:
    if unit not in ('kmh', 'mph'):
        raise _bad('speed', unit)
    if value is None:
        return None
    return value / (_MS_TO_KMH if unit == 'kmh' else _MS_TO_MPH)


# --- temperature: C <-> C | F ---------------------------------------------------------------------
def temp(c: Number, unit: str = 'C') -> Number:
    if unit not in ('C', 'F'):
        raise _bad('temperature', unit)
    if c is None:
        return None
    return c if unit == 'C' else c * 9 / 5 + 32


def temp_to_c(value: Number, unit: str = 'C') -> Number:
    if unit not in ('C', 'F'):
        raise _bad('temperature', unit)
    if value is None:
        return None
    return value if unit == 'C' else (value - 32) * 5 / 9


# --- fuel: L <-> L | gal_us | gal_uk -------------------------------------------------------------
_FUEL = {'L': 1.0, 'gal_us': _GAL_US_L, 'gal_uk': _GAL_UK_L}


def fuel(litres: Number, unit: str = 'L') -> Number:
    if unit not in _FUEL:
        raise _bad('fuel', unit)
    return None if litres is None else litres / _FUEL[unit]


def fuel_to_l(value: Number, unit: str = 'L') -> Number:
    if unit not in _FUEL:
        raise _bad('fuel', unit)
    return None if value is None else value * _FUEL[unit]


# --- distance: m <-> m | km | mi -----------------------------------------------------------------
_DISTANCE = {'m': 1.0, 'km': 1000.0, 'mi': _MILE_M}


def distance(m: Number, unit: str = 'm') -> Number:
    if unit not in _DISTANCE:
        raise _bad('distance', unit)
    return None if m is None else m / _DISTANCE[unit]


def distance_to_m(value: Number, unit: str = 'm') -> Number:
    if unit not in _DISTANCE:
        raise _bad('distance', unit)
    return None if value is None else value * _DISTANCE[unit]


# --- pressure: bar <-> bar | psi -----------------------------------------------------------------
def pressure(bar: Number, unit: str = 'bar') -> Number:
    if unit not in ('bar', 'psi'):
        raise _bad('pressure', unit)
    if bar is None:
        return None
    return bar if unit == 'bar' else bar * _PSI_BAR


def pressure_to_bar(value: Number, unit: str = 'bar') -> Number:
    if unit not in ('bar', 'psi'):
        raise _bad('pressure', unit)
    if value is None:
        return None
    return value if unit == 'bar' else value / _PSI_BAR


# --- labels ------------------------------------------------------------------------------------
_LABELS = {
    'speed': {'kmh': 'km/h', 'mph': 'mph'},
    'temp': {'C': '°C', 'F': '°F'},
    'fuel': {'L': 'L', 'gal_us': 'gal', 'gal_uk': 'gal (UK)'},
    'distance': {'m': 'm', 'km': 'km', 'mi': 'mi'},
    'pressure': {'bar': 'bar', 'psi': 'psi'},
}


def label(kind: str, unit: str) -> str:
    """Short display label, e.g. label('speed', 'kmh') -> 'km/h'."""
    try:
        return _LABELS[kind][unit]
    except KeyError:
        raise ValueError(f'unknown unit {unit!r} for kind {kind!r}') from None


def spoken_speed(m_s: Number, unit: str = 'kmh') -> str | None:
    """Phrase for server-spoken output: '215 kilometres per hour' / '134 miles per hour'."""
    value = speed(m_s, unit)
    if value is None:
        return None
    words = 'kilometres per hour' if unit == 'kmh' else 'miles per hour'
    return f'{round(value)} {words}'


# --- server-spoken phrasing for values the engineer catalogue already holds in the "default" spoken unit ---------------
_SPOKEN_WORDS = {
    'speed': {'kmh': 'kilometres per hour', 'mph': 'miles per hour'},
    'fuel': {'L': 'litres', 'gal_us': 'US gallons', 'gal_uk': 'UK gallons'},
    'temperature': {'C': 'degrees Celsius', 'F': 'degrees Fahrenheit'},
}
_DEFAULT_WORD = {'kilometres per hour': ('speed', 'kmh'), 'litres': ('fuel', 'L'), 'degrees Celsius': ('temperature', 'C')}


def spoken_measure(value: Number, unit_word: str, units) -> tuple[Number, str]:
    """Localise a value the engineer catalogue expresses in km/h, litres or degrees Celsius.

    `unit_word` is the catalogue's word (it may carry a suffix such as 'litres, not a guarantee'); `units` is
    `Settings.units` (duck-typed: .speed/.fuel/.temperature). Anything else, or the default units, passes
    through unchanged, so existing phrasing is byte-identical for default settings."""
    for base, (kind, canonical) in _DEFAULT_WORD.items():
        if unit_word == base or unit_word.startswith(base + ','):
            wanted = getattr(units, kind, canonical)
            if wanted == canonical:
                return value, unit_word
            suffix = unit_word[len(base):]
            if kind == 'speed':
                converted = speed(None if value is None else value / _MS_TO_KMH, wanted)
            elif kind == 'fuel':
                converted = fuel(value, wanted)
            else:
                converted = temp(value, wanted)
            return converted, _SPOKEN_WORDS[kind][wanted] + suffix
    return value, unit_word
