"""Operations shared by the legacy HTTP routes and the command catalogue.

Extracted verbatim from api.py so each behaviour has exactly one implementation. They take the Runtime
(composition root) and raise core.errors.AppError; adapters map errors to HTTP.
"""
import asyncio
import json
import socket
from datetime import datetime, timedelta, timezone

from .config import Settings
from .core.errors import AppError
from .tracks import LAYOUTS

TRAINING_EXCLUDED_VENUES = {'28'}  # Special Stage Route X: excluded from training mode.
TRAINING_LAYOUTS = {k: v for k, v in LAYOUTS.items() if v['venue_id'] not in TRAINING_EXCLUDED_VENUES}
SETTINGS_NOTE = ('Console/UDP changes reconnect immediately. HTTP listen/origin changes need restart; '
                 'audio device changes need microphone reinitialization.')


# ---- settings -----------------------------------------------------------------------------------------
def settings_update(runtime, settings: Settings) -> dict:
    if str(settings.http_host) != str(runtime.settings.http_host) or settings.http_port != runtime.settings.http_port:
        family = socket.AF_INET6 if ':' in str(settings.http_host) else socket.AF_INET
        try:
            # Reject a nonlocal bind or occupied replacement port before persisting it.
            ports = (settings.http_port, settings.http_port + 1 if settings.http_port < 65535 else 65534)
            for port in ports:
                with socket.socket(family, socket.SOCK_STREAM) as probe:
                    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    probe.bind((str(settings.http_host), port))
        except OSError:
            raise AppError.from_status(422, 'HTTP address or port is unavailable on this computer. Existing settings are unchanged.')
    if settings.track_id:
        layout = LAYOUTS.get(settings.track_id)
        if not layout:
            raise AppError.from_status(422, 'Unknown GT7 layout')
        settings.track = layout['track']
        settings.layout = layout['name']
        settings.direction = layout['direction']
    runtime.update_settings(settings.model_dump())
    return {'settings': settings.model_dump(mode='json'), 'restart_required': SETTINGS_NOTE}


# ---- tracks -------------------------------------------------------------------------------------------
async def track_import(runtime, layout_id: str, points: list):
    try:
        await asyncio.to_thread(runtime.track_map.import_map, layout_id, points)
    except ValueError as error:
        raise AppError.from_status(422, str(error))
    except OSError:
        raise AppError.from_status(503, 'Map write failed; previous map is retained')
    return runtime.track_map.snapshot()


async def track_select(runtime, layout_id: str):
    try:
        runtime.track_map.select(layout_id, force=True)
    except ValueError as error:
        raise AppError.from_status(422, str(error))
    runtime.track.select(layout_id)
    await asyncio.to_thread(runtime.track_map.alignment, layout_id)
    return runtime.track_map.snapshot()


async def track_confirm(runtime, layout_id: str, candidate_id: str):
    try:
        return await asyncio.to_thread(runtime.track_map.confirm, candidate_id, layout_id)
    except ValueError as error:
        raise AppError.from_status(422, str(error))
    except OSError:
        raise AppError.from_status(503, 'Map could not be saved; previous revision remains available')


async def track_restore(runtime, layout_id: str, revision: str):
    try:
        return await asyncio.to_thread(runtime.track_map.restore, layout_id, revision)
    except ValueError as error:
        raise AppError.from_status(422, str(error))
    except OSError:
        raise AppError.from_status(503, 'Map could not be restored; previous revision remains available')


# ---- training -----------------------------------------------------------------------------------------
def training_start(runtime, layout_id: str):
    layout = TRAINING_LAYOUTS.get(layout_id)
    if not layout:
        raise AppError.from_status(422, 'Unknown GT7 layout')
    runtime.training.start(layout_id, layout)
    return runtime.training.status()


def training_stop(runtime):
    runtime.training.stop()
    return runtime.training.status()


def training_retry_lap(runtime):
    runtime.training.discard_current_lap()
    return runtime.training.status()


def training_restart(runtime, layout_id: str):
    if layout_id not in TRAINING_LAYOUTS:
        raise AppError.from_status(422, 'Unknown GT7 layout')
    if not runtime.training.restart_layout(layout_id):
        raise AppError.from_status(409, 'Stop training this layout before clearing its captures')
    return runtime.training.list_progress(TRAINING_LAYOUTS)


# ---- recovery -----------------------------------------------------------------------------------------
async def recovery_action(runtime, action: str, local_origins: set[str]) -> dict:
    values = runtime.settings.model_dump()
    if action == 'live':
        runtime.host_only = False
        if hasattr(runtime.group, 'hosting'):
            runtime.group.hosting['host_only'] = False
        runtime.group.replay = None
        runtime.switch('live')
    elif action == 'display':
        runtime.update_settings({**values, 'minimal': False, 'ui_hz': 12})
    elif action == 'connection':
        runtime.update_settings({**values, 'udp_bind': '0.0.0.0', 'udp_port': 33740, 'remote_port': 33739, 'heartbeat': 1,
                                 'variant': 'A', 'allowed_origins': sorted(set(values['allowed_origins']) | local_origins)})
    elif action == 'audio':
        runtime.speaker.stop()
        runtime.scheduler.cancel('Audio recovery')
        await asyncio.to_thread(runtime.mic.close)
        runtime.update_settings({**values, 'input_device': None, 'output_device': None, 'speech_enabled': True,
                                 'hard_mute': False, 'voice_volume': 80, 'hands_free': False})
    else:
        raise AppError.from_status(422, 'Unknown recovery action')
    return {'ok': True, 'action': action, 'message': 'Recovery applied. Recordings, maps, leagues and credentials are retained.',
            'settings': runtime.settings.model_dump(mode='json')}


