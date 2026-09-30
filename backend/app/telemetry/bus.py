"""Synchronous in-process telemetry bus.

`publish(frame)` runs on the ingestion path (one call per UDP packet, ~60 Hz), so it must be cheap and
must never raise.  Subscribers choose how they want frames:

  every   handler(frame) is called inline for every frame
  rate    handler(frame) is called at most `hz` times per second, decided from `frame.meta.mono`
          (the first frame always passes; a clock that goes backwards restarts the cadence)
  latest  nothing is called; the newest frame is kept in a slot the consumer pulls with
          `subscription.latest()` (e.g. a 10 Hz UI push loop)

Critical subscribers run before the others; otherwise order is subscription order.  A handler that raises is
caught, counted, and logged at most once per 60 s per subscriber name, so a broken consumer can neither
stop ingestion nor starve the other subscribers.

Discrete events (lap completed, connection changed, ...) go through `emit(TelemetryEvent)` to handlers
registered with `subscribe_events`, with the same isolation guarantees.
"""
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Optional

from .frame import TelemetryFrame

log = logging.getLogger('telemetry')

# Event kinds
LAP_COMPLETED = 'lap_completed'
SESSION_STARTED = 'session_started'
SESSION_ENDED = 'session_ended'
SOURCE_CHANGED = 'source_changed'
CONNECTION_CHANGED = 'connection_changed'
TRACK_LOCKED = 'track_locked'
TRACK_UNLOCKED = 'track_unlocked'
PIT_DETECTED = 'pit_detected'
EVENT_KINDS = (LAP_COMPLETED, SESSION_STARTED, SESSION_ENDED, SOURCE_CHANGED, CONNECTION_CHANGED,
               TRACK_LOCKED, TRACK_UNLOCKED, PIT_DETECTED)

Mode = Literal['every', 'rate', 'latest']
TIMING_SAMPLE_EVERY = 16      # time one handler call in N (perf_counter is cheap but not free)
ERROR_LOG_INTERVAL_S = 60.0
DURATION_WINDOW = 256


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    kind: str
    data: dict = field(default_factory=dict)
    mono: float = 0.0


class SubscriberMetrics:
    __slots__ = ('calls', 'errors', 'last_error', 'durations', 'last_logged', 'suppressed')

    def __init__(self):
        self.calls = 0
        self.errors = 0
        self.last_error: Optional[str] = None
        self.durations: deque[float] = deque(maxlen=DURATION_WINDOW)   # seconds, sampled
        self.last_logged: Optional[float] = None
        self.suppressed = 0

    def p95(self) -> Optional[float]:
        if not self.durations:
            return None
        ordered = sorted(self.durations)
        return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


class Subscription:
    """Handle returned by `subscribe`. `cancel()` is idempotent."""
    __slots__ = ('name', 'handler', 'mode', 'hz', 'critical', 'kinds', 'metrics', 'active',
                 '_bus', '_seq', '_interval', '_last_mono', '_slot', '_fresh')

    def __init__(self, bus: 'TelemetryBus', seq: int, name: str, handler: Optional[Callable], mode: str,
                 hz: Optional[float], critical: bool, kinds: Optional[frozenset[str]] = None):
        self._bus, self._seq = bus, seq
        self.name, self.handler, self.mode, self.hz, self.critical, self.kinds = name, handler, mode, hz, critical, kinds
        self.metrics = SubscriberMetrics()
        self.active = True
        self._interval = 1.0 / hz if hz else 0.0
        self._last_mono: Optional[float] = None
        self._slot: Optional[TelemetryFrame] = None
        self._fresh = False

    def cancel(self) -> None:
        if self.active:
            self.active = False
            self._bus._remove(self)

    @property
    def fresh(self) -> bool:
        """True when a frame has arrived since the last `latest()` call (latest mode)."""
        return self._fresh

    def latest(self, only_fresh: bool = False) -> Optional[TelemetryFrame]:
        """Newest frame in the slot (None before the first). Marks the slot as read;
        with `only_fresh=True` returns None when nothing new arrived since the previous read."""
        frame, fresh = self._slot, self._fresh
        self._fresh = False
        if only_fresh and not fresh:
            return None
        return frame


