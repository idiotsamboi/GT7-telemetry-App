# 0005. Commands vs queries and the `CommandResult` codes

Status: accepted

## Context
`POST /api/control {action}`, `POST /api/command {text}` and ~40 group admin routes mixed validation,
authorization and side effects; the UI inferred success from state changes.

## Decision
State-changing or externally visible operations are **commands** (`core/commands.py`): id, capability,
Pydantic payload schema, handler, `audited`, `rate`, `destructive`. `dispatch()` validates, authorizes,
rate-limits, runs the handler and writes an audit row for audited commands. The result is always a
`CommandResult{code, message, diagnostic, data, command_id, audit_id}` with a fixed vocabulary
(`ok, rejected, not_authorized, invalid_state, invalid_input, timeout, connection_lost, rate_limited,
not_found, conflict, unavailable`) mapped to HTTP in one table (`core/errors.HTTP_STATUS`).
Read-only GETs stay plain queries.

Existing routes are **thin shims over the same operation functions** (`control.py`, `operations.py`), so a
route and its command cannot diverge. New generic endpoint: `POST /api/commands/{id}`.

## Undo policy
Only editor state (layouts, graphics draft, branding draft) may have undo. Sent race-control actions
(flags, messages, decisions, takes) have none; a compensating command (`cancelFlag`, a superseding decision)
is a new, labelled action.

## Consequences
The UI reacts to `code`/`message`; tests assert codes, not status strings.