# ---- sessions -----------------------------------------------------------------------------------------------------
PURGE_CONFIRMATION = 'DELETE ARCHIVED SESSION'


async def _detail_or_404(runtime, sid: str) -> dict:
    detail = await asyncio.to_thread(runtime.store.detail, sid)
    if not detail:
        raise AppError.from_status(404, 'Unknown session')
    return detail


async def session_update_meta(runtime, sid: str, *, notes: str = '', tags: list | None = None, protected: bool = False,
                              track=None, layout=None, direction=None, reference_lap=None) -> dict:
    detail = await _detail_or_404(runtime, sid)
    meta = {**detail['meta'], 'notes': notes, 'tags': [t[:60] for t in (tags or [])]}
    for key, value in (('track', track), ('layout', layout), ('direction', direction), ('reference_lap', reference_lap)):
        if value is not None:
            meta[key] = value
    if reference_lap and not any(l['id'] == reference_lap and l['comparable'] for l in detail['laps']):
        raise AppError.from_status(422, 'Reference must be a complete comparable lap')
    if sid == runtime.sessions.id:
        runtime.sessions.meta = meta
    if not runtime.store.put('metadata', (json.dumps(meta), int(protected), sid)):
        raise AppError.from_status(503, 'Storage queue full')
    await asyncio.to_thread(runtime.store.flush)
    return {'ok': True}


async def session_protect(runtime, sid: str, protected: bool) -> dict:
    """Toggle only the protected flag; notes, tags and the rest of the metadata are kept."""
    detail = await _detail_or_404(runtime, sid)
    if not runtime.store.put('metadata', (json.dumps(detail['meta']), int(protected), sid)):
        raise AppError.from_status(503, 'Storage queue full')
    await asyncio.to_thread(runtime.store.flush)
    return {'ok': True, 'protected': protected}


async def session_set_archived(runtime, sid: str, archived: bool = True) -> dict:
    detail = await _detail_or_404(runtime, sid)
    if not detail['ended'] or (archived and detail['protected']):
        raise AppError.from_status(409, 'Active or protected sessions cannot be archived')
    runtime.store.put('archive', (datetime.now(timezone.utc).isoformat() if archived else None, sid))
    await asyncio.to_thread(runtime.store.flush)
    return {'ok': True}


async def session_purge(runtime, sid: str) -> dict:
    """Caller has already checked the confirmation string (schema/command/route)."""
    if runtime.sessions.id:
        raise AppError.from_status(409, 'End recording before disk cleanup')
    detail = await asyncio.to_thread(runtime.store.detail, sid)
    if not detail or not detail['ended'] or detail['protected'] or not detail['archived_at']:
        raise AppError.from_status(409, 'Only archived, ended, unprotected sessions can be purged')
    runtime.store.put('purge', sid)
    await asyncio.to_thread(runtime.store.flush)
    return {'ok': True, 'note': 'Freed SQLite pages are reused. Vacuum only offline.'}


async def retention_candidates(runtime) -> list[dict]:
    """Sessions the retention policy would archive (age, optional size cap; protected/active/favourites never)."""
    from .storage.retention import RetentionPolicy, select_for_archive
    settings = runtime.settings
    rows = await asyncio.to_thread(runtime.store.query,
                                   'SELECT id,started,ended,status,provenance,protected,archived_at,meta FROM sessions '
                                   'WHERE ended IS NOT NULL AND archived_at IS NULL ORDER BY started LIMIT 5000')
    sessions = []
    for r in rows:
        try:
            meta = json.loads(r['meta'])
        except (TypeError, ValueError):
            meta = {}
        # age is measured from when the session ended (as the original retention query did)
        sessions.append({**r, 'meta': meta, 'started': r['ended']})
    policy = RetentionPolicy.from_settings(settings.retention_days, getattr(settings, 'max_storage_gb', None))
    db_bytes = (await asyncio.to_thread(runtime.store.health))['db_bytes']
    chosen = set(select_for_archive(sessions, policy, datetime.now(timezone.utc), db_bytes))
    return [{'id': r['id'], 'started': r['started'], 'status': r['status'], 'provenance': r['provenance']}
            for r in rows if r['id'] in chosen][:1000]


async def retention_apply(runtime) -> dict:
    rows = await retention_candidates(runtime)
    stamp = datetime.now(timezone.utc).isoformat()
    for row in rows:
        runtime.store.put('archive', (stamp, row['id']))
    await asyncio.to_thread(runtime.store.flush)
    return {'archived': len(rows), 'note': 'Recoverable archive only. Purge requires a separate explicit action.'}

