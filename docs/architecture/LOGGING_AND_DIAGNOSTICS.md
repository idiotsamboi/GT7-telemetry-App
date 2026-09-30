# Logging and diagnostics

Sources: `backend/app/core/logging_setup.py`, `diagnostics_report.py`, `safe_mode.py`, `api.py`, `control.py`,
`operations.py`, `backend/app/data/recovery.{html,js}`, `frontend/src/domain/clientErrors.ts`. Storage of logs is listed in
`STORAGE.md`; audit is a different record (`COMMANDS_AND_PERMISSIONS.md`, ADR 0007).

## 1. Logging

### Subsystem loggers

`SUBSYSTEMS`: `system`, `network`, `telemetry`, `session`, `race_control`, `broadcast`, `engineer`, `audio`, `storage`, `ai`,
`training`, `ui`. Use `get_logger(name)` (raises `ValueError` for any other name) or, preferably, `log_event`:

```python
import logging
from backend.app.core.logging_setup import log_event

log_event('storage', logging.ERROR, 'storage_open_failed', error=str(error)[:300])
```

`log_event(subsystem, level, event, **details)` logs `event` as the message with `extra={'event': event, 'details': {...}}`;
keep `event` a stable snake_case id and put variable data in `details` (which is redacted by key name). Modules that only need
a logger use `logging.getLogger('<subsystem>')` (`core/commands.py`, `telemetry/bus.py`, `group/public.py`). A few older call sites
still use `logging.exception(...)` on the root logger (`runtime.py`); they land in the file with `sub: "root"` (TECH_DEBT #10).

`setup_logging(log_dir, level, *, console=False, subsystem_levels=None)` is idempotent: it removes the handlers it installed
earlier, sets the root logger to WARNING (so third-party warnings still reach the file) and each subsystem logger to `level`.
`Settings.log_level` (`DEBUG|INFO|WARNING|ERROR`) is applied once in the app lifespan, so changing it needs a restart.
Startup logs `system/startup` (version, data dir name only), `settings_migrated`, `storage_open_failed`, `safe_mode`, and
`shutdown` on a clean stop.

### File format and rotation

`<data>/logs/app.jsonl`, one JSON object per line, `RotatingFileHandler` with 5 MB per file and 5 backups
(`app.jsonl.1` ... `.5`, so at most about 30 MB):

| key | content |
|---|---|
| `t` | UTC ISO time, millisecond precision |
| `lvl` | level name |
| `sub` | logger name (subsystem) |
| `event` | event id, or the message when none was given |
| `details` | redacted dict, only when present |
| `suppressed` | count of identical records dropped since the last one, only when non-zero |
| `exc` | redacted traceback, last 2000 characters, only when present |

### Redaction

`RedactionFilter` runs on every handler (file, console and the error ring) and rewrites the message, `details`, and traceback.

- Key names matching `token|credential|secret|password|passwd|authorization|invite|invitation|cookie|fragment|api[_-]?key`
  have their value replaced by `[redacted]` (unless the value is None, empty or False), recursively through dicts and lists.
- Text patterns: `token|credential|secret|password|authorization|invite|invitation|x-control-token|gt7_token|key` followed by
  `=` or `:`; URL fragments containing `token=`, `credential=` or `key=`; and `Bearer <token>`.
- `tests/test_core_foundation.py::test_redaction_of_secrets`, `::test_logging_writes_redacted_jsonl_and_rate_limits_repeats`.

### Repeat suppression

`RepeatFilter` applies to the file and console handlers, not to the error ring. Only WARNING and above are considered. The key
is (logger, level, event or message). The first record passes; identical records inside `LOG_REPEAT_WINDOW_S` (60 s) are dropped
and counted; the next record after the window carries `suppressed: n`. The table holds at most 512 keys and is cleared when it
overflows. `tests/test_core_foundation.py::test_repeat_filter_reports_suppressed_count`.

### Error ring

`ERRORS` (`ErrorRing`) keeps the last 50 records at ERROR or above (`{t, sub, event, details}`). Diagnostics returns it as
`last_errors`.

### What is never logged

By policy (module docstring): per-frame telemetry at INFO or above, credentials, tokens, invitation keys, overlay URL fragments and
microphone audio. Raw packets at sampled DEBUG are also named in the docstring, but no such logging exists in the code.
Ingest counts errors instead (`parse_errors`, `pipeline_errors`) and logs the first failure only.

## 2. Diagnostics

`GET /api/diagnostics` returns `diagnostics_report.collect(runtime, config)` (read-only, cheap):

| key | content |
|---|---|
| `generated_utc`, `versions` | time; app, parser, protocol, settings schema, DB schema, analysis versions |
| `platform` | OS string, machine, Python version, resolved `performance_profile` |
| `safe_mode` | `SafeMode.to_public()` or `null` |
| `services` | every service's state, detail and metrics (`core.lifecycle`) |
| `receiver` | receiver state plus sequence counters, `parse_errors`, `pipeline_errors`, unexpected senders, source |
| `bus` | per-subscriber calls, errors and durations from `TelemetryBus.metrics_snapshot()` |
| `recorder` | queue, capacity, queue age, `application_drops`, `failed_rows`, `error`, `written` |
| `storage` | `db_bytes`, `wal_bytes`, `free_bytes` |
| `group` | clients, hosting flag, `recording_drops` |
| `health` | rate, CPU (one core), peak RSS, thermal, loop lag, `degraded`, reason |
| `last_errors` | the error ring |
| `features` | feature flag snapshot |
| `settings_summary` | variant, `ui_hz`, `log_level`, `developer_mode`, units |
| `data_dir` | the absolute data directory (not redacted here; this endpoint is behind the local pairing token) |

### Redacted bundle

`POST /api/diagnostics/copy` with `{"include_ips": false}` returns the same data through `redacted_bundle()`:

1. `redact()` on keys and text (same rules as the logs).
2. Path replacement: the resolved data dir becomes `<data>` and the user's home directory `<home>` (longer path first, both
   slash styles).
