"""Group wire protocol v2: envelope, message registry, handshake and reliable delivery.

Pure logic: no sockets, no fastapi, no asyncio. Transports (group/public.py, group/client.py) call
`decode`/`encode`, `negotiate`, and drive `ReliableChannel` with their own clock. Legacy (v1) flat
messages such as `{'type': 'lap', 'lap': {...}}` are accepted and converted, so old clients keep
working for one release; v1 use is logged as a DEPRECATION event.

Envelope: {v, type, id, ts, sender, session, seq, payload}.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.errors import AppError, ResultCode
from ..core.registry import Registry
from ..core.version import APP_VERSION, PROTOCOL_SUPPORTED, PROTOCOL_VERSION as _CORE_PROTOCOL_VERSION

PROTOCOL_VERSION = _CORE_PROTOCOL_VERSION
SUPPORTED = tuple(PROTOCOL_SUPPORTED)
SERVER_CAPABILITIES = ('envelope-v2', 'ack', 'reliable', 'snapshot-cache')
CLIENT_CAPABILITIES = ('envelope-v2', 'ack', 'reliable')
CLOSE_PROTOCOL_INCOMPATIBLE = 4426          # WebSocket application close code
MAX_MESSAGE_BYTES = 32768

log = logging.getLogger('network')


class ProtocolError(AppError):
    """Malformed, oversized, unknown or not-permitted message. Carries the HTTP-shaped status."""

    def __init__(self, status: int, message: str, code: str = ''):
        super().__init__(ResultCode.INVALID_INPUT if status in (400, 413, 422) else ResultCode.NOT_AUTHORIZED, status, message)
        self.protocol_code = code


# --------------------------------------------------------------------------- payload schemas

class Payload(BaseModel):
    """Base for payload schemas: unknown keys are kept so newer peers can add fields."""
    model_config = ConfigDict(extra='allow')


class HelloPayload(Payload):
    """Either direction; see ClientHello / ServerHello for the strict shapes."""


class ClientHello(BaseModel):
    model_config = ConfigDict(extra='ignore')
    protocol: list[int] | int = Field(default_factory=lambda: [1])
    app_version: str = Field('', max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    boot_id: str = Field('', max_length=100)


class ServerHello(BaseModel):
    model_config = ConfigDict(extra='allow')
    protocol: int
    app_version: str
    compatible: bool
    reason: str = ''
    server_capabilities: list[str] = Field(default_factory=list)
    session_id: str | None = None


class TelemetryPayload(Payload):
    packet: dict


class LapPayload(Payload):
    lap: dict


class ResponsePayload(Payload):
    response: dict


class PingPayload(Payload):
    source: float | None = None


class PongPayload(Payload):
    source: float | None = None
    host_time: float | None = None
    state: dict | None = None


class ClockPayload(Payload):
    uncertainty_ms: float | None = None
    offset_ms: float | None = None


class StatePayload(Payload):
    accepted: bool | None = None
    state: dict | None = None


class ErrorPayload(Payload):
    message: str = ''
    code: str | None = None


class AckPayload(Payload):
    id: str = ''                     # id of the acknowledged message
    ack: Any = None                  # legacy value (lap id) for v1 parity
    of: str | None = None            # type of the acknowledged message


class GenericPayload(Payload):
    """instruction / message / decision / workspace_taken: the document as the host stored it."""


@dataclass(frozen=True)
class MessageType:
    type: str
    schema: type[BaseModel]
    reliability: Literal['ephemeral', 'reliable']
    roles: frozenset[str]            # roles allowed to SEND this type
    description: str = ''


MESSAGE_TYPES: Registry[MessageType] = Registry(
    'protocol messages', key=lambda m: m.type,
    public=lambda m: {'type': m.type, 'reliability': m.reliability, 'roles': sorted(m.roles),
                      'description': m.description, 'schema': m.schema.__name__})

_CLIENTS = ('driver', 'spectator', 'overlay')
for _m in (
    MessageType('hello', HelloPayload, 'ephemeral', frozenset((*_CLIENTS, 'host')), 'Version and capability handshake'),
    MessageType('telemetry', TelemetryPayload, 'ephemeral', frozenset({'driver'}), 'Latest-wins telemetry packet'),
    MessageType('lap', LapPayload, 'reliable', frozenset({'driver'}), 'Completed lap; retried until acked'),
    MessageType('response', ResponsePayload, 'reliable', frozenset({'driver'}), 'Driver response/receipt; retried until acked'),
    MessageType('ping', PingPayload, 'ephemeral', frozenset(_CLIENTS), 'Clock/latency probe'),
    MessageType('clock', ClockPayload, 'ephemeral', frozenset({'driver'}), 'Client clock offset report'),
    MessageType('pong', PongPayload, 'ephemeral', frozenset({'host'}), 'Reply to ping with host time and state'),
    MessageType('state', StatePayload, 'ephemeral', frozenset({'host'}), 'Filtered group state (latest wins)'),
    MessageType('error', ErrorPayload, 'ephemeral', frozenset({'host'}), 'Error before the connection closes'),
    # Acks are idempotent: a duplicate reliable message is simply re-acked, so acks need no ack.
    MessageType('ack', AckPayload, 'ephemeral', frozenset({'host', 'driver'}), 'Acknowledges a reliable message id'),
    MessageType('instruction', GenericPayload, 'reliable', frozenset({'host'}), 'Race-control instruction/flag'),
    MessageType('message', GenericPayload, 'reliable', frozenset({'host'}), 'Race-control message to drivers'),
    MessageType('decision', GenericPayload, 'reliable', frozenset({'host'}), 'Steward decision'),
    MessageType('workspace_taken', GenericPayload, 'reliable', frozenset({'host'}), 'A workspace draft went to program'),
):
    MESSAGE_TYPES.register(_m)

# v1 names that map onto the generic v2 ack
ACK_ALIASES = {'lap_ack': 'lap', 'response_ack': 'response'}
RELIABLE_TYPES = frozenset(m.type for m in MESSAGE_TYPES if m.reliability == 'reliable')
ALLOWED_TYPES: dict[str, frozenset[str]] = {
    role: frozenset(m.type for m in MESSAGE_TYPES if role in m.roles) for role in (*_CLIENTS, 'host')}


# --------------------------------------------------------------------------- envelope

class Envelope(BaseModel):
    model_config = ConfigDict(extra='ignore')
    v: int = PROTOCOL_VERSION
    type: str = Field(max_length=32)
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=100)
    ts: float | str = Field(default_factory=time.time)
    sender: str = Field('', max_length=100)
    session: str | None = Field(None, max_length=100)
    seq: int | None = None
    payload: dict = Field(default_factory=dict)


class Decoded(NamedTuple):
    envelope: Envelope
    legacy: bool


def encode(type: str, payload: dict | None = None, *, sender: str = '', session: str | None = None,
           seq: int | None = None, id: str | None = None, ts: float | None = None) -> dict:
    """Build a JSON-ready v2 envelope. The payload is validated against the type's schema."""
    spec = MESSAGE_TYPES.get(type)
    if spec is None:
        raise ProtocolError(422, 'Unknown message')
    body = dict(payload or {})
    try:
        spec.schema.model_validate(body)
    except ValidationError as error:
        raise ProtocolError(422, f'Invalid {type} payload: {str(error)[:200]}') from None
    envelope = Envelope(type=type, payload=body, sender=sender, session=session, seq=seq,
                        **({'id': id} if id else {}), **({'ts': ts} if ts is not None else {}))
    return envelope.model_dump()


