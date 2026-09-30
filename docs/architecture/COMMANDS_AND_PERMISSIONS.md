# Commands and permissions

How state-changing operations are named, authorised, audited and answered. Sources: `backend/app/core/commands.py`,
`core/errors.py`, `core/permissions.py`, `commands_catalog.py`, `control.py`, `operations.py`, `api.py`; ADRs 0004, 0005,
0007. The full generated command and capability tables are in [CONTRACTS.md](CONTRACTS.md) (do not copy them here).

## 1. Commands vs queries

| | query | command |
|---|---|---|
| HTTP | plain `GET` (state, sessions, diagnostics, audit, capabilities, ...) | `POST /api/commands/{id}`, or a legacy route that shares the same operation |
| Changes state or is visible outside the app | no | yes |
| Capability check, rate limit, schema, audit | no (local pairing token only) | yes, in `dispatch()` |
| Answer | route-specific JSON | always a `CommandResult` |

Read-only calls must never change service state (`tests/test_foundation_api.py::test_read_only_calls_never_change_service_state`).

## 2. Definitions

`core/commands.py`:

| type | fields |
|---|---|
| `CommandDef` (frozen) | `id`, `capability`, `schema` (Pydantic model), `handler(ctx, body)` (sync or async), `audited=False`, `rate=None` (`(max_calls, per_seconds)`, per principal), `destructive=False`, `description=''` |
| `Ctx` | `principal`, `services` (the `Runtime`; core never inspects it), `audit` (callable sink), `session_id` |
| `CommandResult` | `code: ResultCode`, `message`, `diagnostic`, `data`, `command_id` (fresh uuid), `audit_id`; `.ok`, `.http_status`, `.to_public()` |
| `Empty` | payload schema for parameterless commands |

`COMMANDS` is a `Registry[CommandDef]` (duplicate ids raise at import). `to_public()` adds the JSON schema of the payload;
`GET /api/commands` returns it.

### Result codes to HTTP (`core/errors.HTTP_STATUS`)

| code | HTTP | typical cause |
|---|---|---|
| `ok` | 200 | done |
| `rejected` | 400 | refused by the service |
| `not_authorized` | 403 | principal lacks the capability |
| `invalid_state` | 409 | valid request, wrong moment |
| `conflict` | 409 | clashes with existing state |
| `invalid_input` | 422 | schema failure, missing `confirm`, service-side validation |
| `not_found` | 404 | unknown command id or resource |
| `rate_limited` | 429 | over the command's `rate` |
| `unavailable` | 503 | handler crashed (`diagnostic` = exception type) or a dependency is down |
| `connection_lost` | 503 | used by the frontend for transport failures |
| `timeout` | 504 | used by the frontend for timeouts |

Handlers raise `AppError(code, status, message)` (`AppError.from_status`, `AppError.from_code`); `dispatch()` turns it into a
result. `fastapi` is never imported outside the adapters (`tests/test_architecture.py`).

## 3. Dispatcher order

`core.commands.dispatch(ctx, command_id, payload, *, registry, limiter)`:

1. Unknown id: `not_found` ("Unknown command ..."). Not audited.
2. Capability: `can(ctx.principal, command.capability)`; else `not_authorized` (`diagnostic` = the capability).
3. Rate limit: `limiter.allow((subject or kind, command.id), max, per)`; else `rate_limited`. Note it runs before schema
   validation, so malformed calls also consume the budget.
4. Schema: `command.schema.model_validate(payload)`; else `invalid_input` (`diagnostic` = first 400 chars of the error).
5. Destructive confirm: if `destructive` and `payload['confirm']` is falsy, `invalid_input` with `diagnostic='confirm'`.
6. Handler. `AppError` becomes its own code; a `ValidationError` from a service becomes `invalid_input`; any other exception is
   logged (`command_failed`) and becomes `unavailable` with the exception class name.
7. Audit, only if `command.audited` and `ctx.audit` is set, and for every outcome from step 2 onwards (refusals included):
   row `{id, utc, actor='<kind>:<subject>', capability, command_id, target=payload.target or payload.id or '', payload_hash,
   result_code, message[:200], session_id}`. If the sink raises, `audit_write_failed` is logged and `audit_id` stays `None`; the
   command result is unchanged.

Verified by `tests/test_core_foundation.py::test_dispatcher_validation_capability_rate_audit_and_errors`,
`tests/test_foundation_api.py::test_commands_catalogue_dispatch_codes_and_audit`.

Known gap: `session_id` in the audit row is `runtime.sessions.id` (the recording session, set in `api.command_ctx`). ADR 0007
says group actions carry the group session id; the code does not do that today.

## 4. Calling a command

`POST /api/commands/{id}` with a JSON object body. The response status is the result code's HTTP status and the body is
`CommandResult.to_public()`:

```json
{"code": "ok", "ok": true, "message": "", "diagnostic": null, "data": {"ok": true},
 "command_id": "…", "audit_id": null}
```

