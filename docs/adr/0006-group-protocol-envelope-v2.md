# 0006. Group protocol envelope v2 with a v1 compatibility window

Status: accepted

## Context
The group WebSocket protocol was ad hoc JSON (`telemetry`, `lap`, `ping`/`pong`, `clock`, `response`,
`*_ack`, `hello`, `state`, `error`) with `version: 1` only inside `Join` and `Packet`. There was no
handshake, no reliability classes, and subscribers received a freshly recomputed snapshot roughly every
200 ms each.

## Decision
`group/protocol.py` defines a versioned envelope
`{v, type, id, ts, sender, session, seq, payload}`, a `hello` handshake that negotiates the protocol and
returns `compatible: false` + `protocol_incompatible` when there is no overlap, a per-role type
allowlist, per-type Pydantic schemas, and two reliability classes:

- **ephemeral** (`telemetry`, fast state): latest-wins, droppable, rate-limited by the publish rate;
- **reliable** (`lap`, `response`, `instruction`, `message`, `decision`, `workspace_taken`): carry
  an `id`, require an `ack` (itself ephemeral and idempotent), retried with backoff until acked or expired, deduplicated by `id`.

State sync today: the host sends the filtered full state (latest-wins) on the publish tick and each browser
subscription frame; a bounded server-side `SnapshotCache` (keyed by publication filter, delay and group revision,
max age 200 ms) lets every subscriber with the same filter share one computed frame instead of recomputing per
subscriber. Deltas are a planned optimisation, not built. v1 messages are converted to v2 internally for one release
and a `DEPRECATION` event (`protocol_v1_client`) is logged when a v1 driver connects. Telemetry ordering uses the
packet's own `sequence`; the envelope `seq` is carried for reliable channels but the host does not yet order by it.
Server-to-driver notices (`instruction`, `message`, `decision`, `workspace_taken`) are registered as reliable types
but still travel inside `state` frames; `ReliableChannel` (retry/backoff/dedup) is used driver-to-host for laps.
Transport specifics stay in `public.py`/`client.py`; `service.py` works on decoded envelopes.

## Consequences
Cloud/relay transports would slot in behind the same envelope (documented in `NETWORKING.md`; nothing built).

Related fix made with this pass: the member client reported `host - client` as the clock offset while the host
applied `source_utc - offset`, mirroring the correction. The client now reports `client - host`
(`group/client.clock_offset_ms`, tested in `tests/test_group_clock.py`); drivers running an older build still send
the old sign until they update.
