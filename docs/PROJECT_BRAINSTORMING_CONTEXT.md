# GT7 Race Engineer Backend Frontend and Brainstorming Context

Review date: 2026-09-30. This brief describes the current working tree, including substantial uncommitted development. It is intended to give an AI enough context to brainstorm realistic improvements without confusing planned features, partial infrastructure, and working product behavior.

Source code takes precedence over older documentation. This is an architecture and capability review, not a security certification or a claim that every execution path has been validated. The companion `PROJECT_REVIEW_FILE_INDEX.md` indexes 362 source, test, configuration, documentation and reference files. Dependencies, compiled distributions, release binaries, runtime databases, credentials, personal recordings and model weights were excluded from content review. Screenshots were inventoried, not visually revalidated.

## 1 How to use this document with an AI

For a short brainstorming session, supply sections 2, 3, 8, 9 and 12. For architectural or implementation planning, supply the whole document. Add the file index only when locating implementation files matters; avoid spending the context window on dependencies, binaries or raw recordings.

Use these status meanings throughout:

- **Active:** code is connected to a current runtime or UI path. This does not imply production or hardware acceptance.
- **Partial:** useful functionality exists but a significant implementation, integration or validation gap remains.
- **Foundation:** types, registries, helpers or tests exist; complete user-facing integration is not established.
- **Unavailable:** the required fact is not supplied by the player telemetry stream and cannot be truthfully presented as a reported fact.
- **Proposal:** a possible future improvement, not existing functionality.

The application has a strong local-first telemetry and recording foundation, a broad driver interface, and substantial league/broadcast functionality. Its main architectural challenge is finishing integration across old and new subsystems while preserving recording reliability and data provenance.

## 2 Compact project context

GT7 Race Engineer is an independent local application for Gran Turismo 7 on PS5. It receives encrypted player-car UDP telemetry, records sessions, calculates driving and fuel metrics, speaks offline engineer responses, learns and recognizes tracks, and presents a React dashboard. An optional group service aggregates telemetry forwarded by participating drivers for Race Control and OBS graphics.

The backend is Python with FastAPI, Uvicorn, Pydantic, asyncio, SQLite and PyCryptodome. Optional components include Vosk and sounddevice for voice input, system speech/eSpeak/Piper for output, and a local llama-server running a small Qwen model for selecting calculated briefing observations. The frontend is React 19, TypeScript 5.9 and Vite 6, with uPlot, Lucide and GSAP. Desktop launchers wrap the web interface using pywebview.

It runs locally without a cloud account or hosted AI API. Windows is the development platform; Linux and ARM64 packaging exist. The historical Orange Pi 4 GB ceiling was dropped in project status notes, although installation documentation still references that device. Sustained board performance is not established.

The active code has both legacy learned track maps and a newer world-coordinate track recognizer. The new recognizer feeds live spatial coaching and group calculations; it is no longer dormant. The old map system remains responsible for important map UI and stored revision behavior.

The frontend has hash routing and centralized HTTP adapters, but the main dashboard still owns one full WebSocket snapshot in React state. New slice stores and a singleton connection module are present without replacing that main path. Do not assume the larger UI redesign specification has shipped.

The player stream does not expose opponents, official flags, penalties, tyre wear, tyre compound, official sectors, official lap validity, dependable track identity or confirmed race finish. Group-derived standings require other drivers to participate and share data. Race Control flags and steward decisions are operator-authored application facts, not official GT7 telemetry.

## 3 Product boundaries and data truth

| Data category | Examples | What an AI must preserve |
|---|---|---|
| Reported player telemetry | Position, speed, RPM, pedals, fuel, lap counter, completed lap timing, tyre surface temperatures | Keep field availability, packet variant and stale state attached to the value |
| Calculated observation | Fuel burn, pace consistency, delta, braking episode, heat rate, battle score | Label method, confidence and prerequisites; it is not an official game measurement |
| Experimental interpretation | Undocumented extension fields, including C timing | Respect opt-in interpretation and capability labels |
| User-authored fact | Track confirmation, race length, pit-loss assumption, flag, penalty decision | Identify the user/host as the source |
| Shared driver observation | Other participating cars' position and permitted telemetry | Respect admission, consent, publication categories and latency |
| Unavailable fact | Tyre wear, official validity, unshared opponents, official race-control flags | Show unavailable, not zero or an invented estimate |
| Synthetic or replay data | Demo races, recorded playback, imported recordings | Never present as current live PS5 evidence |

An application-clean lap means its local quality checks passed. It does not establish official game validity, track-limit compliance, identical setup, identical weather or equal tyre conditions. A driven path is not an ideal racing line or surveyed track boundary.

## 4 Architecture and data flow

```text
PS5 player telemetry
  -> UDP socket and heartbeat owned by Runtime
  -> Salsa20 decrypt, variant parser and packet ordering checks
  -> Sample plus normalized TelemetryFrame metadata
  -> synchronous in-process TelemetryBus
       -> legacy track map and training capture
       -> v3 track recognition and progress projection
       -> live delta and trailing analysis
       -> session/lap segmentation -> bounded SQLite writer queue
       -> spatial coaching, tyre heat and engineer rules
       -> derived channels
  -> current runtime snapshot -> local /ws -> React driver dashboard
  -> optional driver publisher -> group host -> filtered/delayed group views
                                             -> Race Control and OBS output

Typed or spoken question -> intent -> rules/calculated evidence/templates
                        -> speech scheduler -> local TTS
Optional local model -> selects supplied evidence IDs -> validated briefing
```

