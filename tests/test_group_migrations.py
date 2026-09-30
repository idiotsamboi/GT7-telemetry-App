"""Group document schema versions and upgrades (group/migrations.py)."""
import asyncio
import io
import json
from types import SimpleNamespace

import pytest

from backend.app.core.errors import AppError
from backend.app.group import migrations
from backend.app.group.assets import Assets
from backend.app.group.migrations import CURRENT_SCHEMA, MissingUpgrade, UPGRADES, ensure_team_ids, upgrade
from backend.app.group.repository import GroupRepository
from backend.app.group.service import GroupService


def old_league():
    """A league as stored before per-document schemas: no `schema`, teams without team_id."""
    return {'id': 'league-1', 'revision': 3, 'branding': {
        'name': 'Old League', 'teams': [
            {'id': 'front-uuid-1', 'name': 'Scuderia Apex', 'asset': '', 'color': '#ffffff'},
            {'name': 'Vector Racing', 'asset': '', 'color': '#000000'},
            {'name': 'Vector Racing', 'asset': '', 'color': '#111111'}],
        'sponsors': [], 'logos': {}}}


def insert_raw(path, kind, id, parent, payload):
    repo = GroupRepository(path)          # creates tables
    with repo.connect() as db:
        db.execute('INSERT INTO group_documents VALUES(?,?,?,?)', (kind, id, parent, json.dumps(payload)))
    return repo


def raw_payload(path, id):
    with GroupRepository(path).connect() as db:
        return json.loads(db.execute('SELECT payload FROM group_documents WHERE id=?', (id,)).fetchone()[0])


def test_documents_without_schema_count_as_schema_1_and_upgrade():
    doc = upgrade('league', old_league())
    assert doc['schema'] == CURRENT_SCHEMA['league'] == 2
    teams = doc['branding']['teams']
    assert teams[0]['team_id'] == 'front-uuid-1'                         # existing frontend id is reused
    assert all(t['team_id'] for t in teams)
    assert len({t['team_id'] for t in teams}) == 3                       # duplicate names still get distinct ids
    assert [t['name'] for t in teams] == ['Scuderia Apex', 'Vector Racing', 'Vector Racing']   # name lookups intact
    assert {t['name']: t for t in teams}['Scuderia Apex']['color'] == '#ffffff'


def test_upgrade_is_idempotent_and_ids_are_deterministic():
    first = upgrade('league', old_league())
    second = upgrade('league', json.loads(json.dumps(first)))
    assert first == second
    assert upgrade('league', old_league())['branding']['teams'][1]['team_id'] == first['branding']['teams'][1]['team_id']
    other_league = old_league()
    other_league['id'] = 'league-2'
    assert upgrade('league', other_league)['branding']['teams'][1]['team_id'] != first['branding']['teams'][1]['team_id']


def test_ensure_team_ids_keeps_existing_and_survives_rename():
    teams = [{'name': 'A', 'team_id': 'keep-me'}, {'name': 'B'}]
    ensure_team_ids(teams, 'L')
    before = teams[1]['team_id']
    assert teams[0]['team_id'] == 'keep-me' and before
    teams[1]['name'] = 'B renamed'
    ensure_team_ids(teams, 'L')
    assert teams[1]['team_id'] == before                                 # stable across renames


def test_group_snapshot_and_override_teams_upgrade():
    league = old_league()
    group = {'id': 'g1', 'league_id': 'league-1', 'branding_snapshot': league,
             'branding': {'teams': [{'name': 'Override Team'}]}, 'participants': {}}
    doc = upgrade('group', group)
    assert doc['schema'] == 2
    assert all(t['team_id'] for t in doc['branding_snapshot']['branding']['teams'])
    assert doc['branding']['teams'][0]['team_id']
    assert upgrade('group_session', {'id': 's', 'league_id': 'league-1', 'branding': {}})['schema'] == 2


def test_asset_documents_get_metadata_defaults():
    asset = upgrade('asset', {'id': 'a1', 'league_id': 'l', 'bytes': 10, 'width': 1, 'height': 1, 'sha256': 'x', 'created': 1.0})
    assert asset['schema'] == 2 and asset['kind'] == 'logo' and asset['name'] == ''
    assert asset['license_note'] == '' and asset['created_by'] == 'host'
    kept = upgrade('asset', {'id': 'a2', 'kind': 'sponsor', 'name': 'ACME', 'license_note': 'CC0', 'created_by': 'p1'})
    assert (kept['kind'], kept['name'], kept['license_note'], kept['created_by']) == ('sponsor', 'ACME', 'CC0', 'p1')
    assert set(migrations.ASSET_KINDS) == {'logo', 'sponsor', 'team', 'driver_photo', 'background'}