def to_legacy(envelope: Envelope | dict) -> dict:
    """v2 envelope -> the flat v1 message the old code paths understand."""
    data = envelope.model_dump() if isinstance(envelope, Envelope) else envelope
    return {'type': data['type'], **data.get('payload', {})}


def _legacy_id(message: dict) -> str:
    """Stable id for reliable v1 messages so retransmissions deduplicate; else a fresh one."""
    lap = message.get('lap')
    if message.get('type') == 'lap' and isinstance(lap, dict) and isinstance(lap.get('id'), str) and lap['id']:
        return 'lap:' + lap['id'][:90]
    return uuid.uuid4().hex


def is_v2(message: Any) -> bool:
    return isinstance(message, dict) and isinstance(message.get('v'), int) and 'payload' in message and 'type' in message


def decode(raw: dict | str | bytes, *, max_bytes: int = MAX_MESSAGE_BYTES, role: str | None = None) -> Decoded:
    """Parse one inbound message (v2 envelope or v1 flat) into an Envelope.

    Raises ProtocolError: 413 too large, 400 not JSON/object, 422 unknown type or bad payload,
    403 when `role` may not send that type, 426 unsupported envelope version.
    """
    if isinstance(raw, (str, bytes, bytearray)):
        if len(raw) > max_bytes:
            raise ProtocolError(413, 'Packet too large')
        try:
            message = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ProtocolError(400, 'Invalid message') from None
    else:
        message = raw
        try:
            if len(json.dumps(message, separators=(',', ':'))) > max_bytes:
                raise ProtocolError(413, 'Packet too large')
        except (TypeError, ValueError):
            raise ProtocolError(400, 'Invalid message') from None
    if not isinstance(message, dict) or not isinstance(message.get('type'), str):
        raise ProtocolError(400, 'Invalid message')
    legacy = not is_v2(message)
    if legacy:
        payload = {k: v for k, v in message.items() if k != 'type'}
        envelope = Envelope(v=1, type=message['type'][:32], id=_legacy_id(message), payload=payload)
    else:
        if message['v'] not in SUPPORTED:
            raise ProtocolError(426, f'Unsupported protocol version {message["v"]}', 'protocol_incompatible')
        try:
            envelope = Envelope.model_validate(message)
        except ValidationError:
            raise ProtocolError(400, 'Invalid envelope') from None
        if not isinstance(envelope.payload, dict):
            raise ProtocolError(400, 'Invalid envelope')
    spec = MESSAGE_TYPES.get(envelope.type)
    if spec is None:
        raise ProtocolError(422, 'Unknown message')
    if role is not None and envelope.type not in ALLOWED_TYPES.get(role, frozenset()):
        raise ProtocolError(403, 'Message type not permitted')
    try:
        spec.schema.model_validate(envelope.payload)
    except ValidationError:
        raise ProtocolError(422, f'Invalid {envelope.type} payload') from None
    return Decoded(envelope, legacy)


