"""Operator control actions (source switching, audio, replay...). One implementation shared by the
legacy `POST /api/control {action}` shim and the `source.*` / `audio.*` / `session.*` commands.

Raises core.errors.AppError; adapters map it to HTTP.
"""
import asyncio

from .core.errors import AppError
from .voice import audio_probe

ACTIONS = ('demo', 'live', 'ai_briefing', 'telemetry_test', 'reconnect', 'start', 'end', 'stop', 'mute', 'resume',
           'speaker_test', 'audio_test', 'calibrate', 'listen_on', 'listen_off', 'mic_enable', 'ptt_start', 'ptt_stop',
           'replay', 'replay_pause', 'replay_speed', 'replay_seek', 'leave_safe_mode')


async def control_action(runtime, action: str, value=None) -> dict:
    if action in ('demo', 'live'):
        runtime.switch(action)
    elif action == 'leave_safe_mode':
        # Confirms heartbeat/mic/local AI; group hosting and the group client never auto-start anyway.
        runtime.set_safe_mode(None)
    elif action == 'ai_briefing':
        runtime.ai_refresh_requested = True
    elif action == 'telemetry_test':
        if runtime.source != 'live':
            raise AppError.from_status(400, 'Select live PS5 telemetry before testing')
        runtime.start_reception_test()
    elif action == 'reconnect':
        runtime.switch('live')
    elif action == 'start':
        runtime.sessions.manual_ended = False
    elif action == 'end':
        return runtime.command('end session')
    elif action == 'stop':
        return runtime.command('stop talking')
    elif action == 'mute':
        return runtime.command('mute')
    elif action == 'resume':
        return runtime.command('resume engineer')
    elif action == 'speaker_test':
        runtime.scheduler.cancel('Speaker test')
        runtime.speaker.stop()
        if runtime.speaker.thread:
            await asyncio.to_thread(runtime.speaker.thread.join, 3)
        if runtime.speaker.busy:
            raise AppError.from_status(409, 'Previous speech is still stopping. Try again shortly.')
        runtime.update_settings({**runtime.settings.model_dump(), 'speech_enabled': True, 'hard_mute': False,
                                 'voice_volume': runtime.settings.voice_volume or 80})
        runtime.mic.set_suppressed(True)
        runtime.speaker.speak('Radio check. This is your GT7 race engineer speaking through the selected output device.', runtime.settings, 1)
        return {'ok': True, 'message': 'Speaker test started. Spoken output is now enabled.'}
    elif action in ('audio_test', 'calibrate'):
        if runtime.mic_testing:
            raise AppError.from_status(409, 'An audio test is already running')
        runtime.mic_testing = True
        try:
            runtime.speaker.stop()
            runtime.scheduler.cancel('Audio test')
            await asyncio.to_thread(runtime.mic.close)
            return await asyncio.to_thread(audio_probe, runtime.settings, action == 'audio_test')
        finally:
            runtime.mic_testing = False
            runtime.mic.last_attempt = -1e30
    elif action in ('listen_on', 'listen_off'):
        runtime.update_settings({**runtime.settings.model_dump(), 'hands_free': action == 'listen_on'})
    elif action == 'mic_enable':
        runtime.mic.start_worker(runtime.settings)
    elif action == 'ptt_start':
        if runtime.mic_testing:
            raise AppError.from_status(409, 'Wait for the audio test to finish')
        runtime.speaker.stop()
        runtime.scheduler.cancel('Push to talk')
        runtime.mic.start_worker(runtime.settings)
        await asyncio.sleep(.25)
        runtime.mic.control('start')
    elif action == 'ptt_stop':
        runtime.mic.control('stop')
    elif action == 'replay':
        sid = str(value)
        if not await asyncio.to_thread(runtime.store.detail, sid):
            raise AppError.from_status(404, 'Session not found')
        runtime.switch('replay')
        runtime.replay = sid
        runtime.replay_cursor = -1e30
        runtime.replay_record_id = 0
        runtime.replay_last = None
        runtime.replay_buffer.clear()
        runtime.replay_paused = False
    elif action == 'replay_pause':
        runtime.replay_paused = not runtime.replay_paused
    elif action == 'replay_speed':
        runtime.replay_speed = max(.25, min(16, float(value or 1)))
    elif action == 'replay_seek':
        runtime.sessions.end('interrupted')
        runtime.sessions.manual_ended = False
        runtime.scheduler.cancel('Replay seek')
        runtime.rules = type(runtime.rules)(runtime.settings)
        runtime._refresh_flags()          # re-point the new Rules at the (safe-mode) settings view
        runtime.replay_cursor = float(value or 0)
        runtime.replay_record_id = 0
        runtime.replay_last = None
        runtime.replay_buffer.clear()
        runtime.history.clear()
        runtime.reset_driver_line()
        runtime.last_lap = None
    else:
        raise AppError.from_status(400, 'Unknown control')
    return {'ok': True}