The browser is paired first (`POST /api/pair`, cookie `gt7_token`; every other `/api/*` route needs it). All calls through this
endpoint run as `Principal('local', 'operator')`. Frontend: `frontend/src/domain/commands.ts` `run(id, payload)` never throws for
a backend refusal; it returns the `CommandResult`, and a transport failure becomes a local `connection_lost`/`timeout` result.

## 5. The shim pattern

One operation function, several front doors, so a route and its command cannot diverge.

| module | role |
|---|---|
| `control.py` `control_action(runtime, action, value)` | source, audio, session, replay and safe-mode actions; raises `AppError` |
| `operations.py` | `settings_update`, `track_import/select/confirm/restore`, `training_start/stop/retry_lap/restart`, `recovery_action` |
| `commands_catalog.py` | registers a `CommandDef` per operation; handlers only adapt payloads (`_control(action)`, `_intent(action)`, `_svc(method)`) |

Legacy routes that are shims over the same operations:

| route | shares its implementation with |
|---|---|
| `POST /api/control {action, value}` | `session.start/end`, `source.*`, `audio.*`, `engineer.ai_brief`, `safe_mode.leave` (`control_action`) |
| `PUT /api/settings` | `settings.update` (`ops.settings_update`) |
| `PUT /api/track-map`, `POST /api/track-map/{select,confirm,restore}` | `track.import/select/confirm/restore` |
| `POST /api/training/{start,stop,retry-lap,restart}` | `training.*` |
| `POST /api/recovery {action}` | `recovery.live/display/connection/audio` |

Not shims of the dispatcher:

- `POST /api/command {text}` calls `Runtime.command()` directly. `engineer.ask` reaches the same `Runtime.execute` through
  `RuntimeEngineer.ask`.
- The group admin routes (`/api/group/*`, `group/admin.py`) call `GroupService` methods directly. The matching `group.*`,
  `raceControl.*`, `graphics.*` and `branding.update` commands call the same methods, but only the command path is
  audited: a call through the legacy group route writes no `audit_log` row.
- Consequence: the legacy shim routes (`/api/control`, `PUT /api/settings`, track, training and recovery routes) write no
  `audit_log` row even where the equivalent command is `audited`, and the local pairing token is their only guard. Only
  `POST /api/commands/{id}` runs `can()` for the local principal.

## 6. Commands by area

56 commands, 28 audited, 1 destructive (`training.restart`). Rate limits: `audio.speaker_test`, `audio.mic_test` (6 per 60 s),
`engineer.ask` (60 per 60 s), `group.invite` (30 per 60 s), `raceControl.setFlag`, `raceControl.message` (60 per 60 s).

| area | commands | audited | capability |
|---|---|---|---|
| `session` | 7 (`start`, `end`, `mark_incident`, `set_reference`, `set_target`, `box`, `unbox`) | 1 (`end`) | `local.admin` |
| `source` | 6 (`live`, `demo`, `replay`, `replay_pause`, `replay_seek`, `replay_speed`) | 0 | `local.admin` |
| `audio` | 7 | 0 | `local.admin` |
| `engineer` | 2 (`ask`, `ai_brief`) | 0 | `local.admin` |
| `alerts` | 1 (`acknowledge`) | 0 | `local.admin` |
| `track` | 4 | 2 (`restore`, `import`) | `local.admin` |
| `training` | 4 | 1 (`restart`) | `local.admin` |
| `settings` | 1 (`update`) | 1 | `settings.write` |
| `recovery` | 4 (`live`, `display`, `connection`, `audio`) | 4 | `local.admin` |
| `safe_mode` | 1 (`leave`) | 1 | `local.admin` |
| `group` | 10 (`create`, `configure`, `invite`, `admit`, `remove`, `lock`, `session.start/end/finalize/close`) | 10 | `league.configure`, `raceControl.admit`, `raceControl.session` |
| `raceControl` | 4 (`setFlag`, `cancelFlag`, `message`, `decision`) | 4 | `raceControl.setFlag`, `.message`, `.steward` |
| `graphics` | 4 (`saveDraft`, `take`, `clearProgram`, `credential.issue`) | 3 (all but `saveDraft`) | `graphics.edit`, `.take`, `.issueOutput` |
| `branding` | 1 (`update`) | 1 | `branding.edit` |

Per-command capability, audit and rate flags: [CONTRACTS.md, "Commands"](CONTRACTS.md).

### Not mapped yet

The frontend `CommandId` union (`frontend/src/domain/commands.ts`) and the built-in modules in `frontend/src/domain/modules.ts`
name four ids that do not exist in the backend catalogue; calling them returns 404, which `run()` reports as `unavailable`
("not available on the connected backend"):

| id in the frontend | backend state |
|---|---|
| `group.hosting` | not a command. Hosting is `POST /api/group/hosting` (starts/stops the LAN listener, host-only mode) |
| `group.revoke` | not a command. `POST /api/group/revoke` |
| `graphics.focusBattle` | not a command. `POST /api/group/battles/{id}/focus` |
| `branding.asset.upload` | not a command. `POST /api/group/leagues/{id}/assets` |

