# 0007. Audit log vs debug logs, and the `group_events` decision

Status: accepted

## Context
Race-control and broadcast actions need an authoritative record of who did what. Group actions already
write `group_events`; debug logs are rotating JSON lines that may be cleared or rate-limited.

## Decision
- **Debug/diagnostic logs** (`data/logs/app.jsonl`, `core/logging_setup.py`) are never audit: they are
  redacted, rate-limited, rotated and may be deleted.
- **Audit** is the `audit_log` table (migration 003): `id, utc, actor, capability, command_id, target,
  payload_hash, result_code, message, session_id`. It is written by `dispatch()` for every `audited`
  command; payloads are hashed, never stored. `GET /api/audit` is local-admin only.
- **`group_events` stays the domain event stream** (timeline, replay and broadcast graphics read it; it
  has its own retention). Group race-control actions are mirrored into `audit_log` through the same
  dispatcher path, with `session_id` = the group session and the `group_events` id in `target`/`message`
  so the two can be joined. `group_events` is not the audit store: it has no actor, capability or result
  code, and its lifetime follows the group session.

## Consequences
One log with a uniform shape lets `/api/audit` and diagnostics query all privileged actions; audit
survives session purge.
