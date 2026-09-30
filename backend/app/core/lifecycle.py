"""Service lifecycle: every long-running subsystem reports a ServiceStatus; one failure never stops the rest."""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

log = logging.getLogger('system')


class ServiceState(StrEnum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    DEGRADED = 'degraded'
    RECONNECTING = 'reconnecting'
    FAILED = 'failed'
    STOPPING = 'stopping'


@dataclass(slots=True)
class ServiceStatus:
    id: str
    state: ServiceState
    since: float = field(default_factory=time.time)
    detail: str = ''
    metrics: dict = field(default_factory=dict)
    last_error: str | None = None
    error_code: str | None = None

    def to_public(self) -> dict:
        return {'id': self.id, 'state': str(self.state), 'since': self.since, 'detail': self.detail,
                'metrics': self.metrics, 'last_error': self.last_error, 'error_code': self.error_code}


@runtime_checkable
class Service(Protocol):
    id: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def status(self) -> ServiceStatus: ...


class BaseService:
    """Convenience base: tracks state transitions; subclasses override _start/_stop/_metrics."""
    id = 'service'

    def __init__(self):
        self._state = ServiceState.STOPPED
        self._since = time.time()
        self._detail = ''
        self._error: str | None = None
        self._code: str | None = None

    def set_state(self, state: ServiceState, detail: str = '', *, error: str | None = None, code: str | None = None):
        if state != self._state or detail != self._detail:
            self._since = time.time()
        self._state, self._detail = state, detail
        if error is not None:
            self._error, self._code = error, code

    async def start(self):
        self.set_state(ServiceState.STARTING)
        await self._start()
        if self._state == ServiceState.STARTING:
            self.set_state(ServiceState.RUNNING)

    async def stop(self):
        self.set_state(ServiceState.STOPPING)
        await self._stop()
        self.set_state(ServiceState.STOPPED)

    async def _start(self): ...
    async def _stop(self): ...
    def _metrics(self) -> dict: return {}

    def status(self) -> ServiceStatus:
        return ServiceStatus(self.id, self._state, self._since, self._detail, self._metrics(), self._error, self._code)


class ServiceRegistry:
    """Topologically ordered start, reverse-ordered bounded stop, failure isolation."""

    def __init__(self, stop_timeout: float = 5.0):
        self._services: dict[str, Service] = {}
        self._deps: dict[str, tuple[str, ...]] = {}
        self._failed: dict[str, ServiceStatus] = {}
        self._started: list[str] = []
        self.stop_timeout = stop_timeout

    def register(self, service: Service, *, depends_on: tuple[str, ...] = ()) -> Service:
        if service.id in self._services:
            raise ValueError(f'duplicate service id {service.id!r}')
        self._services[service.id] = service
        self._deps[service.id] = tuple(depends_on)
        return service

    def get(self, service_id: str) -> Service | None:
        return self._services.get(service_id)

    def order(self) -> list[str]:
        """Dependencies first. Unknown dependencies and cycles are configuration errors."""
        done: list[str] = []
        visiting: set[str] = set()

        def visit(node: str):
            if node in done:
                return
            if node in visiting:
                raise ValueError(f'service dependency cycle at {node!r}')
            visiting.add(node)
            for dep in self._deps[node]:
                if dep not in self._services:
                    raise ValueError(f'{node!r} depends on unknown service {dep!r}')
                visit(dep)
            visiting.discard(node)
            done.append(node)

        for sid in self._services:
            visit(sid)
        return done

    async def start_all(self):
        for sid in self.order():
            service = self._services[sid]
            if any(dep in self._failed for dep in self._deps[sid]):
                self._failed[sid] = ServiceStatus(sid, ServiceState.FAILED, detail='dependency failed',
                                                  error_code='dependency_failed')
                continue
            try:
                await service.start()
                self._started.append(sid)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # isolation: log, mark FAILED, carry on
                log.error('service_start_failed', extra={'event': 'service_start_failed', 'details': {'service': sid, 'error': str(error)[:300]}})
                self._failed[sid] = ServiceStatus(sid, ServiceState.FAILED, detail='start failed',
                                                  last_error=str(error)[:300], error_code=type(error).__name__)

    async def stop_all(self):
        for sid in reversed(self._started):
            try:
                await asyncio.wait_for(self._services[sid].stop(), self.stop_timeout)
            except Exception as error:  # a stuck/failed stop must not block shutdown of the others
                log.warning('service_stop_failed', extra={'event': 'service_stop_failed', 'details': {'service': sid, 'error': str(error)[:300]}})
        self._started.clear()

    def statuses(self) -> list[ServiceStatus]:
        out = []
        for sid, service in self._services.items():
            if sid in self._failed:
                out.append(self._failed[sid])
                continue
            try:
                out.append(service.status())
            except Exception as error:
                out.append(ServiceStatus(sid, ServiceState.FAILED, detail='status() raised', last_error=str(error)[:200]))
        return out

    def public(self) -> list[dict]:
        return [s.to_public() for s in self.statuses()]
