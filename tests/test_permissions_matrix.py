"""Role x action -> allow/deny matrix for the group API.

Written against the behaviour that existed before the service delegated to core.permissions.can();
it must stay green through the refactor (identical allow/deny AND status codes).
"""
import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.core import permissions
from backend.app.core.errors import AppError
from backend.app.group.public import public_app
from backend.app.group.service import GroupService

ORIGIN = 'http://testserver'


def make_service(tmp_path):
    return GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / 'db.sqlite'),
                                        config=SimpleNamespace(root=tmp_path)))


class World:
    """One group with: driver, second driver, pending driver, owner spectator, shared spectator,
    other spectator, pending spectator; and a workspace owned by `owner` and shared with `shared`."""

    def __init__(self, tmp_path):
        self.s = make_service(tmp_path)
        asyncio.run(self.build())

    async def join(self, role, name, sharing=None):
        invite = await self.s.invite(role)
        body = {'credential': invite['credential'], 'identity': {'display_name': name, 'number': name[-1]}}
        if sharing:
            body['accepted_sharing'] = sharing
        return await self.s.join(body)

    async def build(self):
        s = self.s
        league = await s.league_save({'name': 'Matrix'})
        self.group = await s.create_group({'name': 'M', 'event_name': 'E', 'league_id': league['id'], 'approval': False})
        self.joined = {}
        for name, role in [('driver', 'driver'), ('driver2', 'driver'), ('owner', 'spectator'),
                           ('shared', 'spectator'), ('other', 'spectator')]:
            self.joined[name] = await self.join(role, name)
        await s.configure({'approval': True})
        for name, role in [('pdriver', 'driver'), ('pspec', 'spectator')]:
            self.joined[name] = await self.join(role, name)
        self.p = {k: await s.authenticate(v['token'], ('driver', 'spectator')) for k, v in self.joined.items()}
        self.ws = await s.save_workspace({'name': 'WS'}, principal=self.p['owner'])
        await s.share_workspace(self.ws['id'], [self.joined['shared']['participant']['id']])
        self.overlay = await s.authenticate((await s.overlay_token(self.ws['id']))['credential'], ('overlay',))
        other_ws = await s.save_workspace({'name': 'Other WS'}, principal=self.p['other'])
        self.other_overlay = await s.authenticate((await s.overlay_token(other_ws['id']))['credential'], ('overlay',))
        self.other_ws = other_ws

    def packet(self, who, sequence=1):
        j = self.joined[who]['participant']
        g = self.s.active()
        return {'version': 1, 'group_id': g['id'], 'session_id': g['session_id'], 'participant_id': j['id'],
                'entry_id': j['entry_id'] or 'none', 'boot_id': 'b', 'sequence': sequence, 'source_mono': 1,
                'source_utc': time.time(), 'provenance': 'live', 'layout_id': '', 'local_session_id': 'l',
                'values': {'car_id': 1, 'lap': None, 'flags': 1}}


@pytest.fixture()
def world(tmp_path):
    return World(tmp_path)


def status_of(call) -> int:
    """200 when the call succeeds, else the AppError status."""
    try:
        result = call()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        return 200
    except AppError as error:
        return error.status_code


DRIVER_ONLY = {'driver': 200, 'driver2': 200, 'pdriver': 403, 'owner': 403, 'shared': 403, 'other': 403, 'pspec': 403}


def test_publish_telemetry_matrix(world):
    # Packet identity binds to the caller: send each caller's own packet so only the role check differs.
    got = {who: status_of(lambda who=who: world.s.telemetry(world.p[who], world.packet(who)))
           for who in world.p}
    assert got == {**DRIVER_ONLY, 'pdriver': 403}


def test_lap_event_matrix(world):
    g = world.s.active()
    body = {'session_id': g['session_id'], 'id': 'lap-1', 'duration_ms': 90000, 'number': 1, 'comparable': True}
    got = {who: status_of(lambda who=who: world.s.lap_event(world.p[who], {**body, 'id': f'lap-{who}'}))
           for who in world.p}
    assert got == DRIVER_ONLY


def test_driver_response_matrix(world):
    got = {who: status_of(lambda who=who: world.s.response(world.p[who], {'action': 'pit_intent'}))
           for who in world.p}
    assert got == DRIVER_ONLY


# who -> status for actions on the workspace owned by `owner` and shared with `shared`
WORKSPACE_ACCESS = {'owner': 200, 'shared': 200, 'other': 403, 'driver': 403, 'pspec': 403}


def test_workspace_edit_matrix(world):
    wid = world.ws['id']
    got = {who: status_of(lambda who=who: world.s.save_workspace({'name': 'edit ' + who}, wid, world.p[who]))
           for who in WORKSPACE_ACCESS}
    assert got == WORKSPACE_ACCESS


def test_workspace_take_matrix(world):
    wid = world.ws['id']
    got = {who: status_of(lambda who=who: world.s.take(wid, world.p[who])) for who in WORKSPACE_ACCESS}
    assert got == WORKSPACE_ACCESS


