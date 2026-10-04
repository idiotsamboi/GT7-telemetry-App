"""Local OBS browser-source overlays.

Every graphic template gets a fixed local address, `http://<host>:<port>/obs/<template-id>`, that works
with no league, group, credential, draft or program. The page polls `/obs-api/frame` (read-only, no
token: OBS browser sources cannot pair) and renders the template with GroupGraphics.GraphicView.

Frame source:
  * an active group (league/demo event) -> its published overlay view, so leagues "just work" here too;
  * otherwise -> a single-entry frame built from the local driver's own telemetry. Nothing is invented:
    only reported sample values, and graphics that need other drivers show their own unavailable states.

Configuration (global driver focus, per-overlay size/settings, the driver's display identity) is
USER_AUTHORED, stored in `obs-overlays.json` next to the settings, and edited through `/api/obs/*`
(paired browser only).
"""
import json
import os
import threading
import time
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .cars import identify
from .core.errors import AppError
from .group.graphics import GRAPHIC_TEMPLATES

SLOTS = ('primary', 'a', 'b', 'team', 'class')
TELEMETRY_FIELDS = ('position', 'lap', 'last_ms', 'best_ms', 'flags', 'car_id', 'speed_kmh', 'rpm', 'gear',
                    'throttle', 'brake', 'clutch', 'tyres', 'fuel', 'fuel_capacity', 'current_ms')
LOCAL_ENTRY = 'local'
FRAME_CACHE_S = 0.1
Text = Annotated[str, Field(max_length=160)]


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Identity(_Model):
    display_name: Annotated[str, Field(max_length=80)] = 'Driver'
    number: Annotated[str, Field(max_length=8)] = ''
    team: Text = ''
    class_name: Text = ''


class Size(_Model):
    width: int = Field(ge=100, le=3840)
    height: int = Field(ge=40, le=2160)


class Settings(_Model):
    title: Text | None = None
    rows: int | None = Field(None, ge=1, le=32)
    opacity: float | None = Field(None, ge=0, le=1)


class Focus(_Model):
    """Driver focus shared by every overlay. Empty string = automatic (see `resolve_slots`)."""
    primary: Annotated[str, Field(max_length=64)] = ''
    a: Annotated[str, Field(max_length=64)] = ''
    b: Annotated[str, Field(max_length=64)] = ''
    team: Text = ''
    class_name: Text = Field('', alias='class')
    primary_mode: Literal['manual', 'leader'] = 'manual'
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, populate_by_name=True)


class ObsConfig(_Model):
    identity: Identity = Field(default_factory=Identity)
    focus: Focus = Field(default_factory=Focus)
    preset: Literal['formula', 'endurance', 'minimal', 'neon', 'vintage', 'rally', 'oval', 'carbon', 'heritage', 'holo'] = 'formula'
    sizes: dict[str, Size] = Field(default_factory=dict, max_length=64)
    settings: dict[str, Settings] = Field(default_factory=dict, max_length=64)


def _known(template: str) -> None:
    if template not in GRAPHIC_TEMPLATES.ids():
        raise AppError.from_status(404, 'Unknown overlay')