class TelemetryBus:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 on_error: Optional[Callable[[str, Exception], None]] = None):
        self._clock = clock                     # injectable for the error log rate limit
        self._on_error = on_error               # e.g. Runtime counts pipeline errors; must not raise
        self._seq = 0
        self._subs: dict[str, Subscription] = {}
        self._frame_subs: tuple[Subscription, ...] = ()     # rebuilt only on subscribe/cancel
        self._event_subs: tuple[Subscription, ...] = ()
        self.frames_published = 0
        self.events_emitted = 0

    # -- registration ---------------------------------------------------------------------------
    def subscribe(self, name: str, handler: Optional[Callable[[TelemetryFrame], Any]], *, mode: Mode = 'every',
                  hz: Optional[float] = None, critical: bool = False) -> Subscription:
        if mode not in ('every', 'rate', 'latest'):
            raise ValueError(f'unknown subscription mode {mode!r}')
        if mode == 'rate' and (hz is None or hz <= 0):
            raise ValueError("mode 'rate' needs hz > 0")
        if mode != 'latest' and handler is None:
            raise ValueError(f"mode {mode!r} needs a handler")
        return self._add(name, handler, mode, hz, critical, None)

    def subscribe_events(self, name: str, handler: Callable[[TelemetryEvent], Any], *,
                         kinds: Optional[Iterable[str]] = None, critical: bool = False) -> Subscription:
        """`kinds=None` receives every event kind."""
        return self._add(name, handler, 'every', None, critical, frozenset(kinds) if kinds is not None else None,
                         events=True)

    def _add(self, name, handler, mode, hz, critical, kinds, events: bool = False) -> Subscription:
        key = ('event:' if events else 'frame:') + name
        if key in self._subs:
            raise ValueError(f'duplicate subscriber name {name!r}')
        self._seq += 1
        sub = Subscription(self, self._seq, name, handler, mode, hz, critical, kinds)
        self._subs[key] = sub
        self._rebuild()
        return sub

    def _remove(self, sub: Subscription) -> None:
        for key, existing in list(self._subs.items()):
            if existing is sub:
                del self._subs[key]
        self._rebuild()

    def _rebuild(self) -> None:
        ordered = sorted(self._subs.items(), key=lambda kv: (not kv[1].critical, kv[1]._seq))
        self._frame_subs = tuple(s for k, s in ordered if k.startswith('frame:'))
        self._event_subs = tuple(s for k, s in ordered if k.startswith('event:'))

    # -- delivery -----------------------------------------------------------------------------------
    def publish(self, frame: TelemetryFrame) -> None:
        self.frames_published += 1
        mono = frame.meta.mono
        for sub in self._frame_subs:
            mode = sub.mode
            if mode == 'every':
                # hot path, inlined: count, call, and only time/handle errors off the fast path
                metrics = sub.metrics
                calls = metrics.calls = metrics.calls + 1
                if calls % TIMING_SAMPLE_EVERY:
                    try:
                        sub.handler(frame)
                    except Exception as error:      # isolation: a subscriber bug must never reach ingestion
                        self._record_error(sub, error)
                else:
                    self._timed_call(sub, frame)
                continue
            if mode == 'latest':
                sub._slot = frame
                sub._fresh = True
                sub.metrics.calls += 1
                continue
            last = sub._last_mono                     # mode == 'rate'
            if last is not None and 0 <= mono - last < sub._interval:
                continue
            sub._last_mono = mono
            self._call(sub, frame)

    def emit(self, event: TelemetryEvent) -> None:
        self.events_emitted += 1
        kind = event.kind
        for sub in self._event_subs:
            if sub.kinds is None or kind in sub.kinds:
                self._call(sub, event)

    def _call(self, sub: Subscription, payload: Any) -> None:
        metrics = sub.metrics
        metrics.calls += 1
        timed = metrics.calls % TIMING_SAMPLE_EVERY == 0
        started = time.perf_counter() if timed else 0.0
        try:
            sub.handler(payload)
        except Exception as error:      # isolation: a subscriber bug must never reach ingestion
            self._record_error(sub, error)
        if timed:
            metrics.durations.append(time.perf_counter() - started)

    def _timed_call(self, sub: Subscription, payload: Any) -> None:
        """Every TIMING_SAMPLE_EVERY-th call is timed (perf_counter is cheap, not free)."""
        started = time.perf_counter()
        try:
            sub.handler(payload)
        except Exception as error:
            self._record_error(sub, error)
        sub.metrics.durations.append(time.perf_counter() - started)

    def _record_error(self, sub: Subscription, error: Exception) -> None:
        metrics = sub.metrics
        metrics.errors += 1
        metrics.last_error = f'{type(error).__name__}: {str(error)[:200]}'
        if self._on_error is not None:
            try:
                self._on_error(sub.name, error)
            except Exception:
                pass
        try:
            now = self._clock()
            if metrics.last_logged is None or now - metrics.last_logged >= ERROR_LOG_INTERVAL_S:
                log.warning('telemetry subscriber %r failed: %s (%d similar errors suppressed)', sub.name,
                            metrics.last_error, metrics.suppressed, exc_info=error)
                metrics.last_logged = now
                metrics.suppressed = 0
            else:
                metrics.suppressed += 1
        except Exception:
            pass     # even a broken logger/clock must not break delivery

    # -- observability --------------------------------------------------------------------------------
    @staticmethod
    def _public_key(key: str) -> str:
        # Frame subscribers are listed by their plain name, event subscribers as 'event:<name>'.
        return key[len('frame:'):] if key.startswith('frame:') else key

    @property
    def metrics(self) -> dict[str, SubscriberMetrics]:
        return {self._public_key(key): sub.metrics for key, sub in self._subs.items()}

    def metrics_snapshot(self) -> dict:
        def describe(sub: Subscription) -> dict:
            m = sub.metrics
            p95 = m.p95()
            return {'mode': sub.mode, 'hz': sub.hz, 'critical': sub.critical, 'calls': m.calls, 'errors': m.errors,
                    'last_error': m.last_error, 'p95_ms': None if p95 is None else round(p95 * 1000, 4)}
        return {'frames_published': self.frames_published, 'events_emitted': self.events_emitted,
                'subscribers': {self._public_key(key): describe(sub) for key, sub in self._subs.items()}}