Demo and replay enter the same sample consumption path with distinct provenance. Frontend navigation does not own the recorder. Closing or changing a panel should not stop telemetry acquisition.

The telemetry bus catches subscriber exceptions and continues later subscribers. It is synchronous, however: a slow subscriber can still delay ingestion. This is failure isolation, not CPU/process isolation. Subscription ordering currently preserves legacy behavior because session metadata depends on track work performed earlier in the same frame.

Primary concurrency boundaries are asyncio service loops, one telemetry database writer thread, threaded queries/analysis and speech, a microphone worker process, an isolated image decoder process, and the optional llama-server subprocess. Service wrappers expose common health states but much of the loop logic remains on `Runtime`.

Sources: `backend/app/runtime.py`, `runtime_services.py`, `telemetry/bus.py`, `api.py`, `group/client.py`, `group/public.py`.

## 5 Backend outline

### 5.1 Launch configuration and lifecycle

| Area | Files | Responsibility and current boundary |
|---|---|---|
| CLI/server | `run.py` | Run service, diagnostics, isolated connection test, source/data-directory options |
| Windows application | `windows_app.py`, root VBS launchers | Browser/native launch, interpreter recovery, self-tests and packaged startup |
| Linux desktop | `desktop.py`, `scripts/desktop-launch.sh` | Native desktop wrapper and Linux startup |
| Configuration | `config.py`, `core/config_migrations.py` | Pydantic settings, validation, version migration, atomic writes and invalid-file preservation |
| Runtime composition | `runtime.py`, `runtime_services.py`, `core/lifecycle.py` | Service startup/stop order, receiver, analysis loops, health, speech and state |
| Recovery | `safe_mode.py`, `operations.py`, `data/recovery.html`, `data/recovery.js` | Standalone recovery UI and controlled restoration after failure |
| Discoverability | `modules.py`, `core/registry.py`, `core/features.py` | Metadata describing modules, features, commands, services and capabilities |

Source installations default to `data/`; `--data` selects a different location. Packaged launchers use platform-specific application data directories. An unclean-shutdown `.running` marker can trigger safe mode; this is relevant during development when a server is forcibly stopped.

Version information is inconsistent across the tree: the current central backend constant is `0.3.0-beta`, the frontend package reports `1.0.0`, and existing release archives include `1.3.0`. These are not interchangeable indicators of feature parity. Database schema is 3, settings schema is 2, and group envelope protocol is 2 with compatibility support for 1.

### 5.2 Telemetry acquisition and normalized data

`telemetry/parser.py` owns explicit little-endian field offsets, Salsa20 decoding, variant detection, `Sample`, sequence checks and synthetic sample construction. `telemetry/__init__.py` preserves compatibility imports after the former single-file module was split.

Supported packet lengths are A 296 bytes, B 316, tilde 344 and C 368. Nominal live reception is approximately 60 Hz; heartbeat timing requests/maintains the stream and does not set its sample rate. Default receive port is UDP 33740, with heartbeats to the configured PS5 on UDP 33739.

Receiver handling includes sender filtering, malformed packet classification, duplicate/reordering/gap counters, reconnects, stale state and port-owner diagnostics. One receiver owns the local telemetry port. A separate diagnostic connection test should not compete with the running receiver.

`telemetry/frame.py` wraps a parsed sample with immutable metadata such as monotonic time, UTC, provenance, variant, parser version and quality. Its values dictionary is shared with the original sample and is conventionally read-only, not deeply immutable. Channel definitions distinguish reported, calculated, experimental and unavailable data.

`telemetry/derived.py` provides derived channels such as pedal rates, wheel speeds and gated slip estimates. `telemetry/units.py` defines canonical/display conversions. Those foundations do not mean every existing panel obeys configurable units; current UI still contains explicit km/h, litres and Celsius labels.

`telemetry/sources.py` contains source protocols and deterministic scenarios. Live/free-demo/replay orchestration still resides substantially in `Runtime.source_loop`; this is not a complete set of independently replaceable source services.

### 5.3 Sessions recording and persistence

`sessions.py` segments sessions and laps, tracks partial/invalid-for-comparison data, manages source/car/lap resets and incrementally builds reports. UUIDs distinguish laps even when game lap numbers repeat. Opening laps are partial. Manual end means user-completed; prolonged UDP silence means interrupted, not confirmed race finish.

`storage/store.py` owns the telemetry writer and retains legacy query methods. SQLite uses WAL and `synchronous=NORMAL`; sample writes are queued, batched and counted. The recording queue drops new work when full and reports losses. A disk transaction failure can lose that batch while live processing continues. Neither queueing nor WAL promises lossless recovery from power failure.