def test_unknown_types_newer_schemas_and_gaps():
    workspace = {'id': 'w'}
    assert upgrade('workspace', workspace) == {'id': 'w', 'schema': 1}
    assert upgrade('invitation', {'id': 'i'}) == {'id': 'i'}             # types without versions pass through
    future = {'id': 'l', 'schema': 99, 'branding': {}}
    assert upgrade('league', future) == {'id': 'l', 'schema': 99, 'branding': {}}
    assert upgrade('league', 'not a dict') == 'not a dict'
    saved = dict(UPGRADES)
    try:
        del UPGRADES[('asset', 1)]
        with pytest.raises(MissingUpgrade):
            upgrade('asset', {'id': 'a'})
    finally:
        UPGRADES.update(saved)
    assert set(UPGRADES) >= {(kind, 1) for kind, version in CURRENT_SCHEMA.items() if version > 1}


def test_repository_upgrades_on_load_and_writes_back_lazily(tmp_path):
    path = tmp_path / 'db.sqlite'
    repo = insert_raw(path, 'league', 'league-1', '', old_league())
    assert 'schema' not in raw_payload(path, 'league-1')
    loaded = repo.get('league', 'league-1')
    assert loaded['schema'] == 2 and loaded['branding']['teams'][1]['team_id']
    assert repo.docs('league')[0]['schema'] == 2
    assert 'schema' not in raw_payload(path, 'league-1')                  # loading alone does not rewrite
    repo.commit([('league', 'league-1', '', loaded)])                     # next commit persists the upgrade
    stored = raw_payload(path, 'league-1')
    assert stored['schema'] == 2 and stored['branding']['teams'][1]['team_id'] == loaded['branding']['teams'][1]['team_id']
    repo.commit([('invitation', 'i1', 'g', {'id': 'i1'})])
    assert 'schema' not in raw_payload(path, 'i1')                        # only versioned types are stamped


def make_service(tmp_path):
    return GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / 'db.sqlite'), config=SimpleNamespace(root=tmp_path)))


def test_service_loads_an_old_database_and_name_keyed_lookups_still_work(tmp_path):
    path = tmp_path / 'db.sqlite'
    insert_raw(path, 'league', 'league-1', '', old_league())
    s = make_service(tmp_path)
    teams = s.leagues['league-1']['branding']['teams']
    assert [t['name'] for t in teams] == ['Scuderia Apex', 'Vector Racing', 'Vector Racing']
    assert all(t['team_id'] for t in teams)
    saved = asyncio.run(s.league_save(s.leagues['league-1']['branding'], 'league-1'))     # editing still validates
    assert saved['schema'] == 2 and saved['revision'] == 4
    assert [t['team_id'] for t in saved['branding']['teams']] == [t['team_id'] for t in teams]


def test_new_teams_from_the_editor_get_a_team_id_on_save(tmp_path):
    s = make_service(tmp_path)
    league = asyncio.run(s.league_save({'name': 'New', 'teams': [{'id': 'ui-1', 'name': 'Red', 'asset': '', 'color': '#ff0000'},
                                                                  {'name': 'Blue', 'color': '#0000ff'}]}))
    ids = [t['team_id'] for t in league['branding']['teams']]
    assert ids[0] == 'ui-1' and ids[1] and ids[0] != ids[1]
    assert raw_payload(tmp_path / 'db.sqlite', league['id'])['schema'] == 2


def test_upload_records_asset_metadata_and_rejects_unknown_kind(tmp_path):
    from PIL import Image
    s = make_service(tmp_path)
    league = asyncio.run(s.league_save({'name': 'Assets'}))
    buffer = io.BytesIO()
    Image.new('RGBA', (64, 64), (200, 30, 30, 255)).save(buffer, 'PNG')
    assets = Assets(s)
    with pytest.raises(AppError) as info:
        assets.upload(league['id'], buffer.getvalue(), kind='hologram')
    assert info.value.status_code == 422
    asset = assets.upload(league['id'], buffer.getvalue(), kind='sponsor', name='ACME', license_note='Own work', created_by='host')
    stored = s.repo.get('asset', asset['id'])
    assert (stored['kind'], stored['name'], stored['license_note'], stored['created_by'], stored['schema']) == \
        ('sponsor', 'ACME', 'Own work', 'host', 2)
    default = assets.upload(league['id'], buffer.getvalue())
    assert default['kind'] == 'logo'