Other operations with no command: session storage (there is no `sessions.*` command: metadata, correct, archive, retention,
purge, import and export are routes under `/api/sessions/*`, `/api/retention`, `/api/import`), league demo (`/api/group/demo`),
group replay, remote group connection (`/api/group/connection*`), participant entry updates, map edits, battle dismissal,
steward cues and pause, workspace create/share (`saveDraft` covers save only), profiles. `recovery.*` covers only
live, display, connection and audio. The capabilities `sessions.manage`, `sessions.purge`, `raceControl.messageAll` and
`raceControl.zones` are defined but no command uses them.

## 7. Adding a command

See `EXTENDING_THE_APP.md` ("New Race Control command"). In short: payload model, handler, `_def(...)` in
`commands_catalog.py` with an existing capability, `audited=True` for anything privileged, a case in `tests/test_commands.py`,
then `python scripts/gen-contracts.py`.

## 8. Undo policy (ADR 0005)

Only editor state (layouts, graphics draft, branding draft) may have undo. Sent race-control actions (flags, messages,
decisions, takes) have none; a compensating command (`raceControl.cancelFlag`, a superseding decision) is a new, labelled, audited
action. This is a design rule, enforced by the absence of undo commands, not by a test.

## 9. Capabilities and roles

`core/permissions.py`. Capabilities are dot-namespaced ids in the `CAPABILITIES` registry (area, description). Roles are data:

| role | grants |
|---|---|
| `host` | every capability |
| `local` (paired local browser) | every capability except areas `driver` and `overlay` |
| `driver` | `telemetry.publishOwn`, `telemetry.viewOwn`, `driver.respond` |
| `spectator` | `graphics.view`, `.edit`, `.take`, `.issueOutput` |
| `overlay` | `overlay.read` |

The role x capability matrix is in [CONTRACTS.md](CONTRACTS.md).

Rules:

- Check: `can(principal, capability, resource=None)`; an unknown capability raises `KeyError`. Role grant first, then an optional
  `ScopeRule` for that capability.
- Conditional grant: `CONDITIONAL_GRANTS[('driver', 'telemetry.viewAll')] = 'share_traffic_with_drivers'`, granted when
  `principal.flags['share_traffic_with_drivers']` is set (the host enabled traffic sharing).
- Scope rules: `graphics.view/edit/take/issueOutput` need `resource` (a workspace dict) to be owned by or shared with the
  principal; `host` and `local` pass. `overlay.read` needs `principal.scope['workspace_id']` to equal the workspace. A
  `resource` of `None` skips the scope check.
- Pending or removed participants (`status != 'admitted'`, kinds `driver` and `spectator`) hold no capability at all
  (`capabilities_for` returns an empty set).
- The server always enforces. `GET /api/me/capabilities` returns `{principal, capabilities, roles}` for the local principal
  only. ADR 0004 says the group `/me` returns capabilities too, but `GET /group-api/me` currently returns the participant, policy and layout, not a capability list. The frontend `domain/permissions.ts` `can()` only hides or disables UI.
- Group principals are built in `group/principals.py` from the credential; `group/public.py` checks e.g.
  `telemetry.publishOwn` before accepting a driver socket.

### Tests

| test | covers |
|---|---|
| `tests/test_permissions_matrix.py` | role x action matrix for publish, laps, driver responses, workspace edit/take/credential, battle focus, traffic conditional grant, pending participants, overlay/spectator tickets, `test_static_role_table` |
| `tests/test_commands.py` | `test_role_command_matrix`: every role x every command is `not_authorized` exactly when the independent `EXPECTED_ROLES` table says so; `test_catalogue_is_consistent`; race-control and graphics flows with audit |
| `tests/test_core_foundation.py` | `test_role_capability_matrix`, `test_spectator_workspace_scope`, dispatcher behaviour |

`EXPECTED_ROLES` in `tests/test_commands.py` is keyed by capability; a new capability that a command uses must be added there or
the matrix test raises `KeyError`.

## 10. Audit: three different records

| record | where | purpose | lifetime | shape |
|---|---|---|---|---|
| `audit_log` | SQLite table (migration 003) | who did which privileged thing | survives session purge | `id, utc, actor, capability, command_id, target, payload_hash, result_code, message, session_id`; payloads hashed, never stored |
| debug logs | `logs/app.jsonl` | diagnosing the app | rotated (5 x 5 MB), redacted, rate-limited, may be deleted | JSON lines; never audit |
| `group_events` | SQLite table | domain event stream for timeline, replay and broadcast graphics | follows the group session; own retention | no actor, capability or result code |

ADR 0007: debug logs are never audit; audit is written by `dispatch()` for every `audited` command; `group_events` stays the
domain stream and is not the audit store. Query: `GET /api/audit?session=&since=&limit=` (newest first, `limit` up to 1000,
default 200) behind the local pairing token. Group race-control actions reach `audit_log` only through the command path (section 5).
Schema and write path: `STORAGE.md`.