Newer storage modules add typed repository interfaces, paging models, retention selection, export registries, audit operations, schema migration and a data-directory map. Some HTTP paths still use legacy `Store` methods and inline queries. Do not assume the new repositories have replaced every old endpoint.

| Persisted item | Location or owner |
|---|---|
| Settings and browser pairing secret | `settings.json`, `control-token` |
| Samples, sessions, laps, events, profiles, audit and group tables | `telemetry.sqlite3` and WAL companions |
| Learned maps and revisions | `track-maps/` |
| User world-coordinate models | `track-models/`; optional `track-models-user/` extension |
| Training captures | `track-training/` |
| League media | `league-assets/` |
| Generated export bundles | `exports/` |
| Rotating structured diagnostics | `logs/` |
| Disposable analysis cache location | `cache/analysis/` |

The `AnalysisCache` implementation exists, but no active backend call site constructing it was found in this review. Treat it as foundation rather than a proven acceleration of current report/comparison requests.

Retention APIs archive records; archive is reversible and does not free their disk space. Purge is a separate operation restricted to archived, ended, unprotected sessions, with recording stopped and a required confirmation string. Freed SQLite pages are reused; shrinking the database requires separate offline maintenance. The richer retention policy helper is not equivalent to the simpler current HTTP retention implementation.

### 5.4 Analytics strategy and coaching

| Component | Active responsibility | Important limits |
|---|---|---|
| `analytics.py` | Pace summaries, fuel prediction, downsampling, spatial lap alignment, braking episodes and improvement observations | Comparability and data-quality gates; bounded inputs; analysis runs in threads |
| `live_analysis.py` | Trailing live metrics and nonintrusive reception test | Short window; speed-derived acceleration is not a full vehicle physics model |
| `live_delta.py` | Approximate forward-window position alignment to a clean lap | Legacy 1,500-point/five-minute-scale bound; 15 m corridor; does not use the whole v3 coaching system |
| `spatial_coaching.py` | Distance-binned lap trace, braking onset/minimum/exit analysis and corner comparisons | Needs locked track geometry and reference coverage; current live voice path is more complete than recorded-session UI |
| `tyre_heat.py` | Smoothed tyre heat-rate/anomaly tracking with suppression and hysteresis | Surface temperature only; cannot determine wear or compound |
| `clean_air.py` | Compare candidate pit timing using shared traffic and rejoin estimates | Requires group traffic sharing and usable timing/strategy assumptions |
| `group/pit.py`, `group/projection.py` | Pit-stop evidence, estimated pit loss/refuel behavior and projected net order | Heuristic pit detection and conditional estimates; not game-reported pit events |

Fuel prediction uses a median of recent usable positive lap burns and needs at least three qualifying laps. Partial, gapped or refuel-contaminated laps are excluded. Race length and reserve remain configured assumptions.

Fuel scenarios compare a saving branch with a splash-stop branch. Saving feasibility uses a configured maximum; stop evaluation needs a known or supplied pit-loss estimate. Refuel time cannot be claimed without a rate. A learned time/fuel slope needs sufficient comparable variation; fallback assumptions must stay visible.

Spatial coaching is implemented in the runtime and reachable through intent handling, including turn-specific or biggest-loss questions. It is not a complete generalized AI coach. The ordinary fixed request library and extended coaching voice intents are not identical catalogues.

### 5.5 Track identity mapping and training

There are two active systems:

1. **Legacy map system:** `tracks.py` owns learned paths, clean-lap capture, approximate references, confirmation and map revisions. The current map API/UI still depends on it.
2. **World-coordinate system:** `track_service.py`, `track_recognition.py`, `track_model.py`, `track_catalogue.py`, `track_bundle.py`, `track_store.py`, `track_fusion.py`, `track_overlap.py` and `track_geometry.py` support recognition, geometry, projection and offline model preparation. Runtime feeds the recognizer and uses locked progress for spatial features.

The world recognizer works on raw positions and route evidence, with ambiguity handling and manual selection. Projection is throttled to about 5 Hz; intervening progress can be advanced from measured speed. It must not silently treat all layouts sharing a section of road as identical.

The catalogue contains 41 venues and 122 layouts. The world coverage report lists 69 world captures, 29 surveyed layouts, 3 GT7Tracks captures and 21 with no usable model. This totals 101 covered layouts but is a different dataset/meaning from the legacy report's 101 approximate reference outlines. Do not conflate the two or imply all 122 have complete geometry. Elevation and border observations are uneven, and capture paths are not complete track-limit surveys.

`training.py` captures laps for track-model building. The frontend offers a layout picker, roulette selection, capture status and a point-cloud visualizer. Special Stage Route X is explicitly excluded by training operations. Offline scripts build/fuse/evaluate models; recording a training lap is not evidence that a new production bundle has automatically been built and distributed.

Achievement/challenge definitions and pure evaluators exist in `domain/training_defs.py`. A complete persistent progression, challenge and achievements product is not established by those definitions or by the planned UI migration document.

### 5.6 Engineer voice and local model

The engineer is primarily deterministic. `requests.py` contains 100 intent entries with three response forms; `voice.py` handles grammar and aliases; `Runtime.execute` answers using current telemetry and computed evidence. `engineer.py` evaluates rules and arbitrates speech using urgency, expiry, cooldowns, quotas, workload suppression and mute state.