# --------------------------------------------------------------------------- handshake

@dataclass(frozen=True)
class Negotiation:
    compatible: bool
    protocol: int | None             # negotiated version
    legacy: bool                     # client sent no hello: treat as v1
    reason: str = ''
    capabilities: tuple[str, ...] = ()

    def reply_payload(self, *, session_id: str | None = None, app_version: str = APP_VERSION,
                      server_capabilities: Iterable[str] = SERVER_CAPABILITIES, host_time: float | None = None) -> dict:
        body = {'protocol': self.protocol or PROTOCOL_VERSION, 'app_version': app_version, 'compatible': self.compatible,
                'reason': self.reason, 'server_capabilities': list(server_capabilities), 'session_id': session_id}
        if host_time is not None:
            body['host_time'] = host_time
        return body


def negotiate(client_hello: dict | None, server_caps: Iterable[str] = SERVER_CAPABILITIES, *,
              supported: Iterable[int] = SUPPORTED) -> Negotiation:
    """Pure handshake decision. `None` means the client sent no hello: a v1 client."""
    supported = tuple(sorted(supported))
    caps = tuple(server_caps)
    if client_hello is None:
        return Negotiation(compatible=1 in supported, protocol=1 if 1 in supported else None, legacy=True,
                           reason='' if 1 in supported else 'protocol_incompatible: v1 no longer supported')
    try:
        hello = ClientHello.model_validate(client_hello)
    except ValidationError:
        return Negotiation(False, None, False, 'protocol_incompatible: malformed hello')
    offered = sorted(set([hello.protocol] if isinstance(hello.protocol, int) else hello.protocol))
    common = [v for v in offered if v in supported]
    if not common:
        return Negotiation(False, None, False,
                           f'protocol_incompatible: client speaks {offered}, host supports {list(supported)}')
    shared = tuple(c for c in caps if c in set(hello.capabilities))
    return Negotiation(True, max(common), False, '', shared)


class LegacyClientTracker:
    """Logs the v1 DEPRECATION event once per client (bounded memory). Never logs credentials."""

    def __init__(self, limit: int = 512):
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._limit = limit

    def note(self, client_key: str, *, role: str = '') -> bool:
        if client_key in self._seen:
            self._seen.move_to_end(client_key)
            return False
        self._seen[client_key] = None
        while len(self._seen) > self._limit:
            self._seen.popitem(last=False)
        log.warning('DEPRECATION: group protocol v1 client connected; v1 is removed after this release',
                    extra={'event': 'protocol_v1_client', 'details': {'role': role, 'client': client_key[:64]}})
        return True


