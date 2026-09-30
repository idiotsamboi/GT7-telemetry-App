# State management

Three kinds of state, kept apart on purpose:

| Kind | Owner | Persistence | Examples |
|---|---|---|---|
| Backend state | Python objects composed by `Runtime`, SQLite, files under the data dir | disk or process memory | sessions, laps, receiver, services, alerts, settings, group documents |
| Frontend domain data | `frontend/src/domain/*` and `frontend/src/app/liveStore.ts` | none (a cache of what the backend said) | service statuses, capability grants, the session index, notifications, the latest `/ws` snapshot |
| Frontend view state | React components, `frontend/src/app/router.ts`, `domain/units.ts` preference, `ui/tokens.ts` | per browser, `localStorage` under `ui:v1:*` | current route, units preference, motion setting, panel layout, filters, zoom |

Rule: view state never stores domain data, and domain stores never persist. The backend is the single source of truth;
the browser holds a cache and a set of preferences.

## Backend state

`Runtime` (`backend/app/runtime.py`) is the composition root. It owns these state holders:

| State | Holder | Notes |
|---|---|---|
| Settings | `Runtime.settings` / `Config` (`settings.json`) | changed only through `Runtime.update_settings`; schema-versioned (`core/config_migrations.py`) |
| Receiver | `Runtime.receiver` dict, `Runtime.seq` (`Sequence.counts`), `source`, `source_generation` | phase vocabulary: `not_configured, host_only, binding, awaiting_packets, receiving, demo_no_network, replay_no_network, demo_scenario_complete, stale, packets_rejected, socket_error, bind_failed` |
| Session | `Runtime.sessions` (`Sessions`), recorder `Store` | one open session at most; laps in memory bounded to 2000 |
| Derived values | `Runtime.derived_values` (from `DerivedEngine`) | latest only, never recorded |
| Engineer | `Scheduler` (speech arbiter), `Rules`, `Runtime.events` (100), `Runtime.alerts` (`AlertCenter`) | an alert is what the UI lists; the Scheduler still decides what is spoken |
| Track | legacy `TrackMap` and v3 `TrackService` | both are still fed (TECH_DEBT #4, ADR 0009) |
| Health | `Runtime.health_cache`, `Runtime.degraded` | recomputed at 1 Hz by `health_loop` |
| Safe mode | `Runtime.safe_mode` (`SafeMode` or `None`) | decided once at startup, cleared by the user |
| Group | `GroupService` (documents in `group_documents`, credentials, in-memory live samples) | separate tables in the same database file family; see NETWORKING.md |

### Service registry

`runtime_services.build_services(runtime)` returns a `core.lifecycle.ServiceRegistry` with ten services. Every service
reports one `ServiceStatus` (`id, state, since, detail, metrics, last_error, error_code`). States:

`stopped -> starting -> running`, plus `degraded`, `reconnecting`, `failed`, `stopping`.

The registry starts services in dependency order, stops them in reverse with a 5 s bound each, and isolates failures (a
failed dependency marks its dependants `failed / dependency_failed`). The ids, dependencies and probes are tabulated in
`ARCHITECTURE.md`: `recorder, telemetry_receiver, engine, diagnostics, local_ai, track, microphone, group_host,
group_client, overlay_output`.

Read paths: `GET /api/services` (live), `snapshot.services` (a cache refreshed by `health_loop` once per second), and
`GET /api/diagnostics`.

### What `Runtime.snapshot()` contains

The same dict is served by `GET /api/state` and pushed over `/ws`. Top-level keys (35):

| Group | Keys |
|---|---|
| Connection and source | `host_only`, `source`, `stale`, `age_ms`, `status`, `socket_error`, `receiver`, `replay`, `reception_test` |
| Current data | `sample` (`Sample.json()` or `null`), `car`, `derived`, `trace` (600), `history` (600) |
| Session | `session_id`, `report`, `fuel`, `box`, `events` (newest 20), `subtitle` |
| Analysis | `live_delta`, `live_analysis`, `coaching`, `tyre_heat`, `local_ai`, `training` |
| Track | `track_selection` (legacy map), `track` (v3 service snapshot) |
| Truth | `race_flags` = `{available: false, reason: 'Not transmitted by GT7 UDP'}` |
| Platform | `health`, `audio`, `services`, `alerts` (newest 20 active), `safe_mode` (public form or `null`), `recovery_notice` |

`stale` is true when no sample has arrived within `stale_seconds` (default 2 s). `live_delta`, `live_analysis` and
`tyre_heat` carry the same `stale` flag. `derived` is the last result of the 20 Hz derived evaluation. `safe_mode` is
`{active, reason, message, detail, since}` when set.

Delivery: `/ws` builds a fresh snapshot for each client loop iteration at `effective_ui_hz()` (default 12, 8 in LOW_POWER,
4 while degraded), with a 1 s send timeout. There is no publisher queue and no shared snapshot on this path.

## Frontend domain layer

```
src/domain/http.ts           the only fetch(); AppError; JSON; timeout and abort; retries only for idempotent GETs
src/domain/api/*.ts          one client per backend area: control, diagnostics, engineer, graphics, group,
                             platform, sessions, settings, tracks, training
src/domain/commands.ts       run(id, payload) -> CommandResult over POST /api/commands/{id}; never throws for a refusal
src/domain/permissions.ts    capability ids (mirrors core/permissions.py)
src/domain/channels*.ts      channel catalogue (generated from GET /api/channels)
src/domain/units.ts          unit conversion + the units preference (view state)
src/domain/stores/*          domain stores
src/domain/clientErrors.ts   POST /api/client-errors reporting
```

`*.generated.ts` files (`channels`, `commands`, `capabilities`, `graphics`) come from `scripts/gen-contracts.py`;
`tests/test_contracts_fresh.py` fails when they drift.

### Stores

`src/app/store.ts` is a tiny external store (`createStore`, `useStore(store, selector, equality)` on
`useSyncExternalStore`, `shallowEqual`); no Redux or Zustand.

| Store | File | Fed by | Start |
|---|---|---|---|
| `liveStore` | `app/liveStore.ts` | `/ws` messages via `app/liveConnection.ts` (`startLiveConnection()`, one singleton socket, 1.5 s reconnect, marks `stale` on close instead of clearing) | `startLiveConnection()` |
| `servicesStore` | `domain/stores/servicesStore.ts` | `services` inside the live snapshot, else polls `GET /api/services` every 2.5 s while the tab is visible | `startServices()` (idempotent, returns a stop function) |
| `notificationsStore` | `domain/stores/notificationsStore.ts` | command results (`onResult`), plus `notify()`; keeps the last 50 | `startNotifications()` |
| `capabilitiesStore` | `domain/stores/capabilitiesStore.ts` | `GET /api/me/capabilities`; falls back to the local-operator set until loaded | `refreshCapabilities()` |
| `sessionsStore` | `domain/stores/sessionsStore.ts` | `GET /api/sessions`, on demand, in-flight de-duplication | `refreshSessions()` when a view needs it |
| `liveSelectors` | `domain/stores/liveSelectors.ts` | typed slice selectors over `liveStore` | none |

Stores that must be started once at boot: the live connection, `startServices`, `startNotifications` and
`refreshCapabilities`. `domain/stores/index.ts` only re-exports the store modules; it starts nothing. Current state of
the code: `main.tsx` uses the router, the error boundaries and `domain/api`, but does **not yet** call any of these start
functions; it still opens its own `/ws` socket in an effect and keeps the payload in component state, and
`installGlobalErrorReporting()` has no caller. The stores are ready and are intended to replace that (see
`docs/UI_MIGRATION_MAP.md`); when wiring them, remove the old socket so a client has exactly one `/ws` connection.

### View state

| What | Where | Key |
|---|---|---|
| Current route | `app/router.ts` (hash routes such as `#/driver/pit-wall/live`, `#/broadcast/studio`, `#/settings/audio`; workspaces `driver`, `broadcast`, `settings`, `pair`) | `ui:v1:lastRoute` |
| Units preference | `domain/units.ts` | `ui:v1:units` |
| Motion (`full`, `data`, `off`) | `ui/tokens.ts` | `ui:v1:motion` |
| Wheel dash page visibility | `WheelDash.tsx` (legacy, not namespaced) | `wheelPages` |
| Shortcuts | `app/shortcuts.ts` in-memory registry, scopes `global, broadcast, driver, page, context` | none |

All `localStorage` access is wrapped in try/catch, and the pages must render with it empty. Only `/group`, `/overlay/*`
and `/recovery` are separate pages outside the hash router. A settings value the backend also stores (units live in both
`Settings.units` and `ui:v1:units`) is a preference, not domain data: the backend copy governs speech, the browser copy
governs display.

## The workspace rule

Services are backend-owned. Navigating the UI (switching workspace, page or tab) never starts or stops a service; only an
explicit command does (`source.*`, `audio.*`, `session.*`, `group.hosting`, ...). Reads are pure. This is asserted by
`tests/test_foundation_api.py::test_read_only_calls_never_change_service_state`, which calls fifteen read endpoints and
requires the `/api/services` states to be identical afterwards. ADR 0008 records the decision. Consequences: closing a
panel does not stop the microphone, opening the Broadcast workspace does not start hosting, and the recorder is
unaffected by anything the UI does.

## Error boundaries and client errors

- `ui/ErrorBoundary.tsx` has three variants: `page` (fills the view, wraps each page in `main.tsx`), `panel` (an inline card,
  used around the circuit map and similar), and `overlay` (a bare "Graphics unavailable" message for OBS). Each instance
  owns its own state, so an overlay crash never touches the editor. Retry re-mounts the children; Copy diagnostics fetches
  the redacted bundle (`POST /api/diagnostics/copy`) and puts it on the clipboard.
- `componentDidCatch` calls `reportClientError` (`domain/clientErrors.ts`): at most 5 reports per minute in the browser,
  message truncated to 500 characters and stack to 4000, tokens and the URL fragment scrubbed (overlay credentials live in
  the fragment), URL reduced to origin plus path.
- The backend endpoint `POST /api/client-errors` accepts `{message (1000), stack (4000), component (100), url (300)}`, is
  rate-limited to 30 per 60 s, and logs a `client_error` event on the `ui` logger; the log redactor runs on top. Reports
  end up in the diagnostics bundle's `last_errors`.
- Unhandled exceptions and promise rejections are reported by `installGlobalErrorReporting()` once it is called at boot
  (see above: not yet called).