`engineer_service.py` adds a structured interface for answers, briefings and alerts while delegating to existing runtime behavior. Typed alerts and annotations provide newer domain representations; older decision events still coexist with them.

Voice is local to the backend host. Vosk recognition uses a microphone worker, optional hands-free listening or push-to-talk, confidence filtering, playback suppression and device/error handling. Audio output uses supported local engines. A browser on another device is not automatically a remote microphone or speaker endpoint. No raw microphone recording archive is part of the intended workflow.

The optional local AI starts a CPU llama-server with one inference slot and a 1,536-token context. Thread count is `max(2, min(6, cpu_count - 1))`, not the old documented fixed two threads. It selects up to three IDs from supplied calculated observations, validates the result, and rechecks facts before display. Disabled, unavailable or failed inference falls back to deterministic evidence summaries.

There is no implemented hosted LLM provider, autonomous open-ended planner, game-control agent or general conversational memory system. `local_ai_rephrase` exists as a setting/feature label and affects answer-source labeling, but the actual model call inspected is evidence-ID selection; do not advertise arbitrary model-generated spoken rephrasing as completed.

### 5.7 Race Control and group networking

`group/service.py` orchestrates the host; `group/admin.py` exposes local administrative routes; `group/public.py` runs a separate LAN surface; `group/client.py` forwards a driver's allowed data. Supporting modules cover models, principals, persistence, protocol, timing, history, battles, pit detection, projections, steward cues, snapshots, image assets and synthetic demo races.

Main capabilities include leagues/events, invitations, admission, join locking, driver identity/rosters, consent, telemetry sharing, operator flags, scoped messages, acknowledgements, steward decisions, session lifecycle, recorded group replay and 4/8/16-driver rehearsal.

Sharing categories are basic, telemetry, fuel and strategy. Host receipt, public publication and per-user consent are distinct controls. A participating driver must run a telemetry-forwarding app instance; the host does not magically receive the entire GT7 lobby from its own PS5 stream.

The current protocol adds a v2 envelope, handshake, sequence metadata and reliability machinery while accepting v1 compatibility messages. High-rate telemetry is expendable/latest-state data; selected discrete events use acknowledgement/deduplication/retry behavior. Registration as a reliable message type is not a blanket guarantee of durable exactly-once delivery across all paths or crashes.

Group standings and gaps are calculated from the connected field with quality/clock/projection limits. Battle heat is an application score used to help a broadcaster identify action. Steward decisions remain host-authored; automatic cues do not prove fault or official penalties. Pit detection currently falls back to low-speed/start-finish/corner heuristics because the documented bundled pit-lane geometry is absent.

### 5.8 Broadcast outputs and assets

Workspaces separate editable draft from program output. Controls support saving drafts, taking to program, clearing program, placement, selected-driver slots, shared workspaces, styles, delay and scoped output credentials. Branding combines league/event/workspace/graphic settings; session branding is frozen at session start.

The current graphics registry contains **28 templates**, not the older documented 26:

- Timing: timing tower, session bar, fastest lap, class leader, lap-time board, classification strip, session clock.
- Driver/comparison: lower third, selected-car telemetry, head-to-head, fuel level, tyre temperatures, pit board, team roster, speed comparison.
- Race Control: flag banner, message, penalty/investigation, connection status.
- Scene/results: track map, grid/results, podium, league/event slate, sponsor rotation, starting soon, event information.
- New analytical graphics: battle tag and projected order after stops.

There are 10 style presets. A program canvas is 1920 by 1080, with at most 20 graphic layers per workspace. Composite and individual graphic URLs are available; each separate subscription adds backend work. OBS/browser output is transparent and read-only within its credential scope.

League image uploads accept raster formats, are decoded in an isolated worker, and re-encoded for display. Car thumbnails, manufacturer logos and circuit assets are served locally. Their copyright/licence conditions are separate from the application's code and metadata; see `THIRD_PARTY_NOTICES.md` and provenance files before redistribution.

### 5.9 API security and observability

The default admin HTTP listener is loopback port 8000. The optional group listener defaults to 8090 and separates public/group operations from local administration. Origin/host validation, pairing cookies or credentials, scope checks, admission and rate limits constrain access. LAN pairing is authentication, not transport encryption.

The current API includes:

| Surface | Examples |
|---|---|
| Current state | `/api/state`, `/ws`, `/api/health` |
| Configuration and discovery | `/api/settings`, `/api/channels`, `/api/capabilities`, `/api/features`, `/api/modules`, `/api/services` |
| Commands | Legacy `/api/control`, `/api/command`; registered `/api/commands/{command_id}` |
| Sessions and analysis | `/api/sessions`, sample/report/metadata/export subroutes, `/api/import`, `/api/compare`, `/api/profiles` |
| Lifecycle and maintenance | Archive, correction, purge and `/api/retention` |
| Tracks and capture | `/api/tracks`, `/api/track-map` and select/library/confirm/restore, `/api/training/*` |
| Diagnostics | `/api/diagnostics`, redacted diagnostic copy, `/api/client-errors`, `/api/audit`, `/api/alerts`, `/api/storage` |
| Group | Local `/api/group/*`; LAN `/group-api/*`, publish/subscribe sockets, `/group`, `/overlay/{id}` |
| Recovery | `/recovery`, `/recovery.js`, recovery operations |

