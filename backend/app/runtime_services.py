"""Service wrappers over the existing Runtime subsystems.

Each wrapper delegates to code that already exists (the asyncio loops, the recorder, the mic worker,
...). They exist so the UI and diagnostics read ONE status vocabulary (core.lifecycle.ServiceStatus)
instead of poking `receiver`/`audio` internals, and so start/stop ordering and failure isolation
are explicit. Services are backend-owned: nothing here reacts to frontend navigation.
"""
import asyncio
from typing import Callable

from .core.lifecycle import BaseService, ServiceRegistry, ServiceState

Probe = Callable[[], tuple[ServiceState, str, dict]]


class ProbedService(BaseService):
    """A subsystem whose lifecycle is owned elsewhere; status comes from a probe of live state."""

    def __init__(self, service_id: str, probe: Probe):
        super().__init__()
        self.id = service_id
        self._probe = probe

    def status(self):
        try:
            state, detail, metrics = self._probe()
        except Exception as error:      # a probe bug must not take diagnostics down
            state, detail, metrics = ServiceState.FAILED, 'status probe failed', {}
            self._error, self._code = str(error)[:200], 'probe_error'
        if self._state in (ServiceState.STOPPED, ServiceState.STOPPING, ServiceState.STARTING):
            state = self._state         # lifecycle transitions win over the probe
        status = super().status()
        status.state, status.detail, status.metrics = state, detail, metrics
        return status


