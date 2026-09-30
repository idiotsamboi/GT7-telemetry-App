"""Commands (state-changing or externally visible) vs queries (read-only GET).

`dispatch()` validates the payload, checks the capability, applies the rate limit, runs the
handler and writes an audit row for audited commands. Adapters map CommandResult.code to HTTP.
"""
import hashlib
import inspect
import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from .errors import HTTP_STATUS, AppError, ResultCode
from .permissions import Principal, can
from .registry import Registry

log = logging.getLogger('system')


def uid() -> str:
    return uuid.uuid4().hex


@dataclass(slots=True)
class CommandResult:
    code: ResultCode
    message: str = ''
    diagnostic: str | None = None
    data: dict | None = None
    command_id: str = field(default_factory=uid)
    audit_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.code == ResultCode.OK

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.code]

    def to_public(self) -> dict:
        return {'code': str(self.code), 'ok': self.ok, 'message': self.message, 'diagnostic': self.diagnostic,
                'data': self.data, 'command_id': self.command_id, 'audit_id': self.audit_id}


class Empty(BaseModel):
    """Payload schema for commands without parameters."""


@dataclass(slots=True)
class Ctx:
    """What a handler gets. `services` is the composition root (runtime); core never inspects it."""
    principal: Principal
    services: Any = None
    audit: Callable[[dict], None] | None = None     # sink for audited commands
    session_id: str | None = None


Handler = Callable[[Ctx, BaseModel], Awaitable[CommandResult] | CommandResult]


@dataclass(frozen=True)
class CommandDef:
    id: str                                # 'session.start', 'raceControl.setFlag', 'graphics.take', 'engineer.ask'
    capability: str
    schema: type[BaseModel]
    handler: Handler
    audited: bool = False                  # race-control / broadcast / destructive -> audit log
    rate: tuple[int, float] | None = None  # (max calls, per seconds), per principal
    destructive: bool = False              # requires payload field `confirm: true`... enforced by the UI + here
    description: str = ''


COMMANDS: Registry[CommandDef] = Registry('commands', public=lambda c: {
    'id': c.id, 'capability': c.capability, 'audited': c.audited, 'rate': list(c.rate) if c.rate else None,
    'destructive': c.destructive, 'description': c.description, 'schema': c.schema.model_json_schema()})


def register(command: CommandDef) -> CommandDef:
    return COMMANDS.register(command)


class RateLimiter:
    """Sliding window per key. Thread-safe: sync routes run on the thread pool, async handlers on the loop."""

    def __init__(self):
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: tuple[str, str], maximum: int, period: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque(maxlen=maximum))
            while hits and now - hits[0] > period:
                hits.popleft()
            if len(hits) >= maximum:
                return False
            hits.append(now)
            return True


_limiter = RateLimiter()


def audit_target(payload: dict) -> str:
    """What the command acted on. Scalars only and bounded: the payload may contain anything (pass-through bodies), and
    the audit row must always be storable and never carry a structured/secret blob."""
    for key in ('target', 'id'):
        value = payload.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and value != '':
            return str(value)[:100]
    return ''


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


async def dispatch(ctx: Ctx, command_id: str, payload: dict | None = None, *, registry: Registry = COMMANDS,
                   limiter: RateLimiter = _limiter) -> CommandResult:
    command = registry.get(command_id)
    if command is None:
        return CommandResult(ResultCode.NOT_FOUND, f'Unknown command {command_id}')
    payload = payload or {}
    result: CommandResult
    if not can(ctx.principal, command.capability):
        result = CommandResult(ResultCode.NOT_AUTHORIZED, 'Not permitted', diagnostic=command.capability)
    elif command.rate and not limiter.allow((ctx.principal.subject or ctx.principal.kind, command.id), *command.rate):
        result = CommandResult(ResultCode.RATE_LIMITED, 'Too many requests; slow down')
    else:
        try:
            parsed = command.schema.model_validate(payload)
        except ValidationError as error:
            result = CommandResult(ResultCode.INVALID_INPUT, 'Invalid request', diagnostic=str(error)[:400])
        else:
            if command.destructive and payload.get('confirm') is not True:
                result = CommandResult(ResultCode.INVALID_INPUT, 'Confirmation required', diagnostic='confirm')
            else:
                try:
                    out = command.handler(ctx, parsed)
                    result = await out if inspect.isawaitable(out) else out
                except AppError as error:
                    result = CommandResult(error.code, error.detail)
                except ValidationError as error:     # a service validated the payload itself
                    result = CommandResult(ResultCode.INVALID_INPUT, 'Invalid request', diagnostic=str(error)[:400])
                except Exception as error:   # a handler bug is UNAVAILABLE for the caller, logged for us
                    log.exception('command_failed', extra={'event': 'command_failed', 'details': {'command': command.id}})
                    result = CommandResult(ResultCode.UNAVAILABLE, 'Command failed', diagnostic=type(error).__name__)
    if command.audited and ctx.audit:
        row = {'id': uid(), 'utc': time.time(), 'actor': f'{ctx.principal.kind}:{ctx.principal.subject}', 'capability': command.capability,
               'command_id': command.id, 'target': audit_target(payload), 'payload_hash': payload_hash(payload),
               'result_code': str(result.code), 'message': result.message[:200], 'session_id': ctx.session_id}
        try:
            ctx.audit(row)
            result.audit_id = row['id']
        except Exception:
            log.exception('audit_write_failed', extra={'event': 'audit_write_failed'})
    return result