def test_workspace_overlay_credential_matrix(world):
    wid = world.ws['id']
    got = {who: status_of(lambda who=who: world.s.overlay_token(wid, world.p[who])) for who in WORKSPACE_ACCESS}
    assert got == WORKSPACE_ACCESS


def test_focus_battle_matrix(world):
    # Allowed callers get past the access check and hit "battle not found" (404); denied get 403.
    wid = world.ws['id']
    got = {who: status_of(lambda who=who: world.s.focus_battle('nope', wid, False, True, world.p[who]))
           for who in WORKSPACE_ACCESS}
    assert got == {'owner': 404, 'shared': 404, 'other': 403, 'driver': 403, 'pspec': 403}


def test_create_workspace_matrix(world):
    got = {who: status_of(lambda who=who: world.s.save_workspace({'name': 'new'}, principal=world.p[who]))
           for who in world.p}
    assert got == {'driver': 403, 'driver2': 403, 'pdriver': 403, 'owner': 200, 'shared': 200, 'other': 200, 'pspec': 403}


def test_host_local_admin_has_no_workspace_restrictions(world):
    s, wid = world.s, world.ws['id']
    assert status_of(lambda: s.save_workspace({'name': 'host edit'}, wid)) == 200
    assert status_of(lambda: s.take(wid)) == 200
    assert status_of(lambda: s.overlay_token(wid)) == 200
    assert status_of(lambda: s.clear_program(wid)) == 200
    assert status_of(lambda: s.workspace(wid)) == 200


def test_workspace_from_another_group_is_denied(world):
    other = dict(world.p['owner'], group_id='another-group')
    assert status_of(lambda: world.s.workspace(world.ws['id'], other)) == 403


def test_traffic_view_all_is_a_conditional_driver_grant(world):
    s = world.s
    g0 = s.active()
    raw = s.raw_snapshot(g0)
    for who in ('driver', 'owner'):
        assert s.filter_snapshot(raw, g0, world.p[who])['traffic'] is None
    asyncio.run(s.configure({'share_traffic_with_drivers': True}))
    g1 = s.active()
    raw = s.raw_snapshot(g1)
    assert isinstance(s.filter_snapshot(raw, g1, world.p['driver'])['traffic'], list)
    assert s.filter_snapshot(raw, g1, world.p['owner'])['traffic'] is None   # spectators never get it
    assert s.filter_snapshot(raw, g1, None)['traffic'] is None               # host view has no traffic block


def test_pending_participants_see_no_state(world):
    for who in ('pdriver', 'pspec'):
        assert world.s.public_state(world.p[who]) == {'admission': 'pending', 'entries': []}


@pytest.fixture()
def client(world):
    with TestClient(public_app(world.s, {ORIGIN}), base_url=ORIGIN) as c:
        yield c


def bearer(world, who):
    return {'authorization': 'Bearer ' + world.joined[who]['token'], 'origin': ORIGIN}


def test_public_workspace_listing_matrix(world, client):
    got = {who: client.get('/group-api/workspaces', headers=bearer(world, who)).status_code for who in world.p}
    assert got == {'driver': 403, 'driver2': 403, 'pdriver': 403, 'owner': 200, 'shared': 200, 'other': 200, 'pspec': 403}
    listing = client.get('/group-api/workspaces', headers=bearer(world, 'shared')).json()
    assert [w['id'] for w in listing] == [world.ws['id']]


def test_overlay_ticket_is_scoped_to_its_own_workspace(world, client):
    def ticket(principal_token, workspace):
        return client.post('/group-api/ticket', json={'overlay': True, 'workspace_id': workspace},
                           headers={'authorization': 'Bearer ' + principal_token, 'origin': ORIGIN}).status_code
    own = world.s.repo.token('overlay', world.ws['id'], world.group['id'], 60)
    assert ticket(own, world.ws['id']) == 200
    assert ticket(own, world.other_ws['id']) == 403


def test_spectator_ticket_requires_workspace_access(world, client):
    def ticket(who, workspace):
        return client.post('/group-api/ticket', json={'workspace_id': workspace}, headers=bearer(world, who)).status_code
    assert ticket('owner', world.ws['id']) == 200
    assert ticket('shared', world.ws['id']) == 200
    assert ticket('other', world.ws['id']) == 403


# The static role table itself (roles are data in core.permissions).
@pytest.mark.parametrize('role,capability,expected', [
    ('driver', 'telemetry.publishOwn', True), ('driver', 'driver.respond', True),
    ('driver', 'graphics.edit', False), ('driver', 'telemetry.viewAll', False),
    ('spectator', 'graphics.take', True), ('spectator', 'telemetry.publishOwn', False),
    ('spectator', 'raceControl.setFlag', False), ('overlay', 'overlay.read', True),
    ('overlay', 'graphics.view', False), ('host', 'raceControl.steward', True),
    ('host', 'graphics.issueOutput', True), ('local', 'local.admin', True),
])
def test_static_role_table(role, capability, expected):
    principal = permissions.Principal(kind=role, subject='x', group_id='g')
    assert permissions.can(principal, capability) is expected