3. IPv4 addresses are masked to `/24` (`192.168.1.20` becomes `192.168.1.x`); `127.*` and `0.*` are left readable. Unless
   `include_ips` is true.
4. A `redaction` block records what was done: `tokens_removed`, `ips_masked_to_24`, `paths_replaced`.

Limits: only IPv4 is masked (IPv6 addresses and host names pass through), and opting in to IPs never reveals secrets. The UI
error boundary (`ErrorBoundary.tsx`) offers "Copy diagnostics", which calls this endpoint and writes the JSON to the clipboard.

Tests: `tests/test_foundation_api.py::test_diagnostics_bundle_is_redacted` (token, PS5 address and data path absent; masking
flag; opt-in still hides the token).

## 3. Client error reporting

`POST /api/client-errors` `{message (1000), stack (4000), component (100), url (300)}` logs `ui/client_error` at ERROR with the
stack cut to 1500 characters and the URL cut at `#`. Server side limit: 30 per 60 s (429 beyond that). The browser side
(`domain/clientErrors.ts`) sends at most 5 per minute, truncates message to 500 characters, strips token-looking values and URL
fragments, and reports `location.origin + pathname` only. The error boundary calls it; a report never blocks the UI.
`tests/test_foundation_api.py::test_client_errors_are_rate_limited_and_logged_redacted`.

## 4. Developer mode

`Settings.developer_mode` (default off) is the switch. Implemented today:

| piece | behaviour |
|---|---|
| `GET /api/dev/packets?n=` | latest parsed frames (n capped at 50) with values, quality flags, sequence gap, provenance; `raw_hex` is present only when `Settings.raw_capture` is on |
| `GET /api/dev/scenarios` | the demo scenario registry (`telemetry.sources.SCENARIOS`) and the active one |
| bus subscriber `dev_packets` | `rate` mode at 10 Hz; appends to a bounded `Runtime.dev_frames` deque and does nothing unless `developer_mode` is on |
| gating | both routes answer 404 "Developer mode is off" unless the flag is on |
| `settings_summary.developer_mode` | reported in diagnostics |

Tests: `tests/test_foundation_api.py::test_developer_endpoints_are_hidden_until_developer_mode`,
`::test_dev_frame_ring_stays_empty_and_bounded`.