class LoopService(ProbedService):
    """Owns one of Runtime's asyncio loops: start creates the task, stop cancels it."""

    def __init__(self, service_id: str, runtime, coro_factory: Callable, probe: Probe):
        super().__init__(service_id, probe)
        self._runtime, self._factory = runtime, coro_factory
        self.task: asyncio.Task | None = None

    async def _start(self):
        self.task = asyncio.create_task(self._factory())
        self._runtime.tasks.append(self.task)

    async def _stop(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    def status(self):
        status = super().status()
        if self.task is not None and self.task.done() and self._state == ServiceState.RUNNING:
            error = None if self.task.cancelled() else self.task.exception()
            status.state = ServiceState.FAILED
            status.detail = 'loop exited'
            status.last_error = str(error)[:200] if error else None
            status.error_code = type(error).__name__ if error else 'loop_exited'
        return status


# ---- probes ----------------------------------------------------------------------------------------
_RECEIVER_STATES = {
    'not_configured': (ServiceState.STOPPED, 'PS5 address not configured'),
    'host_only': (ServiceState.STOPPED, 'Host-only mode: no driver telemetry'),
    'binding': (ServiceState.STARTING, 'Binding UDP socket'),
    'awaiting_packets': (ServiceState.RUNNING, 'Waiting for the console to send packets'),
    'receiving': (ServiceState.RUNNING, 'Receiving'),
    'demo_no_network': (ServiceState.RUNNING, 'Synthetic demo (no network)'),
    'replay_no_network': (ServiceState.RUNNING, 'Replay (no network)'),
    'demo_scenario_complete': (ServiceState.RUNNING, 'Synthetic scenario finished'),
    'stale': (ServiceState.DEGRADED, 'Telemetry is stale'),
    'packets_rejected': (ServiceState.DEGRADED, 'Packets are being rejected'),
    'socket_error': (ServiceState.RECONNECTING, 'Socket error; retrying'),
    'bind_failed': (ServiceState.FAILED, 'Cannot bind the UDP port'),
}


def receiver_probe(runtime) -> Probe:
    def probe():
        r = runtime.receiver
        state, detail = _RECEIVER_STATES.get(r.get('phase'), (ServiceState.RUNNING, str(r.get('phase'))))
        if r.get('phase') == 'bind_failed' and runtime.socket_error:
            detail = runtime.socket_error[:200]
        metrics = {'phase': r.get('phase'), 'source': runtime.source, 'variant': r.get('last_variant'),
                   'datagrams': r.get('datagrams'), 'valid_packets': r.get('valid_packets'),
                   'parse_errors': runtime.parse_errors, 'unexpected_senders': runtime.unexpected,
                   'sequence': dict(runtime.seq.counts)}
        return state, detail, metrics
    return probe


def recorder_probe(runtime) -> Probe:
    def probe():
        h = runtime.store.health()
        if h['error'] or h['failed_rows']:
            state, detail = ServiceState.FAILED if h['error'] else ServiceState.DEGRADED, 'Recording failure; live telemetry is unaffected'
        elif h['application_drops']:
            state, detail = ServiceState.DEGRADED, f"{h['application_drops']} samples dropped (queue full)"
        else:
            state, detail = ServiceState.RUNNING, 'Recording' if runtime.sessions.id else 'Ready'
        return state, detail, {'phase': 'RECORDING' if runtime.sessions.id else 'READY', **h}
    return probe


def engine_probe(runtime) -> Probe:
    def probe():
        s = runtime.scheduler
        return ServiceState.RUNNING, 'Engineer rules and speech scheduler', {
            'pending': len(s.pending), 'speaking': runtime.speaker.busy, 'speech_error': runtime.speaker.error}
    return probe


def microphone_probe(runtime) -> Probe:
    _map = {'disabled': (ServiceState.STOPPED, 'Microphone disabled'), 'unavailable': (ServiceState.FAILED, 'Microphone unavailable'),
            'loading': (ServiceState.STARTING, 'Loading recognizer'), 'listening': (ServiceState.RUNNING, 'Listening')}

    def probe():
        state, detail = _map.get(runtime.mic.state, (ServiceState.RUNNING, str(runtime.mic.state)))
        if runtime.mic.error and state == ServiceState.FAILED:
            detail = str(runtime.mic.error)[:200]
        return state, detail, {'state': runtime.mic.state, 'hands_free': runtime.settings.hands_free,
                               'clipping': runtime.mic.clipping}
    return probe


def local_ai_probe(runtime) -> Probe:
    def probe():
        if not runtime.settings.local_ai_enabled:
            return ServiceState.STOPPED, 'Local model disabled (calculated evidence summary remains)', {}
        r = runtime.local_ai.result or {}
        state = ServiceState.DEGRADED if r.get('model_error') else ServiceState.RUNNING
        return state, str(r.get('reason') or r.get('status') or ''), {'status': r.get('status'), 'engine': r.get('engine')}
    return probe


def track_probe(runtime) -> Probe:
    def probe():
        t = runtime.track_map
        state = ServiceState.DEGRADED if t.error else ServiceState.RUNNING
        locked = runtime.track.locked is not None
        return state, (t.error or ('Track locked' if locked else 'Searching for the track')), {
            'layout_id': t.layout_id, 'locked': locked, 'map_status': t.status}
    return probe


def group_host_probe(runtime) -> Probe:
    def probe():
        g = getattr(runtime, 'group', None)
        if g is None or not g.running:
            return ServiceState.STOPPED, 'Group service not running', {}
        hosting = bool(getattr(g, 'listener', None))
        return (ServiceState.RUNNING if hosting else ServiceState.STOPPED), ('Hosting on the LAN' if hosting else 'Not hosting'), {
            'hosting': hosting, 'recording_drops': getattr(g, 'recording_drops', 0)}
    return probe


def group_client_probe(runtime) -> Probe:
    def probe():
        g = getattr(runtime, 'group', None)
        client = getattr(g, 'client', None)
        if client is None:
            return ServiceState.STOPPED, 'Not connected to a group', {}
        status = client.status
        state = {'connected': ServiceState.RUNNING, 'joining': ServiceState.STARTING, 'reconnecting': ServiceState.RECONNECTING}.get(status, ServiceState.DEGRADED)
        return state, str(client.error or status), {'status': status, 'rate_hz': client.rate}
    return probe


def overlay_probe(runtime) -> Probe:
    def probe():
        g = getattr(runtime, 'group', None)
        hosting = bool(getattr(g, 'listener', None))
        return (ServiceState.RUNNING if hosting else ServiceState.STOPPED), ('Overlay output available' if hosting else 'Overlay output needs hosting'), {}
    return probe


def diagnostics_probe(runtime) -> Probe:
    def probe():
        degraded = bool(runtime.degraded)
        return (ServiceState.DEGRADED if degraded else ServiceState.RUNNING), (runtime.health_cache.get('reason') or 'Healthy'), {
            'loop_lag_ms': round(runtime.loop_lag * 1000, 1), 'rate_hz': round(runtime.health_cache.get('rate_hz') or 0, 1)}
    return probe


def build_services(runtime) -> ServiceRegistry:
    """Composition of the runtime's services. Order = dependency order."""
    reg = ServiceRegistry()
    reg.register(ProbedService('recorder', recorder_probe(runtime)))
    def career_probe():
        health = runtime.career.health()
        state = ServiceState.DEGRADED if health['last_error'] else (ServiceState.RUNNING if health['running'] else ServiceState.STOPPED)
        return state, 'Local Driver Career; recording has priority', health
    reg.register(ProbedService('gamification', career_probe))
    reg.register(LoopService('telemetry_receiver', runtime, runtime.source_loop, receiver_probe(runtime)), depends_on=('recorder',))
    reg.register(LoopService('engine', runtime, runtime.engine_loop, engine_probe(runtime)))
    reg.register(LoopService('diagnostics', runtime, runtime.health_loop, diagnostics_probe(runtime)))
    reg.register(LoopService('local_ai', runtime, runtime.ai_loop, local_ai_probe(runtime)))
    reg.register(LoopService('track', runtime, runtime.track_loop, track_probe(runtime)))
    reg.register(ProbedService('microphone', microphone_probe(runtime)), depends_on=('engine',))
    reg.register(ProbedService('group_host', group_host_probe(runtime)))
    reg.register(ProbedService('group_client', group_client_probe(runtime)), depends_on=('group_host',))
    reg.register(ProbedService('overlay_output', overlay_probe(runtime)), depends_on=('group_host',))
    return reg
