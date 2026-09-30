"""Graphic template registry (group/graphics.py) and published state models (group/state_models.py)."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.app.core.registry import DuplicateRegistration
from backend.app.group import graphics, state_models
from backend.app.group.graphics import GRAPHIC_TEMPLATES, GraphicTemplate, public_templates
from backend.app.group.models import GRAPHICS, Graphic
from backend.app.group.public import registry
from backend.app.group.service import GroupService

# The table as it was before it became a registry: name, width, height per template, in order.
PREVIOUS = {
    'timing': ('Timing tower', 440, 850), 'session': ('Session bar', 1200, 100),
    'flag': ('Flag banner', 1000, 130), 'message': ('Race-control message', 1100, 160),
    'driver': ('Driver lower third', 900, 210), 'telemetry': ('Selected-car telemetry', 620, 260),
    'comparison': ('Head-to-head comparison', 1000, 300), 'map': ('Track map', 600, 600),
    'results': ('Grid/results panel', 1200, 850), 'slate': ('League/event slate', 1920, 1080),
    'fastest_lap': ('Fastest lap announcement', 900, 160), 'class_leader': ('Class leader panel', 680, 460),
    'penalty': ('Penalty / investigation notice', 1000, 160), 'podium': ('Podium', 900, 620),
    'sponsor': ('Sponsor rotation', 700, 220),
    'fuel_status': ('Fuel level', 420, 220), 'tyre_temps': ('Tyre temperatures', 420, 320),
    'pit_board': ('Pit board', 700, 220), 'starting_soon': ('Starting soon slate', 1920, 1080),
    'session_clock': ('Session clock', 420, 180),
    'classification_strip': ('Classification strip', 1824, 180), 'team_roster': ('Team roster', 700, 500),
    'lap_board': ('Lap-time board', 800, 520), 'speed_comparison': ('Speed comparison', 1000, 300),
    'connection_status': ('Connection status', 700, 500), 'event_info': ('Event information', 780, 440),
    'battle_tag': ('Battle tag', 500, 120), 'net_order': ('Projected order after stops', 800, 640)}


def test_legacy_graphics_table_is_unchanged():
    assert dict(GRAPHICS) == PREVIOUS
    assert list(GRAPHICS) == list(PREVIOUS)                      # order is the studio library order
    assert graphics.legacy_graphics() == PREVIOUS


def test_template_literal_tracks_the_registry():
    for template_id in PREVIOUS:
        assert Graphic(id='x', template=template_id).template == template_id
    with pytest.raises(ValueError):
        Graphic(id='x', template='not_a_template')
    assert set(GRAPHIC_TEMPLATES.ids()) == set(PREVIOUS) and len(GRAPHIC_TEMPLATES) == 28


def test_every_template_fulfils_the_contract():
    for template in GRAPHIC_TEMPLATES:
        assert template.name and template.category and template.renderer and template.preview_fixture
        assert template.stage in ('implemented', 'beta', 'planned')
        assert template.required_sharing and set(template.required_sharing) <= {'basic', 'telemetry', 'fuel', 'strategy'}
        assert template.required_models, template.id
        assert set(template.required_models) <= state_models.MODEL_NAMES, template.id
        assert set(template.lifecycle) == {'enter_ms', 'exit_ms', 'supports_popup'}
        assert template.lifecycle['enter_ms'] >= 0 and template.lifecycle['exit_ms'] >= 0
        assert set(template.config_schema) == {'title', 'rows', 'opacity'}    # what Graphic.settings accepts
        w, h = template.default_size
        assert 100 <= w <= 1920 and 50 <= h <= 1080


def test_sharing_and_models_match_what_each_graphic_reads():
    by_id = {t.id: t for t in GRAPHIC_TEMPLATES}
    assert by_id['net_order'].required_sharing == ('fuel', 'strategy')      # gated on both categories
    assert by_id['fuel_status'].required_sharing == ('fuel',)
    assert by_id['speed_comparison'].required_sharing == ('telemetry',)
    assert 'ProjectionState' in by_id['net_order'].required_models
    assert {'DecisionState', 'StewardCue'} <= set(by_id['penalty'].required_models)
    assert 'BattleState' in by_id['battle_tag'].required_models
    assert 'MessageState' in by_id['message'].required_models and 'FlagState' in by_id['flag'].required_models
    assert by_id['penalty'].lifecycle['supports_popup'] and not by_id['timing'].lifecycle['supports_popup']
    assert by_id['battle_tag'].slots == ('a', 'b') and by_id['flag'].slots == ('primary',)


def test_public_templates_are_json_safe():
    listing = public_templates()
    assert len(listing) == 28
    assert json.loads(json.dumps(listing)) == listing                        # no callables, tuples, or classes
    first = listing[0]
    assert first['default_size'] == {'width': 440, 'height': 850}
    assert isinstance(first['required_sharing'], list) and isinstance(first['required_models'], list)
    assert {'id', 'name', 'category', 'default_size', 'required_sharing', 'required_models', 'config_schema',
            'renderer', 'preview_fixture', 'lifecycle', 'stage'} <= set(first)
    listing[0]['config_schema']['title']['max_length'] = 1                    # a copy: registry is not affected
    assert GRAPHIC_TEMPLATES.require('timing').config_schema['title']['max_length'] == 160


def test_public_registry_rows_keep_their_shape_and_gain_contract_fields():
    rows = {row['id']: row for row in registry()}
    assert len(rows) == 28
    for row in rows.values():
        assert {'id', 'name', 'width', 'height', 'status', 'data', 'permissions', 'unavailable', 'slots', 'settings'} <= set(row)
        assert row['status'] == 'implemented' and row['permissions'] and row['unavailable'] and row['settings']
        assert row['category'] and row['required_models'] and 'enter_ms' in row['lifecycle']
    assert rows['net_order']['permissions'] == ['fuel', 'strategy']
    assert rows['telemetry']['data'] == ['speed_kmh', 'rpm', 'gear', 'throttle', 'brake', 'clutch']
    assert rows['comparison']['slots'] == ['a', 'b'] and rows['team_roster']['slots'] == ['primary']
    assert rows['timing']['data'] == ['permitted group state'] and rows['timing']['permissions'] == ['basic']


def test_duplicate_template_ids_fail_loudly():
    with pytest.raises(DuplicateRegistration):
        GRAPHIC_TEMPLATES.register(GraphicTemplate(id='timing', name='Again', category='timing', default_size=(1, 1)))


# ------------------------------------------------------------------ state models

def build_state(tmp_path, share_traffic=False):
    s = GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / 'db.sqlite'), config=SimpleNamespace(root=tmp_path)))

    async def setup():
        league = await s.league_save({'name': 'Models'})
        await s.create_group({'name': 'M', 'event_name': 'E', 'league_id': league['id'], 'approval': False,
                              'share_traffic_with_drivers': share_traffic})
        spectator = await s.join({'credential': (await s.invite('spectator'))['credential'], 'identity': {'display_name': 'S'}})
        driver = await s.join({'credential': (await s.invite('driver'))['credential'], 'identity': {'display_name': 'D', 'number': '1'}})
        workspace = await s.save_workspace({'name': 'W'})
        return (await s.authenticate(spectator['token'], ('spectator',)), await s.authenticate(driver['token'], ('driver',)),
                workspace)
    spectator, driver, workspace = asyncio.run(setup())
    return s, spectator, driver, workspace


def test_published_snapshot_declares_exactly_the_keys_the_service_publishes(tmp_path):
    s, spectator, driver, workspace = build_state(tmp_path)
    declared = state_models.keys_of(state_models.PublishedSnapshot)
    frame = s.public_state(spectator, workspace)
    assert set(frame) == declared, (set(frame) ^ declared)
    assert {'workspace', 'program_revision', 'taken_at'} <= set(frame)


def test_traffic_and_entry_shapes_match_the_models(tmp_path):
    s, spectator, driver, _ = build_state(tmp_path, share_traffic=True)
    frame = s.public_state(driver)
    assert 'traffic' in frame and frame['battles'] == []
    row = frame['entries'][0]
    assert set(row) == state_models.keys_of(state_models.EntryRow)
    assert set(row['identity']) == state_models.keys_of(state_models.Identity)
    traffic = frame['traffic'][0]
    assert set(traffic) == state_models.keys_of(state_models.TrafficRow)


def test_state_model_groups_partition_the_frame_sensibly():
    models = state_models.STATE_MODELS
    assert {'RaceState', 'TimingState', 'SelectedEntries', 'FlagState', 'MessageState', 'DecisionState', 'BattleState',
            'ProjectionState', 'SessionClock', 'BrandingSnapshot', 'StewardCue'} <= set(models)
    published = state_models.keys_of(state_models.PublishedSnapshot)
    for name in ('RaceState', 'TimingState', 'FlagState', 'MessageState', 'DecisionState', 'BattleState',
                 'ProjectionState', 'SessionClock', 'BrandingSnapshot', 'StewardCue'):
        assert state_models.keys_of(models[name]) <= published, name