Not implemented: any frontend for it (the frontend only carries the field in its settings type), a state inspector, an
event/audit viewer, a network simulator and a layout inspector (all named in `docs/prompts/CLAUDE_CODE_ARCHITECTURE_PROMPT.md`).
`/api/diagnostics`, `/api/audit` and `/api/state` are always available and are not gated by the flag.

## 5. Safe mode

Code: `backend/app/safe_mode.py` (`decide`, `SafeMode`, `RunMarker`), wired in `api.create_app`.

### Triggers (`decide`, in priority order)

| reason | trigger |
|---|---|
| `forced` | `run.py --safe-mode`, `GT7_SAFE_MODE=1`, or `create_app(safe_mode=True)` |
| `storage_failed` | the database could not be opened; `telemetry-safe.sqlite3` is used instead |
| `settings_invalid` | `Config.recovery_notice` is set (invalid or newer settings file preserved, safe defaults loaded) |
| `unclean_shutdown` | the `.running` marker existed at start and `Settings.safe_mode_on_crash` is true (default) |

`RunMarker` writes `<data>/.running` after the runtime has started and removes it on a clean stop, so a hard kill of a dev server
makes the next start a safe start (TECH_DEBT #16). Turn that off with `safe_mode_on_crash: false`.

### Effects

| area | in safe mode |
|---|---|
| Console heartbeat | not sent (`source_loop` skips the send; the socket still binds and receives) |
| Microphone | not auto-started (the hands-free start is skipped) |
| Local AI | `ai_loop` idles |
| Feature flags | Experimental flags are off (`/api/features`, diagnostics) and enforced: `Runtime.feature()` gates tyre-heat, spatial coaching, clean-air advice and the v3 track service; the group service gates battle index, net-order projection and steward cues; sessions/rules read a `SafeModeSettings` view with `trust_c_fields` and local AI forced off. The stored settings are untouched and saving in safe mode never persists the overrides |
| Group hosting and group client | never auto-start in any mode; both are user-initiated (`POST /api/group/hosting`, `/api/group/connection`), so there is nothing to suppress |
| Visibility | `safe_mode` in `/api/state`, `/api/diagnostics`; startup logs `safe_mode` with the reason |

Explicit user actions still work in safe mode (push-to-talk and `mic_enable` start the microphone worker on request).

### Leaving safe mode

`safe_mode.leave` (audited, `local.admin`) or `POST /api/control {"action": "leave_safe_mode"}` sets `runtime.safe_mode = None`.
The heartbeat, microphone and local AI resume on their next loop pass. There is no button for it in the frontend today; call
the command (`POST /api/commands/safe_mode.leave`). Restarting without the marker also clears it.

Tests: `tests/test_foundation_api.py` (`test_forced_safe_mode_blocks_heartbeat_mic_and_ai_until_confirmed`,
`test_unclean_shutdown_marker_triggers_safe_mode_and_clean_stop_clears_it`, `test_crash_detection_can_be_disabled`,
`test_invalid_settings_start_in_safe_mode_with_notice`, `test_storage_failure_falls_back_to_safe_database`).

## 6. Recovery page

`GET /recovery` and `GET /recovery.js` serve static files that do not depend on the React bundle, so recovery works with a
missing or broken dashboard (`tests/e2e/recovery.spec.ts`). The page pairs the browser (`POST /api/pair`, automatic for local
origins) and calls `POST /api/recovery {action}`:

| action | effect (`operations.recovery_action`) |
|---|---|
| `live` | leave host-only mode, drop group replay, switch to the live source |
| `display` | `minimal=false`, `ui_hz=12` |
| `connection` | default UDP bind and ports, heartbeat 1 s, variant A, local origins re-added to `allowed_origins` |
| `audio` | stop speech and mic, default devices, speech on at 80 %, hands-free off |

Recordings, maps, leagues, assets and credentials are retained. The same actions exist as commands `recovery.live`,
`recovery.display`, `recovery.connection`, `recovery.audio` (audited). User-facing text: `docs/RECOVERY.md`.
Recovery does not leave safe mode; that is `safe_mode.leave`.
