"""Command catalogue: existing behaviour exposed as commands (no new features).

Handlers receive `ctx.services` = the Runtime (composition root). The legacy routes (`/api/control`, ...)
remain as thin shims over the same operation functions (`control.py`, `operations.py`), so the behaviour has one
implementation. Only `/api/commands/{id}` adds capability checks, rate limits, destructive confirmation and audit rows;
the shims keep their old contracts (see docs/architecture/TECH_DEBT.md).

Add a command: define a payload model, write a handler, call `register(CommandDef(...))` below,
add a test in tests/test_commands.py and run `python scripts/gen-contracts.py`.
"""
import asyncio

from pydantic import BaseModel, ConfigDict, Field

from . import operations as ops
from .config import Settings
from .control import control_action
from .core.commands import CommandDef, CommandResult, Empty, register
from .core.errors import AppError, ResultCode

OK = ResultCode.OK


def _ok(message: str = '', data=None) -> CommandResult:
    return CommandResult(OK, message, data=data if isinstance(data, dict) or data is None else {'result': data})


class Value(BaseModel):
    value: str | float | None = None


class Layout(BaseModel):
    layout_id: str = Field(max_length=16)


class Text(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class Milliseconds(BaseModel):
    target_ms: int = Field(gt=1000, le=3600000)


class ReplayStart(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


class SeekPayload(BaseModel):
    mono: float = 0


class SpeedPayload(BaseModel):
    speed: float = Field(1, ge=.25, le=16)


class Enabled(BaseModel):
    enabled: bool = True


class TrackImport(BaseModel):
    layout_id: str = Field(max_length=16)
    points: list = Field(max_length=4096)


class TrackConfirm(BaseModel):
    layout_id: str = Field(max_length=16)
    candidate_id: str = Field(max_length=64)


class TrackRestore(BaseModel):
    layout_id: str = Field(max_length=16)
    revision: str = Field(max_length=64)


def _control(action: str, *, payload_value=None):
    async def handler(ctx, body):
        value = payload_value(body) if payload_value else None
        return _ok('', await control_action(ctx.services, action, value))
    return handler


def _intent(action: str):
    async def handler(ctx, body):
        return _ok('', ctx.services.execute(action, None))
    return handler


def _def(id, capability, schema, handler, description, **kw):
    register(CommandDef(id, capability, schema, handler, description=description, **kw))


LOCAL = 'local.admin'

# ---- session ----------------------------------------------------------------------------------------
_def('session.start', LOCAL, Empty, _control('start'), 'Allow recording to start again after a manual end')
_def('session.end', LOCAL, Empty, _control('end'), 'End the current session and produce its report', audited=True)
_def('session.mark_incident', LOCAL, Text, lambda ctx, b: _ok('', ctx.services.execute('incident', b.text)), 'Save an incident marker')
_def('session.set_reference', LOCAL, Empty, _intent('reference'), 'Queue the last clean lap as the live reference')
_def('session.set_target', LOCAL, Milliseconds, lambda ctx, b: _ok('', ctx.services.execute('target', b.target_ms)), 'Set the target lap time')
_def('session.box', LOCAL, Empty, _intent('box'), 'Mark pit intent')
_def('session.unbox', LOCAL, Empty, _intent('unbox'), 'Clear pit intent')

# ---- source -----------------------------------------------------------------------------------------
_def('source.live', LOCAL, Empty, _control('live'), 'Switch to live PS5 telemetry')
_def('source.demo', LOCAL, Empty, _control('demo'), 'Switch to the synthetic demo source')
_def('source.replay', LOCAL, ReplayStart, _control('replay', payload_value=lambda b: b.session_id), 'Replay a recorded session')
_def('source.replay_pause', LOCAL, Empty, _control('replay_pause'), 'Pause/resume replay')
_def('source.replay_seek', LOCAL, SeekPayload, _control('replay_seek', payload_value=lambda b: b.mono), 'Seek within the replay')
_def('source.replay_speed', LOCAL, SpeedPayload, _control('replay_speed', payload_value=lambda b: b.speed), 'Set replay speed')

# ---- audio / engineer ---------------------------------------------------------------------------------
_def('audio.mute', LOCAL, Empty, _control('mute'), 'Hard-mute the engineer')
_def('audio.resume', LOCAL, Empty, _control('resume'), 'Resume the engineer')
_def('audio.ptt_start', LOCAL, Empty, _control('ptt_start'), 'Push-to-talk start')
_def('audio.ptt_stop', LOCAL, Empty, _control('ptt_stop'), 'Push-to-talk stop')
_def('audio.hands_free', LOCAL, Enabled, lambda ctx, b: _control('listen_on' if b.enabled else 'listen_off')(ctx, b), 'Enable/disable hands-free listening')
_def('audio.speaker_test', LOCAL, Empty, _control('speaker_test'), 'Play a radio check through the selected output', rate=(6, 60))
_def('audio.mic_test', LOCAL, Empty, _control('audio_test'), 'Run the microphone/speaker probe', rate=(6, 60))


async def _engineer_ask(ctx, body):
    response = ctx.services.engineer.ask(body.text)
    # `answer`/`variation` keep the legacy /api/command shape for existing callers
    return _ok('', {**response.to_public(), 'answer': response.message})


_def('engineer.ask', LOCAL, Text, _engineer_ask, 'Ask the engineer (text intent)', rate=(60, 60))
_def('engineer.ai_brief', LOCAL, Empty, _control('ai_briefing'), 'Refresh the local AI briefing')

# ---- tracks / training ---------------------------------------------------------------------------------


async def _track_select(ctx, b):
    return _ok('', await ops.track_select(ctx.services, b.layout_id))


async def _track_confirm(ctx, b):
    return _ok('', await ops.track_confirm(ctx.services, b.layout_id, b.candidate_id))


async def _track_restore(ctx, b):
    return _ok('', await ops.track_restore(ctx.services, b.layout_id, b.revision))


async def _track_import(ctx, b):
    return _ok('', await ops.track_import(ctx.services, b.layout_id, b.points))


_def('track.select', LOCAL, Layout, _track_select, 'Select the track layout')
_def('track.confirm', LOCAL, TrackConfirm, _track_confirm, 'Confirm a captured track map candidate')
_def('track.restore', LOCAL, TrackRestore, _track_restore, 'Restore an earlier track map revision', audited=True)
_def('track.import', LOCAL, TrackImport, _track_import, 'Import track map points', audited=True)
_def('training.start', LOCAL, Layout, lambda ctx, b: _ok('', ops.training_start(ctx.services, b.layout_id)), 'Start training capture for a layout')
_def('training.stop', LOCAL, Empty, lambda ctx, b: _ok('', ops.training_stop(ctx.services)), 'Stop training capture')
_def('training.retry', LOCAL, Empty, lambda ctx, b: _ok('', ops.training_retry_lap(ctx.services)), 'Discard the current training lap')
_def('training.restart', LOCAL, Layout, lambda ctx, b: _ok('', ops.training_restart(ctx.services, b.layout_id)),
     'Clear saved captures for a layout', destructive=True, audited=True)


# ---- settings / recovery -----------------------------------------------------------------------------------
async def _settings_update(ctx, body):
    merged = ctx.services.settings.model_dump()
    for key, value in body.model_dump(exclude_unset=True).items():
        merged[key] = {**merged[key], **value} if isinstance(value, dict) and isinstance(merged.get(key), dict) else value   # nested `units` etc. merge
    settings = Settings.model_validate(merged)
    return _ok('Settings saved', ops.settings_update(ctx.services, settings))


def _recovery(action):
    async def handler(ctx, body):
        origins = getattr(ctx.services, 'local_origins', set())
        return _ok('Recovery applied', await ops.recovery_action(ctx.services, action, origins))
    return handler


_def('settings.update', 'settings.write', Settings, _settings_update, 'Update settings (only the fields sent change)', audited=True)
for _action in ('live', 'display', 'connection', 'audio'):
    _def(f'recovery.{_action}', LOCAL, Empty, _recovery(_action), f'Recovery: {_action}', audited=True)
_def('safe_mode.leave', LOCAL, Empty, _control('leave_safe_mode'), 'Leave safe mode (enables heartbeat, microphone, local AI)', audited=True)


# ---- group / race control / broadcast ------------------------------------------------------------------------
# Handlers call GroupService methods that already validate their own bodies (Pydantic) and raise AppError.
# Group commands are audited: dispatch() writes audit_log rows; group_events stays the domain event stream (ADR 0007).
class Body(BaseModel):
    """Pass-through payload: the GroupService validates the fields itself."""
    model_config = ConfigDict(extra='allow')


class Identified(BaseModel):
    id: str = Field(min_length=1, max_length=100)


class Invite(BaseModel):
    role: str
    expires: int = 3600


class Admission(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=20)


class Locked(BaseModel):
    locked: bool = True


class WorkspaceSave(BaseModel):
    model_config = ConfigDict(extra='allow')
    workspace_id: str | None = None


class LeagueSave(BaseModel):
    model_config = ConfigDict(extra='allow')
    league_id: str | None = None


def _group(ctx):
    return ctx.services.group


def _svc(method):
    """Handler for a GroupService coroutine taking the raw body."""
    async def handler(ctx, body):
        return _ok('', await getattr(_group(ctx), method)(body.model_dump()))
    return handler


async def _group_invite(ctx, b):
    return _ok('', await _group(ctx).invite(b.role, b.expires))


async def _group_admit(ctx, b):
    return _ok('', await _group(ctx).admit(b.id, b.status))


async def _group_remove(ctx, b):
    return _ok('', await _group(ctx).admit(b.id, 'removed'))


async def _group_lock(ctx, b):
    return _ok('', await _group(ctx).configure({'join_locked': b.locked}))


def _session(action):
    async def handler(ctx, body):
        return _ok('', await _group(ctx).session_action(action))
    return handler


async def _save_workspace(ctx, b):
    payload = b.model_dump()
    wid = payload.pop('workspace_id', None)
    return _ok('', await _group(ctx).save_workspace(payload, wid))


async def _league_update(ctx, b):
    payload = b.model_dump()
    lid = payload.pop('league_id', None)
    return _ok('', await _group(ctx).league_save(payload, lid))


async def _take(ctx, b):
    return _ok('', await _group(ctx).take(b.id))


async def _clear(ctx, b):
    return _ok('', await _group(ctx).clear_program(b.id))


async def _credential(ctx, b):
    return _ok('', await _group(ctx).overlay_token(b.id))


async def _cancel_flag(ctx, b):
    return _ok('', await _group(ctx).cancel_instruction(b.id))


_def('group.create', 'league.configure', Body, _svc('create_group'), 'Create a group/event', audited=True)
_def('group.configure', 'league.configure', Body, _svc('configure'), 'Configure the group (partial update)', audited=True)
_def('group.invite', 'raceControl.admit', Invite, _group_invite, 'Issue an invitation credential', audited=True, rate=(30, 60))
_def('group.admit', 'raceControl.admit', Admission, _group_admit, 'Admit or update a participant status', audited=True)
_def('group.remove', 'raceControl.admit', Identified, _group_remove, 'Remove a participant', audited=True)
_def('group.lock', 'raceControl.admit', Locked, _group_lock, 'Lock/unlock joining', audited=True)
for _action in ('start', 'end', 'finalize', 'close'):
    _def(f'group.session.{_action}', 'raceControl.session', Empty, _session(_action), f'Group session: {_action}', audited=True)
_def('raceControl.setFlag', 'raceControl.setFlag', Body, _svc('instruction'), 'Issue a flag/instruction', audited=True, rate=(60, 60))
_def('raceControl.cancelFlag', 'raceControl.setFlag', Identified, _cancel_flag, 'Cancel an instruction (a new, labelled action)', audited=True)
_def('raceControl.message', 'raceControl.message', Body, _svc('message'), 'Send a race control message', audited=True, rate=(60, 60))
_def('raceControl.decision', 'raceControl.steward', Body, _svc('decision'), 'Publish a steward decision (no undo; supersede instead)', audited=True)
_def('graphics.saveDraft', 'graphics.edit', WorkspaceSave, _save_workspace, 'Save a workspace draft')
_def('graphics.take', 'graphics.take', Identified, _take, 'Take a draft to program', audited=True)
_def('graphics.clearProgram', 'graphics.take', Identified, _clear, 'Clear the program output', audited=True)
_def('graphics.credential.issue', 'graphics.issueOutput', Identified, _credential, 'Issue an overlay credential', audited=True)
_def('branding.update', 'branding.edit', LeagueSave, _league_update, 'Update league branding', audited=True)


# ---- alerts ---------------------------------------------------------------------------------------------------
class AckAlert(BaseModel):
    id: str | None = None      # omit to acknowledge everything


async def _ack_alert(ctx, b):
    center = ctx.services.alerts
    if b.id is None:
        return _ok('', {'acknowledged': center.acknowledge_all()})
    if not center.acknowledge(b.id):
        raise AppError.from_code(ResultCode.NOT_FOUND, 'Alert not found')
    return _ok('', {'acknowledged': 1})


_def('alerts.acknowledge', LOCAL, AckAlert, _ack_alert, 'Acknowledge one alert, or all when no id is given')


# ---- sessions (storage) -----------------------------------------------------------------------------------------------
class SessionMeta(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    notes: str = Field('', max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    protected: bool = False
    track: str | None = Field(None, max_length=120)
    layout: str | None = Field(None, max_length=120)
    direction: str | None = None
    reference_lap: str | None = None


class SessionProtect(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    protected: bool = True


class SessionArchive(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    archived: bool = True


class SessionPurge(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    confirmation: str                                # the typed phrase (ops.PURGE_CONFIRMATION), in addition to `confirm: true`


async def _sessions_update_meta(ctx, b):
    return _ok('', await ops.session_update_meta(ctx.services, b.id, notes=b.notes, tags=b.tags, protected=b.protected, track=b.track,
                                                 layout=b.layout, direction=b.direction, reference_lap=b.reference_lap))


async def _sessions_protect(ctx, b):
    return _ok('', await ops.session_protect(ctx.services, b.id, b.protected))


async def _sessions_archive(ctx, b):
    return _ok('', await ops.session_set_archived(ctx.services, b.id, b.archived))


async def _sessions_purge(ctx, b):
    if b.confirmation != ops.PURGE_CONFIRMATION:
        raise AppError.from_code(ResultCode.INVALID_INPUT, 'Type the confirmation phrase to purge')
    return _ok('', await ops.session_purge(ctx.services, b.id))


async def _retention_apply(ctx, b):
    return _ok('', await ops.retention_apply(ctx.services))


_def('sessions.update_meta', 'sessions.manage', SessionMeta, _sessions_update_meta, 'Edit session notes, tags, track/layout, reference lap', audited=True)
_def('sessions.protect', 'sessions.manage', SessionProtect, _sessions_protect, 'Protect/unprotect a session from retention and purge', audited=True)
_def('sessions.archive', 'sessions.manage', SessionArchive, _sessions_archive, 'Archive (recoverable) or restore a session', audited=True)
_def('sessions.retention', 'sessions.manage', Empty, _retention_apply, 'Archive every session the retention policy selects (never purges)', audited=True)
_def('sessions.purge', 'sessions.purge', SessionPurge, _sessions_purge, 'Permanently delete an archived, unprotected session', audited=True, destructive=True)


# ---- group: revoke credentials, focus a battle on a workspace -------------------------------------------------------------
class Revoke(BaseModel):
    kind: str = Field(min_length=1, max_length=30)
    id: str = Field(min_length=1, max_length=100)


class FocusBattle(BaseModel):
    id: str = Field(min_length=1, max_length=100)              # battle id
    workspace_id: str | None = None
    take: bool = False
    ensure_graphics: bool = True


async def _group_revoke(ctx, b):
    if b.kind not in ('invite_driver', 'invite_spectator', 'overlay'):
        raise AppError.from_code(ResultCode.INVALID_INPUT, 'Remove participants through admission controls')
    await asyncio.to_thread(_group(ctx).repo.revoke, b.id, b.kind)
    return _ok('', {'revoked': True})


async def _focus_battle(ctx, b):
    return _ok('', await _group(ctx).focus_battle(b.id, b.workspace_id, b.take, b.ensure_graphics))


_def('group.revoke', 'raceControl.admit', Revoke, _group_revoke, 'Revoke an invitation or overlay credential', audited=True)
_def('graphics.focusBattle', 'graphics.take', FocusBattle, _focus_battle, 'Focus a battle on a workspace (optionally take it live)', audited=True)