The command registry adds validation, capability checks, result codes, auditing and rate limits where declared. Legacy routes coexist. The presence of a modern command API should not be interpreted as universal migration of every mutation or event to the new architecture.

## 6 Frontend outline

### 6.1 Stack shell routing and state

`frontend/src/main.tsx` still combines app shell, connection state, driver page logic and many forms. The UI groups modes under Driver and Broadcast using the existing sidebar. `app/router.ts` supplies hash routing, last-route persistence and browser history without an external router library.

Active route families are `#/driver/pit-wall/live|telemetry|analysis|strategy|engineer|sessions`, `#/driver/wheel`, `#/driver/training`, `#/broadcast/race-control`, `#/broadcast/studio` and settings. Pairing is a UI gate. `/group`, `/overlay/{id}` and `/recovery` are separate surfaces rather than ordinary operator tabs.

The main app opens `/ws` after pairing, stores the full message in `useState<any>`, marks it stale on disconnect and retries after 1.5 seconds. It can automatically open Analysis when a session ends. This remains the authoritative mounted connection in the inspected shell.

`app/liveStore.ts`, `app/liveConnection.ts`, `app/store.ts` and `domain/stores/*` provide a foundation for selective subscriptions, persisted preferences and shared state. Their existence does not mean the main dashboard avoids full-tree updates. Wire the replacement deliberately to avoid two simultaneous WebSockets.

### 6.2 Pages and major components

| Surface | Files | Current functionality and boundary |
|---|---|---|
| Live Race | `main.tsx`, `RaceVisuals.tsx`, `Broadcast.tsx` | Player state, car identity, map selection/capture, RPM/speed/pedals, lap timing, delta, fuel, tyre temperatures and radio actions |
| Telemetry | `main.tsx`, `Chart.tsx` | Channel selection, uPlot chart, live metrics, map and bounded recorded-sample overview; not a complete synchronized multichannel workstation |
| Analysis | `main.tsx` | Session/lap summaries, quality notes, comparison selection and computed observations; no complete recorded corner-coaching workflow |
| Strategy | `main.tsx` | Fuel estimate and race assumptions; backend's richer scenarios exceed the dedicated frontend presentation |
| Engineer | `RequestLibrary.tsx`, `LocalBrief.tsx`, `main.tsx` | Typed request, searchable request library, answer/subtitle, evidence briefing, voice/mute/PTT controls and event history |
| Sessions | `main.tsx` | Search/list, selection, import/export, replay and protection; maintenance APIs are broader than visible lifecycle tooling |
| Wheel dashboard | `WheelDash.tsx`, `WheelDash.css` | Compact Race/Timing/Fuel/Tyres/Strategy/Map pages, shift lights, paging and display preferences; currently replaces shell view |
| Training | `Training.tsx`, `TrackVisualizer.tsx`, `RouletteWheel.tsx` | Layout selection, capture progress and geometry visualization; not the full planned progression product |
| Race Control | `GroupControl.tsx`, `RaceDesk.tsx` | Event/session setup, driver desk, admission, instructions, messages, zones, decisions, battle focus, group replay and demo controls |
| Studio | `GroupStudio.tsx`, `LeagueBranding.tsx` | Draft/program monitoring, graphic library, placement, workspace sharing, output URLs, branding and styles |
| Output renderer | `GroupGraphics.tsx`, `GroupGraphics.css` | Public group view and graphic/composition rendering with filtered group state |
| Settings and recovery | `main.tsx`, `ui/ErrorBoundary.tsx`, backend recovery assets | Connection, display, audio, model, profile and diagnostic controls; recovery can operate outside the main React rendering path |

`RaceVisuals.tsx` supplies the shared circuit map renderer. Reuse it for consistency across driver, group and broadcast views rather than introducing another geometry interpretation.

### 6.3 Frontend domain layer and generated contracts

`domain/http.ts` centralizes same-origin requests, parsing, timeouts, cancellation, normalized errors and optional GET retries. Mutations are not automatically retried. `domain/api/*` contains subsystem adapters. Generated channel, command, capability and graphics definitions connect frontend metadata to backend registries through `scripts/gen-contracts.py`.

`domain/types.ts`, units, permissions, panel/module metadata and store selectors create a migration boundary for typed UI work. Large legacy components still use `any`; generated catalogues do not provide complete end-to-end response typing on their own.

`frontend/scripts/check-arch.mjs` checks that domain modules do not import React components and that direct `fetch()` calls remain in the HTTP layer. CSS and `motion.ts` provide responsive styling, semantic colors, transitions and reduced-motion support. uPlot is lazy-loaded; major operator components are still imported by the main bundle.

The migration map and redesign prompts describe more than is implemented. Do not assume command palette, top-bar workspace menus, full timeline production controls, synchronized multichannel telemetry lanes, popouts, or persistent training progression exist simply because they appear in those documents.

## 7 Concrete limits and capacities