class ObsStore:
    """Atomic JSON persistence; a corrupt or missing file falls back to defaults rather than failing."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.config = self._load()

    def _load(self) -> ObsConfig:
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            config = ObsConfig.model_validate(raw)
            if set(config.sizes) | set(config.settings) <= set(GRAPHIC_TEMPLATES.ids()):
                return config
        except (OSError, ValueError, ValidationError):
            pass
        return ObsConfig()

    def save(self, config: ObsConfig) -> ObsConfig:
        for template in {*config.sizes, *config.settings}:
            _known(template)
        with self.lock:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(config.model_dump(by_alias=True), indent=1), encoding='utf-8')
            os.replace(tmp, self.path)
            self.config = config
        return config

    def reset(self) -> ObsConfig:
        return self.save(ObsConfig())


def store_for(runtime) -> ObsStore:
    store = getattr(runtime, '_obs_store', None)
    if store is None:
        store = runtime._obs_store = ObsStore(Path(runtime.config.root) / 'obs-overlays.json')
    return store


def size_of(template, config: ObsConfig) -> dict:
    override = config.sizes.get(template.id)
    return {'width': override.width, 'height': override.height} if override else {'width': template.width, 'height': template.height}


# ---- frame sources -------------------------------------------------------------------------------

def _solo_entry(runtime, config: ObsConfig, now: float) -> dict:
    sample = runtime.sample
    received = runtime.received_at
    age = time.monotonic() - received if received else None
    stale = sample is None or age is None or age > runtime.settings.stale_seconds
    values = dict(sample.values) if sample else {}
    laps = [lap for lap in getattr(runtime.sessions, 'laps', []) if lap.get('complete')]
    comparable = [lap['duration_ms'] for lap in laps if lap.get('comparable')]
    fields = {}
    for key in TELEMETRY_FIELDS:
        if key in values:
            value = values[key]
            fields[key] = {'value': None if stale else value, 'source': 'reported', 'available': value is not None and not stale,
                           'source_time': None, 'received_time': now - age if age is not None else None,
                           'confidence': 'GT7 telemetry'}
    identity = config.identity.model_dump()
    return {'entry_id': LOCAL_ENTRY, 'identity': identity, 'car': identify(values.get('car_id')), 'car_id': values.get('car_id'),
            'stale': stale, 'received': now - age if age is not None else None, 'last_ms': values.get('last_ms'),
            'best_ms': min(comparable) if comparable else None, 'reported_best_ms': values.get('best_ms'),
            'completed_laps': len(laps), 'progress': None, 'D': None, 'median_lap_ms': None, 'in_pit': False,
            'clock_uncertainty_ms': None, 'quality': list(getattr(sample, 'quality', []) or []),
            'adjusted_laps': len(laps), 'penalty_ms': 0, 'adjusted_elapsed_ms': None, 'disqualified': False,
            'manual_order': None, 'position': None if stale else 1, 'gap_s': None, 'lap_separation': 0,
            'classification_source': 'local driver only', 'baseline_source': None, 'fields': fields, 'flags': []}


def _solo_frame(runtime, config: ObsConfig, now: float) -> dict:
    entry = _solo_entry(runtime, config, now)
    sample = runtime.sample
    track = getattr(runtime.track_map, 'layout_id', '') or ''
    from .tracks import LAYOUTS
    track_name = LAYOUTS.get(track, {}).get('name') if track else None
    return {'version': 1, 'group_id': LOCAL_ENTRY, 'event_id': LOCAL_ENTRY, 'session_id': runtime.sessions.id or '',
            'name': 'Local session', 'event_name': track_name or 'Local session',
            'state': 'running' if not entry['stale'] else 'idle',
            'provenance': (getattr(sample, 'provenance', None) or runtime.source or 'live') if sample else 'live',
            'format': 'practice', 'layout_id': track, 'started': None, 'ended': None, 'duration_s': None, 'laps': None,
            'timeline': now, 'coverage': 'local driver only', 'entries': [entry], 'map': [], 'map_model': None,
            'zones': [], 'instructions': [], 'messages': [], 'decisions': [], 'battles': [], 'steward_cue_active': None,
            'projection': None, 'results': None, 'branding': {'name': config.identity.display_name or 'GT7', 'tagline': '',
            'logos': {}, 'sponsors': [], 'teams': [], 'colors': {'primary': '#ed1b35', 'secondary': '#252530', 'accent': '#f5ce42',
            'background': '#101014', 'text': '#ffffff'}}, 'delay_s': 0}


def _league_frame(runtime, group) -> dict | None:
    service = runtime.group
    principal = {'kind': 'overlay', 'subject': 'obs-local', 'group_id': group['id']}
    frame = service.public_state(principal)
    # League logos/sponsor images are served by the group listener behind credentials; this local page has none.
    if isinstance(frame.get('branding'), dict):
        frame['branding'] = {**frame['branding'], 'logos': {}, 'sponsors': []}
    return frame


_cache: dict = {'at': 0.0, 'key': None, 'frame': None}


def current_frame(runtime, config: ObsConfig) -> tuple[str, dict]:
    """(mode, frame). Cached for FRAME_CACHE_S so several overlays polling together share one build."""
    now = time.time()
    group = runtime.group.active() if hasattr(runtime, 'group') else None
    key = (group['id'] if group else None, id(config))
    if _cache['frame'] is not None and _cache['key'] == key and now - _cache['at'] < FRAME_CACHE_S:
        return ('league' if group else 'solo'), _cache['frame']
    frame = _league_frame(runtime, group) if group else _solo_frame(runtime, config, now)
    _cache.update(at=now, key=key, frame=frame)
    return ('league' if group else 'solo'), frame


def resolve_slots(frame: dict, config: ObsConfig, mode: str) -> dict:
    """Global focus -> concrete entry ids. Unset focus falls back to something sensible, never to invented data."""
    entries = frame.get('entries') or []
    ids = {e['entry_id'] for e in entries}
    focus = config.focus
    ranked = sorted((e for e in entries if isinstance(e.get('position'), int) and e['position'] > 0), key=lambda e: e['position'])
    primary = focus.primary if focus.primary in ids else ''
    if focus.primary_mode == 'leader' and ranked:
        primary = ranked[0]['entry_id']
    if not primary:
        primary = LOCAL_ENTRY if mode == 'solo' else (ranked[0]['entry_id'] if ranked else (entries[0]['entry_id'] if entries else ''))
    a = focus.a if focus.a in ids else primary
    b = focus.b if focus.b in ids else ''
    team = focus.team or next((e['identity'].get('team', '') for e in entries if e['entry_id'] == primary), '')
    return {'primary': primary, 'a': a, 'b': b, 'team': team, 'class': focus.class_name}


def drivers_for_picker(runtime, config: ObsConfig) -> list[dict]:
    mode, frame = current_frame(runtime, config)
    return [{'entry_id': e['entry_id'], 'label': ('#' + e['identity'].get('number', '') + ' ' if e['identity'].get('number') else '') + (e['identity'].get('display_name') or 'Driver'),
             'team': e['identity'].get('team', ''), 'class_name': e['identity'].get('class_name', ''), 'stale': bool(e.get('stale'))}
            for e in (frame.get('entries') or [])]


def invalidate() -> None:
    _cache.update(frame=None)


def frame_payload(runtime, graphic: str) -> dict:
    """Everything one overlay page needs for one poll."""
    _known(graphic)
    template = GRAPHIC_TEMPLATES.get(graphic)
    config = store_for(runtime).config
    mode, data = current_frame(runtime, config)
    size = size_of(template, config)
    settings = config.settings.get(graphic, Settings()).model_dump(exclude_none=True)
    workspace = {'preset': config.preset, 'slots': resolve_slots(data, config, mode), 'branding': {}, 'auto_steward': True}
    return {'mode': mode, 'state': data, 'workspace': workspace,
            'graphic': {'id': graphic, 'template': graphic, 'visible': True, 'x': 0, 'y': 0, **size, 'entry_id': '',
                        'slot': template.slots[0] if template.slots else 'primary', 'duration_s': 0, 'settings': settings}}


def overview(runtime, base: str) -> dict:
    """What the in-app OBS page shows."""
    config = store_for(runtime).config
    mode, data = current_frame(runtime, config)
    return {'mode': mode, 'base_url': base, 'config': config.model_dump(by_alias=True), 'overlays': catalog(config, base),
            'drivers': drivers_for_picker(runtime, config), 'slots': resolve_slots(data, config, mode),
            'provenance': data.get('provenance'), 'group_name': data.get('name') if mode == 'league' else None}


def catalog(config: ObsConfig, base: str) -> list[dict]:
    rows = []
    for template in GRAPHIC_TEMPLATES:
        size = size_of(template, config)
        rows.append({'id': template.id, 'name': template.name, 'category': template.category, 'url': f'{base}/obs/{template.id}',
                     'default_width': template.width, 'default_height': template.height, **size,
                     'settings': config.settings.get(template.id, Settings()).model_dump(exclude_none=True),
                     'sharing': list(template.required_sharing), 'slots': list(template.slots)})
    return rows


