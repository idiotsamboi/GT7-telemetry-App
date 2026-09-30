"""Command catalogue: role × command matrix, and an end-to-end race-control flow through `/api/commands`."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import commands_catalog  # noqa: F401  (registers the catalogue)
from backend.app.api import create_app
from backend.app.config import Config
from backend.app.core import commands as cmd
from backend.app.core.commands import COMMANDS
from backend.app.core.errors import ResultCode
from backend.app.core.permissions import CAPABILITIES, Principal

BASE = 'http://127.0.0.1:8000'

# Written independently of core.permissions.ROLES: which roles may run a command needing this capability.
LOCAL_OPS = {'host', 'local'}
EXPECTED_ROLES = {
    'local.admin': LOCAL_OPS, 'settings.write': LOCAL_OPS, 'sessions.manage': LOCAL_OPS, 'sessions.purge': LOCAL_OPS,
    'league.configure': LOCAL_OPS, 'branding.edit': LOCAL_OPS,
    'raceControl.setFlag': LOCAL_OPS, 'raceControl.message': LOCAL_OPS, 'raceControl.steward': LOCAL_OPS,
    'raceControl.session': LOCAL_OPS, 'raceControl.admit': LOCAL_OPS, 'raceControl.zones': LOCAL_OPS,
    'graphics.edit': LOCAL_OPS | {'spectator'}, 'graphics.take': LOCAL_OPS | {'spectator'},
    'graphics.issueOutput': LOCAL_OPS | {'spectator'},
}
ROLES = ('host', 'local', 'driver', 'spectator', 'overlay')


def principal(role):
    return Principal(role, f'{role}-1', 'g1')


def test_catalogue_is_consistent():
    assert len(COMMANDS) >= 50
    for c in COMMANDS:
        assert c.capability in CAPABILITIES, c.id
        assert c.description, c.id
    audited = {c.id for c in COMMANDS if c.audited}
    for must in ('session.end', 'settings.update', 'raceControl.setFlag', 'raceControl.decision', 'graphics.take', 'group.create'):
        assert must in audited
    assert {c.id for c in COMMANDS if c.destructive} >= {'training.restart'}


@pytest.mark.parametrize('command', [c.id for c in COMMANDS])
def test_role_command_matrix(command):
    """Every role × every command: not_authorized exactly when the independent table says so.
    Allowed roles never reach a real handler here (services=None -> a handled failure), so nothing is executed."""
    definition = COMMANDS.require(command)
    allowed = EXPECTED_ROLES[definition.capability]
    for role in ROLES:
        ctx = cmd.Ctx(principal(role), services=None)
        result = asyncio.run(cmd.dispatch(ctx, command, {}, limiter=cmd.RateLimiter()))
        if role in allowed:
            assert result.code != ResultCode.NOT_AUTHORIZED, (command, role)
        else:
            assert result.code == ResultCode.NOT_AUTHORIZED, (command, role)


def test_pending_participants_hold_no_capabilities():
    ctx = cmd.Ctx(Principal('spectator', 's1', status='pending'))
    assert asyncio.run(cmd.dispatch(ctx, 'graphics.take', {'id': 'w'})).code == ResultCode.NOT_AUTHORIZED


# ---- end-to-end race control flow ------------------------------------------------------------------------------
def test_race_control_flow_through_commands_with_audit(tmp_path):
    Config(tmp_path).save({'http_port': 18301, 'hands_free': False, 'speech_enabled': False})
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        assert c.post('/api/pair', json={}).status_code == 200

        def run(command, payload=None):
            return c.post(f'/api/commands/{command}', json=payload or {})

        league = c.post('/api/group/leagues', json={'name': 'Cmd league'}).json()
        created = run('group.create', {'name': 'Race', 'event_name': 'Event', 'league_id': league['id']})
        assert created.status_code == 200 and created.json()['ok'] and created.json()['audit_id']
        assert run('group.create', {'name': ''}).status_code == 422              # service-side validation -> invalid_input
        invite = run('group.invite', {'role': 'driver'}).json()
        assert invite['ok'] and invite['data']['role'] == 'driver' and invite['data']['credential']
        assert run('group.invite', {'role': 'wizard'}).status_code == 422
        assert run('group.session.finalize').status_code == 409                  # AppError 409 -> conflict code
        assert run('group.session.start').json()['ok']
        flag = run('raceControl.setFlag', {'flag': 'yellow', 'scope': 'global', 'reason': 'Debris at turn 3'})
        assert flag.status_code == 200 and flag.json()['data']['flag'] == 'yellow'
        assert run('raceControl.setFlag', {'flag': 'invented'}).status_code == 422
        cancelled = run('raceControl.cancelFlag', {'id': flag.json()['data']['id']})
        assert cancelled.status_code == 200
        assert run('raceControl.cancelFlag', {'id': 'nope'}).status_code == 404
        msg = run('raceControl.message', {'text': 'Box this lap', 'scope': 'all'})
        assert msg.status_code == 422 and 'No matching entries' in msg.json()['message']       # nobody has joined yet
        assert run('raceControl.message', {'text': ''}).status_code == 422
        assert run('group.lock', {'locked': True}).json()['ok']
        assert c.get('/api/group/state').json()['group']['join_locked'] is True
        assert run('group.session.end').json()['ok']
        rows = c.get('/api/audit?limit=200').json()
        commands_logged = [r['command_id'] for r in rows]
        for expected in ('group.create', 'group.invite', 'group.session.start', 'raceControl.setFlag', 'group.lock', 'group.session.end'):
            assert expected in commands_logged, expected
        failed = [r for r in rows if r['command_id'] == 'raceControl.setFlag' and r['result_code'] == 'invalid_input']
        assert failed                                                            # refusals are audited too
        assert all('payload' not in r for r in rows) and invite['data']['credential'] not in str(rows)   # hash only; no secrets


def test_graphics_take_and_credential_commands(tmp_path):
    Config(tmp_path).save({'http_port': 18302, 'hands_free': False, 'speech_enabled': False})
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        c.post('/api/pair', json={})
        league = c.post('/api/group/leagues', json={'name': 'L'}).json()
        c.post('/api/group/create', json={'name': 'R', 'event_name': 'E', 'league_id': league['id']})
        saved = c.post('/api/commands/graphics.saveDraft', json={'name': 'Main'})
        assert saved.status_code == 200, saved.text
        wid = saved.json()['data']['id']
        assert c.post('/api/commands/graphics.take', json={'id': wid}).json()['ok']
        cred = c.post('/api/commands/graphics.credential.issue', json={'id': wid}).json()
        assert cred['ok'] and cred['data']['credential']
        assert c.post('/api/commands/graphics.take', json={'id': 'missing'}).status_code == 404
        assert c.post('/api/commands/graphics.clearProgram', json={'id': wid}).json()['ok']
        time.sleep(.2)
        rows = c.get('/api/audit?limit=100').json()
        logged = {r['command_id'] for r in rows}
        assert {'graphics.take', 'graphics.credential.issue', 'graphics.clearProgram'} <= logged
        assert cred['data']['credential'] not in str(rows)                     # the issued secret is never written to the audit log


def test_session_commands_retention_index_and_lap_series(tmp_path):
    Config(tmp_path).save({'http_port': 18303, 'hands_free': False, 'speech_enabled': False})
    with TestClient(create_app(tmp_path), base_url=BASE) as c:
        c.post('/api/pair', json={})
        c.post('/api/control', json={'action': 'demo'})
        time.sleep(1.0)
        sid = c.get('/api/state').json()['session_id']
        assert sid
        run = lambda cid, p=None: c.post(f'/api/commands/{cid}', json=p or {})
        assert run('session.end').json()['ok']
        index = c.get('/api/sessions-index?limit=5').json()
        assert index['items'][0]['id'] == sid if 'items' in index else True
        assert run('sessions.protect', {'id': sid, 'protected': True}).json()['ok']
        assert run('sessions.archive', {'id': sid}).status_code == 409            # protected sessions cannot be archived
        assert run('sessions.protect', {'id': sid, 'protected': False}).json()['ok']
        assert run('sessions.update_meta', {'id': sid, 'notes': 'kerb strike', 'tags': ['a']}).json()['ok']
        assert c.get(f'/api/sessions/{sid}').json()['meta']['notes'] == 'kerb strike'
        assert run('sessions.archive', {'id': sid}).json()['ok']
        assert run('sessions.purge', {'id': sid, 'confirmation': 'DELETE ARCHIVED SESSION'}).status_code == 422   # no confirm:true
        assert run('sessions.purge', {'id': sid, 'confirmation': 'nope', 'confirm': True}).status_code == 422
        assert run('sessions.purge', {'id': sid, 'confirmation': 'DELETE ARCHIVED SESSION', 'confirm': True}).json()['ok']
        assert c.get(f'/api/sessions/{sid}').status_code == 404
        assert run('sessions.update_meta', {'id': 'missing'}).status_code == 404
        assert run('sessions.retention').json()['data']['archived'] == 0
        logged = {r['command_id'] for r in c.get('/api/audit?limit=200').json()}
        assert {'sessions.protect', 'sessions.purge', 'sessions.archive'} <= logged
        assert c.get('/api/export-formats').status_code == 200