These are code bounds/defaults, not promises of comfortable performance at the maximum. Some are configuration ranges; others are hard-coded implementation limits.

| Area | Current bound/default | Consequence |
|---|---|---|
| Player source | One configured PS5 receiver per runtime | Not a passive full-lobby feed |
| UI publication | Default 12 Hz; setting 2–20 Hz | UI cadence differs from full-rate recording |
| Low-power profile | UI default cap 8 Hz; group publishing 5 Hz | Intended to reduce presentation work without changing recording |
| Stale/interrupted | Defaults 2 s / 30 s | Missing packets cannot prove race completion |
| Heartbeat | Default 1 s; configurable 0.25–15 s | Not an input sampling-frequency control |
| Recorder queue | 8,192 jobs | Roughly 136 s of samples at 60 Hz only if all slots were samples and writer stopped; not a durability guarantee |
| Recorder batching | Up to 240 jobs / 200 ms | Buffered/uncommitted data can be lost |
| Live history and trace | 600 entries each | Rolling display window, not full recording |
| Event display | 100 events | UI history differs from persisted history |
| Legacy map capture | 4,096 points, approximately 10 m spacing | Bounded driven path, not a full-resolution survey |
| Legacy live delta | 1,500 points, roughly five-minute window | Long laps may record/map successfully but lack this delta |
| Legacy live delta corridor | 15 m from matching reference segment | Divergence suppresses delta rather than guaranteeing alignment |
| Legacy session list API | Latest 200 sessions | UI list is not unlimited archive browsing |
| Legacy sample API | 10,000 source rows/request; overview downsampled to 1,200 | Long-session exploration needs pagination; overview is not necessarily the entire session |
| Comparison input | 100,000 samples/lap at API gate; spatial work further bounded | Deep analysis cannot accept arbitrarily large laps |
| Bundle import | 32 MiB compressed input plus structural/expanded-content checks | A long recording may export but not fit a later import |
| Export/import | Blocked while local session recording is active | Maintenance workflow must account for recording state |
| Group capacity | Default 16; schema permits 1–32 | 32 is a validation maximum, not established endurance capacity |
| Browser group subscriptions | Maximum 64; 200 ms publish loop | Many OBS browser sources multiply authentication/serialization work |
| Slow group client | 1 s send timeout | Slow viewers disconnect instead of building an unbounded send queue |
| Group wire message | 32,768 bytes | Forwarded messages must stay compact |
| Group WebSocket tickets | 20 s lifetime; maximum 512 pending | Short-lived access setup, not long-term authority |
| Broadcast delay | 0–120 s | Delayed public output should not be mistaken for live driver guidance |
| Workspace | 20 graphics on 1920×1080 canvas | Template count is 28; simultaneous layer limit is 20 |
| Battle computation | Up to 48 pairs; approximately 2 Hz | Heuristic attention ranking, not exhaustive race adjudication |
| Image upload | 5 MiB; PNG/JPEG/WebP; isolated decode | No arbitrary SVG/HTML asset execution |
| Local model | One inference slot, 1,536-token context, 45 s request timeout | Small bounded briefing selector, not a general low-latency copilot |
| Training corpus | 40 MiB configured bound | Capture/build workflow requires bounded data management |
| Retention | Default 90 days | Archive selection does not automatically reclaim bytes |

Additional important limitations:

- **Not game control:** no steering, braking, setup adjustment or console automation is implemented.
- **No full cloud product:** no hosted accounts, managed internet relay, cloud sync, mobile-native app or multi-tenant backend is established.
- **Partial field visibility:** unconnected or non-sharing drivers remain unknown; a complete-field setting cannot manufacture missing telemetry.
- **No official stewarding:** calculated proximity, braking or heat cannot establish blame, track-limit violations or official penalties.
- **No universal geometry guarantee:** pit lanes, alternate routes, reverse layouts, crossings and incomplete models need conservative handling.
- **No universal unit migration:** conversion helpers/settings exist while old panels retain fixed-unit presentation.
- **No universal feature gating:** most feature identifiers are registered and reported, but the reviewed runtime does not consistently consult `is_enabled()` at every feature execution point.
- **No universal threshold wiring:** `tyre_heat_rate_c_s`, `tyre_heat_anomaly_c` and `coaching_min_loss_s` appear in settings, while live algorithms retain constants rather than consuming these settings dynamically.
- **No process-isolated deep analysis:** off-loop threads reduce blocking I/O but do not remove Python CPU contention.
- **No proven maximum endurance capacity:** successful synthetic tests or schema limits do not establish multi-hour real-console, audio, disk-pressure and broadcast reliability.

## 8 Important inconsistencies and unfinished integrations

