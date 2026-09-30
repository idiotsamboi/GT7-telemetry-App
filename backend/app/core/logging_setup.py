"""Structured JSON-lines logging with redaction, repeat suppression and an in-memory error ring.

Subsystem loggers: system, network, telemetry, session, race_control, broadcast, engineer,
audio, storage, ai, training, ui. Never log per-frame telemetry at INFO+, raw packets (DEBUG,
sampled) or credentials/tokens/invitation keys/overlay fragments/microphone audio.
"""
import json
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .defaults import ERROR_RING, LOG_BACKUPS, LOG_MAX_BYTES, LOG_REPEAT_WINDOW_S

SUBSYSTEMS = ('system', 'network', 'telemetry', 'session', 'race_control', 'broadcast', 'engineer',
              'audio', 'storage', 'ai', 'training', 'ui')

REDACTED = '[redacted]'
_SECRET_KEYS = re.compile(r'(token|credential|secret|password|passwd|authorization|invite|invitation|cookie|fragment|api[_-]?key)', re.I)
# key=value / key: value / JSON "key":"value" / URL fragment '#token=...' / query '?token=...'
_SECRET_PATTERNS = [
    re.compile(r'((?:token|credential|secret|password|authorization|invite|invitation|x-control-token|gt7_token|key)["\']?\s*[=:]\s*["\']?)([^\s"\'&,;}]+)', re.I),
    re.compile(r'(#[^\s]*?(?:token|credential|key)=)([^\s&]+)', re.I),
    re.compile(r'(Bearer\s+)([A-Za-z0-9._~+/=-]{8,})', re.I),
]


def redact_text(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
    return text


def redact(value, _key: str = ''):
    """Recursively redact dict values whose key names look secret, and secret-looking substrings."""
    if isinstance(value, dict):
        return {k: (REDACTED if _SECRET_KEYS.search(str(k)) and v not in (None, '', False) else redact(v, str(k))) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        details = getattr(record, 'details', None)
        if details is not None:
            record.details = redact(details)
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class RepeatFilter(logging.Filter):
    """Same (logger, level, event/message) at most once per window; reports the suppressed count."""

    def __init__(self, window: float = LOG_REPEAT_WINDOW_S, clock=time.monotonic):
        super().__init__()
        self.window, self.clock = window, clock
        self._seen: dict[tuple, list] = {}      # key -> [last_emit, suppressed]

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True
        key = (record.name, record.levelno, getattr(record, 'event', None) or record.msg)
        now = self.clock()
        entry = self._seen.get(key)
        if entry is None:
            if len(self._seen) > 512:
                self._seen.clear()
            self._seen[key] = [now, 0]
            return True
        if now - entry[0] < self.window:
            entry[1] += 1
            return False
        record.suppressed = entry[1]
        entry[0], entry[1] = now, 0
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {'t': datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec='milliseconds'),
               'lvl': record.levelname, 'sub': record.name,
               'event': getattr(record, 'event', None) or record.getMessage()}
        details = getattr(record, 'details', None)
        if details:
            out['details'] = details
        if getattr(record, 'suppressed', 0):
            out['suppressed'] = record.suppressed
        if getattr(record, 'exc_text', None):
            out['exc'] = record.exc_text[-2000:]
        elif record.exc_info:
            out['exc'] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(out, default=str)


class ErrorRing(logging.Handler):
    """Last N structured errors, for diagnostics."""

    def __init__(self, size: int = ERROR_RING):
        super().__init__(level=logging.ERROR)
        self.ring: deque = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        self.ring.appendleft({'t': datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec='seconds'),
                              'sub': record.name, 'event': getattr(record, 'event', None) or record.getMessage()[:160],
                              'details': getattr(record, 'details', None)})


ERRORS = ErrorRing()
_installed: dict[str, object] = {}
_current_token: object | None = None


def setup_logging(log_dir: Path | None, level: str = 'INFO', *, console: bool = False, subsystem_levels: dict | None = None) -> object:
    """Idempotent (process-global). Attaches handlers to the root logger and sets the subsystem levels.
    Returns a token: pass it to `shutdown_logging` so an app shutting down does not tear down logging that another
    app in the same process installed after it."""
    global _current_token
    root = logging.getLogger()
    for handler in _installed.values():
        root.removeHandler(handler)           # type: ignore[arg-type]
        handler.close()                       # type: ignore[attr-defined]  (releases the log file on Windows)
    _installed.clear()
    root.setLevel(logging.WARNING)
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    handlers: list[logging.Handler] = [ERRORS]
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / 'app.jsonl', maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding='utf-8')
        fh.setFormatter(JsonFormatter())
        handlers.append(fh)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(asctime)s %(levelname)-7s %(name)s %(message)s'))
        handlers.append(ch)
    for handler in handlers:
        handler.addFilter(RedactionFilter())
        if handler is not ERRORS:
            handler.addFilter(RepeatFilter())
        root.addHandler(handler)
        _installed[f'h{id(handler)}'] = handler
    for name in SUBSYSTEMS:
        logging.getLogger(name).setLevel((subsystem_levels or {}).get(name, numeric))
    _current_token = object()
    return _current_token


def shutdown_logging(token: object | None = None) -> None:
    """Detach file/console handlers (releases the log file on Windows). No-op if `token` is stale."""
    if token is not None and token is not _current_token:
        return
    setup_logging(None, 'WARNING')


def get_logger(subsystem: str) -> logging.Logger:
    if subsystem not in SUBSYSTEMS:
        raise ValueError(f'unknown log subsystem {subsystem!r}')
    return logging.getLogger(subsystem)


def log_event(subsystem: str, level: int, event: str, **details) -> None:
    get_logger(subsystem).log(level, event, extra={'event': event, 'details': details or None})
