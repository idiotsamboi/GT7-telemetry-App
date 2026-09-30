"""Broadcast graphic templates: one registry entry per template instead of scattered tables.

`GraphicTemplate` is the contract a template fulfils: what it is called and where it sits, which
sharing categories and published state models it needs, which settings it accepts, how it enters
and leaves, and how to render and preview it. Adding a template means adding one row here (plus
its renderer case in frontend/src/GroupGraphics.tsx).

`models.GRAPHICS` (id -> (name, width, height)) is derived from this registry for older callers.
"""
from dataclasses import dataclass, field
from typing import Any

from ..core.registry import Registry

DEFAULT_SETTINGS_SCHEMA: dict[str, dict] = {
    'title': {'type': 'text', 'max_length': 160},
    'rows': {'type': 'integer', 'min': 1, 'max': 32},
    'opacity': {'type': 'number', 'min': 0, 'max': 1},
}
UNAVAILABLE_POLICY = 'label unavailable or hide; never infer missing game facts'
RENDERER = 'GroupGraphics.GraphicView'      # the component; it switches on the template id
DEFAULT_LIFECYCLE = {'enter_ms': 250, 'exit_ms': 250, 'supports_popup': False}


@dataclass(frozen=True)
class GraphicTemplate:
    id: str
    name: str
    category: str
    default_size: tuple[int, int]                       # (width, height) on the 1920x1080 canvas
    required_sharing: tuple[str, ...] = ('basic',)     # sharing categories the group must publish
    required_models: tuple[str, ...] = ()               # state_models.STATE_MODELS names it reads
    config_schema: dict = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULT_SETTINGS_SCHEMA.items()})
    renderer: str = RENDERER
    preview_fixture: str = 'league_demo'                # synthetic-demo frame that exercises it
    lifecycle: dict = field(default_factory=lambda: dict(DEFAULT_LIFECYCLE))
    stage: str = 'implemented'                          # 'implemented' | 'beta' | 'planned'
    data_needs: tuple[str, ...] = ('permitted group state',)   # human-readable fields it reads
    slots: tuple[str, ...] = ()                         # entry slots it points at ('primary', 'a', 'b')

    def to_public(self) -> dict:
        """JSON-safe description: no callables, tuples as lists."""
        return {
            'id': self.id, 'name': self.name, 'category': self.category,
            'default_size': {'width': self.default_size[0], 'height': self.default_size[1]},
            'required_sharing': list(self.required_sharing), 'required_models': list(self.required_models),
            'config_schema': {k: dict(v) for k, v in self.config_schema.items()},
            'renderer': self.renderer, 'preview_fixture': self.preview_fixture,
            'lifecycle': dict(self.lifecycle), 'stage': self.stage,
            'data': list(self.data_needs), 'slots': list(self.slots),
        }

    @property
    def width(self) -> int:
        return self.default_size[0]

    @property
    def height(self) -> int:
        return self.default_size[1]


GRAPHIC_TEMPLATES: Registry[GraphicTemplate] = Registry('graphic templates', public=lambda t: t.to_public())

_POPUP = {'enter_ms': 250, 'exit_ms': 250, 'supports_popup': True}
_SELECTED = ('primary',)
_PAIR = ('a', 'b')


def _t(id: str, name: str, category: str, width: int, height: int, *, models: tuple[str, ...] = (),
       sharing: tuple[str, ...] = ('basic',), data: tuple[str, ...] = ('permitted group state',),
       slots: tuple[str, ...] = (), lifecycle: dict | None = None, fixture: str = 'league_demo') -> None:
    GRAPHIC_TEMPLATES.register(GraphicTemplate(
        id=id, name=name, category=category, default_size=(width, height), required_sharing=sharing,
        required_models=models, data_needs=data, slots=slots, preview_fixture=fixture,
        lifecycle=dict(lifecycle or DEFAULT_LIFECYCLE)))


# Order is the order the studio library shows them in. Models were read off GroupGraphics.tsx.
_t('timing', 'Timing tower', 'timing', 440, 850, models=('TimingState',))
_t('session', 'Session bar', 'session', 1200, 100, models=('RaceState', 'SessionClock'))
_t('flag', 'Flag banner', 'race_control', 1000, 130, models=('FlagState', 'SelectedEntries'), slots=_SELECTED,
   lifecycle=_POPUP)
_t('message', 'Race-control message', 'race_control', 1100, 160, models=('MessageState',), lifecycle=_POPUP)
_t('driver', 'Driver lower third', 'driver', 900, 210, models=('SelectedEntries',), slots=_SELECTED)
_t('telemetry', 'Selected-car telemetry', 'telemetry', 620, 260, models=('SelectedEntries',), sharing=('telemetry',),
   data=('speed_kmh', 'rpm', 'gear', 'throttle', 'brake', 'clutch'), slots=_SELECTED)