| Topic | Current evidence | Implication for brainstorming |
|---|---|---|
| Existing `docs/AI_CONTEXT.md` | Says v3 is unwired and later describes v3-dependent active features | Use this review's runtime distinction; preserve old file as historical context |
| Graphics count | Current registry has 28; older user docs say 26 | Generate counts from registries |
| Versioning | Backend 0.3.0-beta, frontend 1.0.0, archives 1.3.0 | Establish a coherent release identifier before promising package parity |
| Track ownership | Both `TrackMap` and `TrackService` are fed; legacy UI remains | Consolidation is a migration project, not a simple deletion |
| Store migration | New typed repositories coexist with old route queries | Extend and connect proven interfaces instead of adding a third storage layer |
| Frontend stores | New store/connection infrastructure exists; `main.tsx` still uses whole-snapshot state | Integrate before claiming re-render optimization is complete |
| Feature switches | Registry/snapshot support outpaces runtime enforcement | Treat feature flags as incomplete controls until integration tests prove them |
| Local AI rephrasing | Setting/source label exists; inspected model call only selects evidence IDs | Keep product claims limited to evidence selection |
| Cache integration | `AnalysisCache` exists without an identified active constructor call | Benchmark only after connecting it to real queries |
| Overlay scaling | Snapshot cache exists, but public subscription re-authenticates through service every 200 ms | Token caching would need explicit expiry/revocation semantics and tests |
| Retention semantics | Archive marks records; newer helper models estimated storage pressure | Do not sell archive as automatic disk cleanup |
| Development data | `.gitignore` now covers `data-preview/` and `data-frontend-dev/` | Old warning that these directories are unignored is stale; synced SQLite risk remains |
| UI redesign | Migration/specification documents describe controls absent from current shell | Separate committed product scope from aspirational design |

There are also large orchestration modules and dense legacy code. `runtime.py`, `group/service.py`, `main.tsx` and complex studio/graphics components are likely change-conflict and maintenance hotspots. This is an architectural inference from their responsibilities, not a measured defect rate.

## 9 Performance reliability and validation status

The repository contains extensive pytest coverage for packet parsing, UDP ordering, sessions, storage, commands, capabilities, telemetry bus/frame/derived channels, track recognition, coaching, strategy, groups, graphics, protocol and recovery. Playwright workflows cover driver UI, group/studio, league demo, track memory, wheel maps, expanded graphics and recovery.

Historical validation JSON and status notes record live reception, speech, packaged Windows tests and synthetic/load measurements. They represent their recorded code/environment, not automatic validation of this working tree. The original architecture audit's 418 tests and older reports of 225/229 tests are historical counts.

The prior group-load report identifies subscriber count as a major scaling variable: many individual browser/overlay connections raised CPU and delivery latency more than increasing demo drivers. Treat those measurements as a reason to rebenchmark current code, not a current service-level guarantee. Composite overlays are a practical way to reduce subscriptions when the production layout permits them.

Checks performed during this review:

- Frontend architecture guard: passed, checking 55 TypeScript/TSX files.
- TypeScript check with `--noEmit --incremental false`: passed.
- Full pytest run: **784 passed, 2 failed, 1 warning in 395.36 seconds**. Failures and follow-up are detailed below.
- No live PS5 drive, physical microphone/speaker test, OBS application acceptance, new release package test, browser screenshot pass or multi-hour hardware soak was performed for this review.

Only documentation is being added by this task; application code and existing uncommitted work are preserved.

### Review validation details

The full run used the project's Python virtual environment and an isolated pytest temporary directory outside OneDrive.

| Check | Result | Interpretation |
|---|---|---|
| `tests/test_battles.py::test_worker_tick_is_fast_at_sixteen_entries` | Average 2.198 ms against a 2 ms budget in the full run | Performance threshold missed on this run; machine load sensitivity is plausible, not proven |
| Same battle test rerun alone | Passed; 1 test in 0.14 s | The miss was not reproduced in isolation; no universal performance guarantee follows |
| `tests/test_contracts_fresh.py::test_generated_contracts_are_fresh` | Failed | Read-only generator comparison shows `docs/architecture/CONTRACTS.md` is missing the `demo_scenario` settings row |
| Frontend architecture | Passed, 55 files | Confirms the guard's import/fetch constraints, not every architectural goal |
| TypeScript no-emit check | Passed | Confirms current type checking, not browser behavior |

The warning was the upstream Starlette/FastAPI TestClient deprecation concerning `httpx`. The stale generated contract was inspected but not regenerated during this review, to keep the deliverable confined to new review documentation. These results replace historical all-green claims for this review snapshot; they do not invalidate older measurements on older code.

## 10 Source navigation guide

| Brainstorming topic | Start with these files |
|---|---|
| Packet support and truthful field availability | `telemetry/parser.py`, `telemetry/frame.py`, `telemetry/derived.py`, `DATA_FIELDS.md`, `PROTOCOL.md` |
| Ingestion performance and isolation | `runtime.py`, `telemetry/bus.py`, `runtime_services.py`, `scripts/bench_ingest.py`, `tests/test_telemetry_bus.py` |
| Reliable session recording | `sessions.py`, `storage/store.py`, `storage/repositories.py`, migrations, storage/reliability tests |
| Track recognition and geometry | `tracks.py`, `track_service.py`, `track_recognition.py`, `track_model.py`, `docs/TRACK_WORLD_COVERAGE.md` |
| Driver coaching and strategy | `spatial_coaching.py`, `tyre_heat.py`, `clean_air.py`, `analytics.py`, `engineer.py`, `voice.py` |
| Local model extension | `local_ai.py`, `engineer_service.py`, `tests/test_local_ai.py` |
| Race Control logic | `group/service.py`, `timing.py`, `history.py`, `pit.py`, `projection.py`, `battles.py`, `steward.py` |
| Network permissions and delivery | `group/public.py`, `client.py`, `protocol.py`, `principals.py`, `core/permissions.py` |
| Broadcast renderers and state | `group/graphics.py`, `state_models.py`, `snapshots.py`, frontend `GroupGraphics.tsx`, `GroupStudio.tsx` |
| Frontend architecture | `frontend/src/main.tsx`, `app/*`, `domain/http.ts`, `domain/api/*`, `domain/stores/*` |
| Build and release | Requirements files, `frontend/package.json`, `scripts/package-*.py`, `core/version.py`, `release/WINDOWS-BETA.md` |
| Planned work versus implemented work | `docs/UI_MIGRATION_MAP.md`, `docs/specs/*`, `docs/prompts/*`, compared against source |

