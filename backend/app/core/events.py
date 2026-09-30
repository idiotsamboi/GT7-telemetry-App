"""Small in-process pub/sub for application events (lap, session, connection...). No broker."""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger('system')


@dataclass(slots=True)
class AppEvent:
    kind: str                       # 'lap_completed', 'session_started', 'session_ended', 'source_changed', ...
    data: dict = field(default_factory=dict)
    mono: float = field(default_factory=time.monotonic)


class EventBus:
    """Synchronous delivery in subscription order. A handler failure is counted, never propagated."""

    def __init__(self):
        self._handlers: list[tuple[str, str | None, Callable[[AppEvent], Any]]] = []
        self.metrics = {'emitted': 0, 'handler_errors': 0}
        self._last_error_log: dict[str, float] = {}

    def subscribe(self, name: str, handler: Callable[[AppEvent], Any], kind: str | None = None) -> Callable[[], None]:
        entry = (name, kind, handler)
        self._handlers.append(entry)
        return lambda: self._handlers.remove(entry) if entry in self._handlers else None

    def emit(self, event: AppEvent) -> None:
        self.metrics['emitted'] += 1
        for name, kind, handler in tuple(self._handlers):
            if kind is not None and kind != event.kind:
                continue
            try:
                handler(event)
            except Exception as error:
                self.metrics['handler_errors'] += 1
                now = time.monotonic()
                if now - self._last_error_log.get(name, -1e9) >= 60:
                    self._last_error_log[name] = now
                    log.error('event_handler_failed', extra={'event': 'event_handler_failed', 'details': {'subscriber': name, 'kind': event.kind, 'error': str(error)[:200]}})