_t('comparison', 'Head-to-head comparison', 'driver', 1000, 300, models=('SelectedEntries',), slots=_PAIR)
_t('map', 'Track map', 'map', 600, 600, models=('RaceState', 'TimingState'), data=('position',))
_t('results', 'Grid/results panel', 'results', 1200, 850, models=('TimingState',))
_t('slate', 'League/event slate', 'branding', 1920, 1080, models=('BrandingSnapshot', 'RaceState'))
_t('fastest_lap', 'Fastest lap announcement', 'timing', 900, 160, models=('TimingState',), lifecycle=_POPUP)
_t('class_leader', 'Class leader panel', 'timing', 680, 460, models=('TimingState',),
   data=('position classification', 'class_name'))
_t('penalty', 'Penalty / investigation notice', 'race_control', 1000, 160,
   models=('DecisionState', 'StewardCue', 'TimingState'), lifecycle=_POPUP)
_t('podium', 'Podium', 'results', 900, 620, models=('TimingState',))
_t('sponsor', 'Sponsor rotation', 'branding', 700, 220, models=('BrandingSnapshot', 'SessionClock'))
_t('fuel_status', 'Fuel level', 'telemetry', 420, 220, models=('SelectedEntries',), sharing=('fuel',),
   data=('fuel', 'fuel_capacity'), slots=_SELECTED)
_t('tyre_temps', 'Tyre temperatures', 'telemetry', 420, 320, models=('SelectedEntries',), sharing=('telemetry',),
   data=('tyres',), slots=_SELECTED)
_t('pit_board', 'Pit board', 'driver', 700, 220, models=('SelectedEntries',), slots=_SELECTED)
_t('starting_soon', 'Starting soon slate', 'branding', 1920, 1080, models=('BrandingSnapshot', 'RaceState'))
_t('session_clock', 'Session clock', 'session', 420, 180, models=('SessionClock',))
_t('classification_strip', 'Classification strip', 'timing', 1824, 180, models=('TimingState',),
   data=('position classification',))
_t('team_roster', 'Team roster', 'driver', 700, 500, models=('TimingState', 'SelectedEntries'),
   data=('team', 'identity'), slots=_SELECTED)
_t('lap_board', 'Lap-time board', 'timing', 800, 520, models=('TimingState',), data=('last_ms', 'best_ms'))
_t('speed_comparison', 'Speed comparison', 'telemetry', 1000, 300, models=('SelectedEntries',), sharing=('telemetry',),
   data=('speed_kmh',), slots=_PAIR)
_t('connection_status', 'Connection status', 'timing', 700, 500, models=('TimingState',), data=('stale', 'identity'))
_t('event_info', 'Event information', 'session', 780, 440, models=('RaceState', 'BrandingSnapshot'),
   data=('event_name', 'format', 'state'))
_t('battle_tag', 'Battle tag', 'timing', 500, 120, models=('BattleState', 'SelectedEntries'),
   data=('battle heat, gap and closing rate',), slots=_PAIR, fixture='league_demo:battle')
# net_order needs BOTH fuel and strategy: the public projection is only published when the
# group publishes both categories (GroupService._public_projection).
_t('net_order', 'Projected order after stops', 'strategy', 800, 640, models=('ProjectionState', 'TimingState'),
   sharing=('fuel', 'strategy'), data=('fuel', 'strategy', 'pit stop history'), fixture='league_demo:fuel_strategy')


def public_templates() -> list[dict]:
    """JSON-safe listing of every template (what /group-api/info and the studio library expose)."""
    return GRAPHIC_TEMPLATES.to_public()


def legacy_graphics() -> dict[str, tuple[str, int, int]]:
    """The old `GRAPHICS` shape: id -> (name, width, height)."""
    return {t.id: (t.name, t.width, t.height) for t in GRAPHIC_TEMPLATES}


def template_ids() -> tuple[str, ...]:
    return tuple(GRAPHIC_TEMPLATES.ids())


def describe(template: GraphicTemplate) -> dict[str, Any]:
    """The row `public.registry()` has always produced, plus the new contract fields."""
    return {'id': template.id, 'name': template.name, 'width': template.width, 'height': template.height,
            'status': template.stage, 'data': list(template.data_needs), 'permissions': list(template.required_sharing),
            'unavailable': UNAVAILABLE_POLICY, 'slots': list(template.slots),
            'settings': {k: dict(v) for k, v in template.config_schema.items()},
            'category': template.category, 'required_models': list(template.required_models),
            'lifecycle': dict(template.lifecycle)}