Backend paths in this table are relative to `backend/app/` unless a different root is stated. The complete companion index lists paths, line counts and structural symbols without exposing runtime credentials or recordings.

## 11 Suggested brainstorming priorities

These are proposals based on the review, not existing roadmap commitments.

1. **Finish foundational integration.** Wire real feature gates, configurable thresholds, unit presentation, source labeling and frontend stores. Value: visible settings and architecture become trustworthy. Guardrail: preserve single receiver, full recording cadence and existing truth labels.
2. **Consolidate track authority.** Define one identity/progress owner and migrate learned-map revisions carefully. Value: fewer conflicting layout/lock states. Guardrail: retain user maps and handle missing world models.
3. **Make coaching reviewable after driving.** Connect recorded lap samples, corner comparisons and evidence to Analysis. Value: driver learning beyond transient voice calls. Guardrail: compare compatible laps and explain uncertainty rather than asserting causality.
4. **Build a useful telemetry workstation.** Add a bounded multichannel/lap-series API and synchronized chart/map exploration. Value: fewer requests and better diagnosis of long sessions. Guardrail: no full-database materialization or interference with ingestion.
5. **Improve broadcast scaling.** Measure authentication, serialization and snapshot costs under realistic overlay counts; design revocation-aware caching. Value: more stable OBS sessions. Guardrail: never weaken credential revocation to obtain a benchmark win.
6. **Improve strategy calibration.** Gather trustworthy pit-lane geometry, pit-loss evidence and refuel rates; expose scenario assumptions in the UI. Value: more defensible pit advice. Guardrail: label heuristic/host-supplied values and respect sharing permissions.
7. **Unify release truth.** Reconcile versions, rebuild packages and derive capability counts from registries. Value: user documentation matches delivered software. Guardrail: platform acceptance must be measured on each target.
8. **Consider a richer AI engineer only after evidence interfaces stabilize.** Reuse `EngineerService` and structured evidence to constrain explanations. Value: clearer answers without changing telemetry facts. Guardrail: a hosted provider would be new scope requiring an explicit privacy, cost and connectivity decision.

## 12 Copyable brainstorming prompt

```text
You are a product and software architecture brainstorming partner for GT7 Race Engineer.
Use the attached PROJECT_BRAINSTORMING_CONTEXT.md as a dated description of the
current working tree. Source code takes priority when newer evidence is supplied.

The product is a local-first PS5 GT7 player-telemetry recorder, driver dashboard,
offline spoken engineer, track recognition/training tool, participating-driver
Race Control host and OBS graphics studio. Backend: Python/FastAPI/SQLite/asyncio.
Frontend: React/TypeScript/Vite. It is an independent beta with incomplete migrations.

My brainstorming goal is: [INSERT THE PROBLEM, AUDIENCE OR OUTCOME].
My constraints are: [INSERT TIME, HARDWARE, BUDGET AND NONNEGOTIABLES].

First restate the relevant existing capability and its current limits. Distinguish
active functionality, partial implementation, foundation-only code and proposals.
Do not suggest rebuilding features that already exist; identify the missing extension.

Preserve these constraints:
- One player UDP stream is not a full-lobby feed. Other cars require consenting
  participants to forward data; unshared or absent opponents remain unknown.
- Never invent official race flags, tyre wear/compound/pressure, penalties, official
  lap validity, sectors, weather, race finish or a dependable wire track ID.
- Separate reported, calculated, experimental, user-authored and unavailable facts.
- Preserve live/demo/replay/import provenance, quality, stale state and uncertainty.
- Protect full-rate recording and bounded memory before adding UI or model work.
- Registries, settings, tests and specification documents do not prove runtime wiring.
- Existing release archives are not proof of parity with this source tree.

Propose 5-8 distinct options. For each, give the user benefit, required data,
backend changes, frontend changes, existing modules to reuse, missing prerequisites,
performance/privacy implications, failure behavior, qualitative effort and one
measurable acceptance test. Mark assumptions explicitly.

Recommend a small first experiment, a practical MVP and a later expansion.
Rank by user value, implementation risk and evidence availability. Challenge ideas
that rely on unavailable telemetry. Ask only the few questions that would materially
change the ranking. Brainstorm first; do not modify or implement the project yet.
```