class Codec:
    """Per-connection encoder: v1 flat until the peer proves it speaks v2, then envelopes."""

    def __init__(self, *, sender: str = 'host', session: str | None = None):
        self.v2 = False
        self.sender = sender
        self.session = session
        self.seq = 0

    def out(self, type: str, payload: dict | None = None, *, reply_to: str | None = None) -> dict:
        payload = dict(payload or {})
        if not self.v2:
            return {'type': type, **payload}
        self.seq += 1
        if type in ACK_ALIASES:                  # lap_ack/response_ack -> generic ack
            payload = {'id': reply_to or '', 'of': ACK_ALIASES[type], **payload}
            type = 'ack'
        return encode(type, payload, sender=self.sender, session=self.session, seq=self.seq)


# --------------------------------------------------------------------------- reliable delivery

@dataclass(slots=True)
class _Outgoing:
    message: Any
    expires_at: float
    next_at: float
    attempts: int = 0


class ReliableChannel:
    """Retry-until-acked outbox plus receiver-side dedup. No I/O; the transport owns the loop.

    Sender: `send(id, message)`, then each tick `for id, message in due(): transmit(message)`;
    `ack(id)` when the peer acknowledges. Retries back off exponentially
    (base * 2**attempt, capped) and give up at `ttl` seconds or `max_attempts`.
    Receiver: `seen(id)` is True for a duplicate; `remember(id, reply)` caches the reply so a
    duplicate is re-acked without being processed twice.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, base_delay: float = 0.5, max_delay: float = 8.0,
                 ttl: float = 60.0, max_attempts: int = 12, outbox_limit: int = 256, dedup_limit: int = 2048,
                 jitter: Callable[[float], float] | None = None):
        self.clock = clock
        self.base_delay, self.max_delay, self.ttl, self.max_attempts = base_delay, max_delay, ttl, max_attempts
        self.outbox_limit, self.dedup_limit = outbox_limit, dedup_limit
        self.jitter = jitter or (lambda delay: delay)
        self._outbox: OrderedDict[str, _Outgoing] = OrderedDict()
        self._expired: list[str] = []
        self._seen: OrderedDict[str, Any] = OrderedDict()
        self.dropped = 0

    # sender side
    def send(self, id: str, message: Any, *, ttl: float | None = None) -> bool:
        if id in self._outbox:
            return True                          # already queued: idempotent
        if len(self._outbox) >= self.outbox_limit:
            self.dropped += 1
            return False
        now = self.clock()
        self._outbox[id] = _Outgoing(message, now + (self.ttl if ttl is None else ttl), now)
        return True

    def due(self, now: float | None = None) -> list[tuple[str, Any]]:
        now = self.clock() if now is None else now
        ready: list[tuple[str, Any]] = []
        for id, item in list(self._outbox.items()):
            if now >= item.expires_at or item.attempts >= self.max_attempts:
                del self._outbox[id]
                self._expired.append(id)
            elif now >= item.next_at:
                item.next_at = now + self.jitter(min(self.max_delay, self.base_delay * 2 ** item.attempts))
                item.attempts += 1
                ready.append((id, item.message))
        return ready

    def ack(self, id: str) -> bool:
        return self._outbox.pop(id, None) is not None

    def reset_backoff(self) -> None:
        """After a reconnect everything pending is retransmitted immediately."""
        now = self.clock()
        for item in self._outbox.values():
            item.next_at = now

    def expired(self) -> list[str]:
        """Ids given up on since the last call."""
        gone, self._expired = self._expired, []
        return gone

    def pending(self) -> int:
        return len(self._outbox)

    def attempts(self, id: str) -> int:
        item = self._outbox.get(id)
        return item.attempts if item else 0

    # receiver side
    def seen(self, id: str) -> bool:
        if id in self._seen:
            self._seen.move_to_end(id)
            return True
        self._seen[id] = None
        while len(self._seen) > self.dedup_limit:
            self._seen.popitem(last=False)
        return False

    def remember(self, id: str, reply: Any) -> None:
        if id in self._seen:
            self._seen[id] = reply

    def reply_for(self, id: str) -> Any:
        return self._seen.get(id)
