# CLAUDE CODE MASTER PROMPT: Architecture foundation pass (tailored to GT7 Race Engineer)

You're working in the **GT7 Race Engineer** repository. This pass is **not** about new features. It's about **making future development predictable**: clear homes, clear APIs, clear data sources, clear permissions, clear tests. Build the foundation that makes the planned features safe to add, and adapt what already works instead of rewriting it.

**Read first**:
- `docs/AI_CONTEXT.md` (feature map)
- `ARCHITECTURE.md`, `PROTOCOL.md`, `DATA_FIELDS.md`, `docs/RACE_CONTROL.md`
- `docs/specs/ACTION_DIRECTOR_AND_COACHING_SPEC.md` (partly implemented)
- `docs/prompts/CLAUDE_CODE_UI_REDESIGN_PROMPT.md` (in progress)
- `docs/UI_MIGRATION_MAP.md` (if present)

**Coordination rule**: the UI redesign owns the **frontend shell, visuals and routing**. This pass owns the **backend architecture** and the **frontend domain/data layer** (API clients, domain types, stores). Reuse the frontend foundations the redesign already created (`src/app/store.ts`, `liveStore.ts`, `liveConnection.ts`, `router.ts`, `shortcuts.ts`, `src/ui/tokens.*`). Don't duplicate them.

---

## 0. What already exists (verified audit; confirm and extend it before changing anything)

| Concern | Current reality | Verdict for this pass |
|---|---|---|
| Languages/runtime | Backend: Python 3.12, FastAPI, Uvicorn, Pydantic v2, stdlib asyncio/sqlite3/struct/socket; PyCryptodome Salsa20; optional Vosk/sounddevice, eSpeak/Piper/Windows System.Speech, llama-server. Frontend: React 19, TS 5.9, Vite 6, uPlot, lucide-react, GSAP. No router/state libs | Keep the stack. **No new frameworks** (no DI containers, Redux, Celery, Kafka, ORMs) |
| Packaging | `scripts/package-windows.py` (PyInstaller `--collect-submodules backend`, so new subpackages are picked up), `package-linux.py` (ARM64 .deb), pywebview/GTK desktop launchers, `run.py` CLI | New modules must live under `backend/` and import without optional deps. Verify both package scripts still build (at least run their import/self-test paths) |
| Orchestration | `backend/app/runtime.py` (~42 KB) `Runtime` class: five asyncio loops (`source_loop`, `engine_loop`, `health_loop`, `ai_loop`, `track_loop`), `consume()` fans each sample out to sessions, recorder, live_delta, live_analysis, legacy TrackMap, TrackService, spatial coaching, tyre heat, training, engineer rules; `snapshot()` builds the `/ws` payload; `command()` handles intents | **Main refactor target**: extract lifecycle, telemetry bus, and a snapshot builder, *incrementally* (§5, §6). Don't rewrite the loops wholesale |
| Group/Race Control | `backend/app/group/`: `service.py` (~53 KB, largest file), `admin.py` (local `/api/group`), `public.py` (LAN listener, WS subscribe/publish), `client.py` (driver publisher), `models.py` (Pydantic schemas, `GRAPHICS` registry), `repository.py` (SQLite documents/credentials/events/frames), `battles.py`, `history.py`, `pit.py`, `projection.py`, `steward.py`, `timing.py`, `assets.py`, `demo.py` | Good module split already. Add a protocol envelope/versioning (§14), capability permissions (§12) and command results (§11). Split `service.py` only along seams that fall out naturally |
| Telemetry parse | `telemetry.py`: `decrypt_datagram`, `parse()` → `Sample(values: dict, mono, utc, variant, provenance, quality, raw_hex, parser_version, wire_length)`; `FIELDS` offset table; `CAPABILITIES` / `UNSUPPORTED` registries; one parser handles A/B/~/C by length | `Sample.values` **is** the de-facto normalized frame. Formalize it (§7) rather than inventing a parallel model. Keep the hot path allocation-light |
| Sources | Live UDP, synthetic demo, SQLite replay are all switched inside `source_loop` with `self.source` | Extract a `TelemetrySource` protocol (§8) around the existing code paths |
| Persistence | `settings.json` (Pydantic `Settings`, `schema_version=1`, atomic write, invalid-file backup plus safe defaults); `control-token`; `telemetry.sqlite3` WAL (single writer, `PRAGMA user_version=2` migrations in `backend/migrations`); group tables (`group_schema`); `track-maps/`, `track-models/`, `track-training/`, `league-assets/`, `_corpus.jsonl` | Mostly sound. Add a config migration chain (§17), a storage layout doc, and a repository interface (§15) |
| Logging | Essentially none (≈2 `logging` uses) | **Build** structured logging (§20) |
| Diagnostics | `/api/health`, `receiver` state, `health` block (rate, CPU, RSS, thermal, loop lag, storage), `run.py diagnostics`, `/api/capabilities`, reception test | Unify under a `ServiceStatus` registry (§5) plus a diagnostics bundle (§21) |
| Safe mode | `/recovery` standalone page; invalid settings give safe defaults plus a notice; recovery actions | Formalize a `--safe-mode` start (§22), reusing these |
| Registries already present | `telemetry.CAPABILITIES`, `requests.CATALOG` (100 intents), `engineer.RULES`, `group.models.GRAPHICS`, `tracks.json` catalogue, v3 track bundle | Promote them into a consistent registry pattern (§10) instead of creating new parallel ones |
| Frontend data access | `fetch(` is called directly inside 9 components (`main.tsx`, `GroupControl`, `GroupGraphics`, `GroupStudio`, `LeagueBranding`, `RaceDesk`, `RaceVisuals`, `RequestLibrary`, `Training`) | **Build** `src/domain/api/*` clients; components stop calling `fetch` (§24) |
| Tests | ~225 pytest tests (protocol, udp, core, api, group, tracks, training, recovery, …), Playwright e2e | Add boundary tests (§27). Keep everything green |
| Platform | Windows (primary dev) plus Linux/ARM64 .deb. **The Orange Pi 4 GB hard target was dropped by the user**, but ARM64 packaging still ships | Keep a `performance_profile` (AUTO/DESKTOP/LOW_POWER, §25); don't design to a 4 GB ceiling |

**Known technical debt to register** (§29), not necessarily fix now:
- the `runtime.py` god object; `group/service.py` size;
- the dense one-line style in older modules;
- dual track systems (legacy `tracks.py` + v3 `track_service`);
- overlay subscriber scaling (per-tick SQLite re-auth);
- test data SQLite files (`data-frontend-dev/`, 6 GB; `data-preview/`) not gitignored;
- project folder inside OneDrive (WAL on a synced folder); `release/` binaries in the tree;
- stale README/release packages; no logging.

**Truthfulness rule (applies to every model you create).** Every field is `reported`, `calculated`, `user_entered` or `unavailable`. GT7 doesn't provide: position, gaps (except connected-group estimates), official sectors, race flags, tyre wear/pressure/compound, weather, damage, lateral G (unvalidated), official validity. Model these as absent or `None` with an availability reason. **Never add fields that pretend otherwise.** Undocumented C fields stay `experimental` behind `trust_c_fields`.

---

## 1. Rules for this pass
1. **Audit first**: produce `docs/architecture/AUDIT.md` (a concise map: modules, owners, data flows, threads/tasks, persistence, entry points) before refactoring.
2. **Staged migration only**: establish interface → adapt the existing implementation behind it → verify → migrate consumers → remove the legacy path. The app runs and tests pass after every step.
3. **Refactor for a concrete benefit** (a boundary, testability, extension point), never for looks. Don't move files just to match the diagram; move only when a module gains a clear owner.
4. **Hot path discipline**: the UDP receive → parse → record path must not get slower. Benchmark `ingest_datagram` + `consume` before and after (`scripts/soak.py --rate 60`, plus a micro-benchmark). Budget: no regression over 5%.
5. **No big-bang style reformat.** Format only files you substantially change (ruff/black for Python, prettier for TS).
6. **Don't overengineer**: no microservices, message brokers, DI frameworks, event sourcing, or abstractions around trivial functions.

## 2. Target layout (mapped onto the real repo)
Conceptual layers → concrete packages. Create new subpackages only when the pass puts code in them.
```
backend/app/
├── core/                 NEW  lifecycle.py (ServiceStatus/Service/ServiceRegistry), events.py (EventBus + AppEvent),
│                              commands.py (Command/CommandResult/dispatcher), permissions.py (capabilities/roles),
│                              config_migrations.py, logging_setup.py, modules.py (module registry), features.py (flags),
│                              errors.py (error codes), version.py
├── telemetry/            NEW  frame.py (TelemetryFrame contract + channel registry), bus.py (TelemetryBus),
│                              sources.py (TelemetrySource: Live/Demo/Replay adapters), derived.py (derived registry),
│                              units.py. Keep telemetry.py (parser) where it is and re-export it; move later only if useful
├── domain/               NEW  annotations.py, insights.py, alerts.py (Alert model), timing_models.py (shared dataclasses)
├── storage/              NEW  repositories.py (SessionRepository protocol + SQLite adapter wrapping storage.py),
│                              layout.py (data-dir map), exports.py (registry wrapping exporting.py)
├── engineer/             OPTIONAL group rules + scheduler + requests + local_ai behind EngineerService (§19); may stay flat
├── group/                EXISTING  add protocol.py (envelope/versioning), permissions via core.permissions
├── tracks.py, track_*.py EXISTING  (register v3 vs legacy in TECH_DEBT; TrackService already exists)
├── runtime.py            EXISTING  becomes a thin composition root over services (gradually)
└── api.py                EXISTING  routes call services/commands, not internals
frontend/src/
├── app/                  EXISTING (redesign): store, liveStore, liveConnection, router, shortcuts
├── domain/               NEW  types.ts (generated/handwritten mirrors of backend models), api/ (sessions.ts, settings.ts,
│                              control.ts, engineer.ts, tracks.ts, training.ts, group.ts, graphics.ts), channels.ts,
│                              units.ts, permissions.ts, commands.ts (CommandResult handling)
├── ui/                   EXISTING (redesign)
└── pages / components    migrate fetch calls to domain/api
```

## 3. Dependency direction (enforce with a test)
- `core` depends on nothing in the app.
- `telemetry`/`domain`/`storage` depend on `core` only.
- `group`, `engineer`, tracks, training and analytics depend on `core`/`telemetry`/`domain`/`storage`.
- `runtime` composes everything. `api.py`/`group/admin.py`/`group/public.py` are adapters that depend on services.
- **Nothing in `backend/app` imports FastAPI except the adapters** (`api.py`, `group/admin.py`, `group/public.py`). `group/service.py` currently raises `HTTPException` via `fail()`. Replace this with `core.errors.AppError(code, status, message)`, mapped to HTTP in the adapters (staged: `fail()` raises `AppError`; the adapters install an exception handler).
- Frontend: `ui/` and pages may import `domain/`; `domain/` never imports React components.
- **Test** `tests/test_architecture.py`: parse imports with `ast` and assert the allowed edges (core imports no app modules; no module outside the adapters imports `fastapi`; no import cycles among `backend.app.*`). Frontend: a small node script in `npm run check:arch` greps that `src/domain/**` has no `.tsx` imports and that no component calls `fetch(` directly (allowlist during migration, shrinking to zero).

## 4. Application core (`core/`)
Keep it small, not a god object. `runtime.py` stays the composition root.
- `version.py`: app version (single source; read by packaging, `/api/health`, the protocol hello, diagnostics), parser version, protocol version, schema versions.
- `features.py`: `FeatureFlag(id, description, default, stage: experimental|beta|stable, requires_restart)`. Initial flags:
  - `packet_c_interpretations`, mirroring the existing `trust_c_fields` setting (keep the setting as the storage);
  - `v3_track_authority`;
  - `battle_index`, `net_order_projection`, `steward_auto_cues`, `spatial_coaching`, `clean_air_advice`, `tyre_heat_rate`;
  - `local_ai`, `local_ai_rephrase`;
  - `ui_redesign_shell`.

  Exposed read-only at `GET /api/features` and writable through settings.
- **Startup stages** (`run.py`/`api.create_app`):
  1. load config;
  2. validate + migrate (§17);
  3. init logging;
  4. open storage (migrations);
  5. build the service registry;
  6. start configured services;
  7. mount the API/UI.

  A failure at any stage logs a structured error and starts in **safe mode** (§22), never a blank screen.

## 5. Service lifecycle (`core/lifecycle.py`)
```python
class ServiceState(StrEnum):
    STOPPED = "stopped"; STARTING = "starting"; RUNNING = "running"; DEGRADED = "degraded"
    RECONNECTING = "reconnecting"; FAILED = "failed"; STOPPING = "stopping"

@dataclass(slots=True)
class ServiceStatus:
    id: str; state: ServiceState; since: float; detail: str = ""; metrics: dict = field(default_factory=dict)
    last_error: str | None = None; error_code: str | None = None

class Service(Protocol):
    id: str
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def status(self) -> ServiceStatus: ...

class ServiceRegistry:
    def register(self, service, *, depends_on=()): ...
    async def start_all(self): ...      # topological order; one failure marks FAILED and continues others
    async def stop_all(self): ...       # reverse order, bounded timeouts
    def statuses(self) -> list[ServiceStatus]: ...
```
- **Wrap existing subsystems as services**:
  - `telemetry_receiver` (UDP socket + heartbeat from `source_loop`/`ingest_datagram`; its states map from the existing receiver phases);
  - `recorder` (storage writer; READY/RECORDING/FINALIZING/COMPLETE/FAILED exposed in metrics);
  - `engine` (engineer scheduler + speech);
  - `microphone` (the mic worker);
  - `local_ai`;
  - `track` (TrackMap + TrackService maintenance);
  - `group_host` (hosting listener), `group_client` (member publisher), `overlay_output` (public listener subscriptions);
  - `session_indexer` (future; register only when real);
  - `diagnostics` (health loop).
- Each wrapper **delegates** to the existing code. Don't rewrite the loops; move each loop body into its service's `run()` over several commits.
- Expose `GET /api/services` and include `services` in `snapshot()` (small payload). The UI reads service states instead of poking `receiver`/`audio` internals.
- **Workspace rule (mandatory)**: services are backend-owned and never start or stop because of frontend navigation. `tests/test_lifecycle.py` asserts no route/UI API call other than explicit commands changes service state.

## 6. Telemetry pipeline and bus (`telemetry/bus.py`)
The canonical flow (document it as a diagram):
```
UDP datagram ─▶ Receiver (sender check) ─▶ decrypt/validate (telemetry.decrypt_datagram)
  ─▶ parse (telemetry.parse → Sample) ─▶ ordering/dedup (existing seq logic) ─▶ TelemetryFrame
  ─▶ TelemetryBus ─┬─ recorder            (every frame, bounded queue, loss counted)
                   ├─ sessions/laps       (every frame, sync)
                   ├─ derived metrics     (every frame, cheap; or decimated)
                   ├─ track service       (≤20 Hz)
                   ├─ rules/alerts        (every frame, cheap)
                   ├─ analysis (live)     (5 Hz)
                   ├─ group client        (configured 5–10 Hz)
                   └─ UI snapshot         (ui_hz, latest-wins)
```
- **Bus API** (synchronous, in-process, no broker):
  ```python
  class TelemetryBus:
      def subscribe(self, name, handler, *, mode: Literal['every','rate','latest'], hz: float | None = None,
                    critical: bool = False) -> Subscription
      def publish(self, frame: TelemetryFrame) -> None      # called once per accepted frame
      def emit(self, event: TelemetryEvent) -> None         # lap/session/connection/source events
  ```
  - `every`: called inline (keep it cheap; the handler must be ≤ 50 µs).
  - `rate`: decimated by monotonic time.
  - `latest`: sets a slot a consumer reads when ready.
  - **Critical** subscribers (recorder, sessions) run first. A handler exception is caught, logged once per 60 s with the subscriber name, and counted in `bus.metrics`. **It never breaks ingestion or other subscribers.**
- **Events**: `LapCompleted(lap)`, `SessionStarted/Ended`, `SourceChanged(live|demo|replay)`, `ConnectionChanged(state)`, `TrackLocked/Unlocked`, `PitDetected`. The current code infers these inside `consume()`/`sessions.py`; emit them from there.
- **Migration**: replace the explicit fan-out lines in `Runtime.consume()` one consumer at a time with `bus.subscribe(...)` in the composition root. Keep call order identical (recorder and sessions first). Verify with the replay-determinism test (§27).
- **Backpressure**:
  - The recorder keeps its bounded queue with explicit loss accounting (already present).
  - The UI stays latest-state-wins.
  - Group publish keeps the latest frame per tick.
  - No unbounded queues anywhere. Add an assertion test that every `asyncio.Queue`/`deque` in `backend/app` has a `maxsize`/`maxlen` (allowlist exceptions with justification).

## 7. Canonical frame and channel registry (`telemetry/frame.py`)
**Raw vs normalized.** Raw = the encrypted datagram and decrypted bytes (`raw_hex` when `raw_capture`) plus undocumented/experimental fields. Normalized = `TelemetryFrame` consumed by features. Keep both; features never parse bytes.

**`TelemetryFrame`**: a thin, typed view over the existing `Sample`, so the hot path doesn't copy data:
```python
@dataclass(slots=True, frozen=True)
class FrameMeta:
    mono: float; utc: str; packet_id: int | None; variant: str; provenance: Literal['live','demo','replay']
    parser_version: str; wire_length: int | None; quality: tuple[str, ...]; sequence_gap: int | None; duplicate: bool
    source_addr: str | None

class TelemetryFrame:
    __slots__ = ('sample', 'meta')
    def get(self, channel_id: str) -> float | int | list | None     # via channel registry accessor
    @property
    def values(self) -> dict                                         # existing dict (read-only by convention)
```

**Channel registry**: the single source for backend, frontend and docs.
```python
@dataclass(frozen=True)
class Channel:
    id: str                 # e.g. 'speed', 'throttle', 'tyre_temp_fl', 'fuel', 'wheel_speed_rr'
    name: str
    group: Literal['identity','timing','motion','engine','controls','fuel','tyres','wheels','chassis','session','packet']
    unit: str               # canonical SI-ish: m/s, rad/s, °C, L, m, s, ratio 0..1, rpm, bar
    source: Literal['reported','calculated','experimental']
    min_variant: Literal['A','B','~','C']
    accessor: Callable[[dict], Any]          # from Sample.values
    color_role: str | None = None            # 'throttle'|'brake'|'clutch'|... semantic, UI resolves to token
    formatter: str = 'number:1'              # display hint; frontend owns the rendering
    availability: str = ''                   # human reason when None
    sampling: Literal['full','ui','lap'] = 'full'
```
- Populate it from `telemetry.FIELDS`, `CAPABILITIES` and `DATA_FIELDS.md`. Mark every C interpretation `experimental` (gated by the feature flag).
- Unavailable-by-design items (`telemetry.UNSUPPORTED`) register as `Channel(..., source='unavailable')` so the UI can show a proper N/A slot.
- `GET /api/channels` returns the registry (no accessors).
- Generate `frontend/src/domain/channels.generated.ts` with `scripts/gen-contracts.py` (§26). A test fails if the generated file is stale.
- **Derived channels** (`telemetry/derived.py`), registered the same way:
  ```python
  @dataclass(frozen=True)
  class DerivedChannel(Channel):
      depends_on: tuple[str, ...]
      compute: Callable[[TelemetryFrame, DerivedState], Any]   # pure given state; state object per channel
      valid_when: Callable[[TelemetryFrame], bool] = lambda f: True
  ```
  - Initial set, only where the logic exists today:
    - `speed_kmh`;
    - `wheel_speed_*` = rad/s × radius;
    - `slip_ratio_*` (suppressed below 30 km/h);
    - `longitudinal_g` (from `live_analysis`);
    - `throttle_brake_overlap`;
    - `fuel_per_lap` (from `analytics`);
    - `delta` (live_delta / spatial);
    - `steering_rate` (B+).
  - Add `brake_release_rate` and `throttle_application_rate` with tests.
  - **Move the calculations out of UI code** (`WheelDash`, `main.tsx`) into the registry and serve them through the snapshot or the lap-samples endpoint.
- **Packet variants**: keep the single table-driven parser (it's correct and tested). Document variant isolation as `FIELDS[min_variant]` plus null-reset. Don't split it into four parser classes unless a variant needs divergent logic.

## 8. Telemetry sources (`telemetry/sources.py`)
```python
class TelemetrySource(Protocol):
    kind: Literal['live','demo','replay']
    def status(self) -> ServiceStatus: ...
    async def frames(self) -> AsyncIterator[TelemetryFrame]: ...   # or push into the bus
    # replay extras (optional interface): pause(), resume(), seek(record_id|mono), set_speed(x)
```
- Adapters wrap the existing code: `LiveUdpSource` (receiver + heartbeat), `DemoSource` (existing synthetic generator), `ReplaySource` (the SQLite paging in `source_loop`).
- `Runtime.switch(source)` becomes `sources.activate(kind)`. Consumers ask "the current source", never the receiver.
- **Invariants** (tests): replay/demo send no heartbeat; replay/demo never write live track maps, personal bests or the training corpus (already enforced; keep the tests); `provenance` is set by the source, not by consumers.
- **Simulation source for development**: extend `DemoSource` scenarios (seeded and deterministic):
  - `normal_laps`, `lap_transition`, `fuel_burn_and_refuel`, `braking_zones`;
  - `packet_loss_burst`, `out_of_order`, `stream_stale_10s`, `session_end`, `variant_switch_A_to_C`.

  Selectable via `run.py --demo --scenario NAME` and in dev settings. Always labelled SYNTHETIC.

## 9. Units (`telemetry/units.py`, `frontend/src/domain/units.ts`)
- **Canonical internal units**: m/s, m, °C, L, bar, s, rad, rad/s, rpm.
- Convert only at display/export boundaries with explicit functions: `speed(m_s, 'kmh'|'mph')`, `temp(c, 'C'|'F')`, `fuel(l, 'L'|'gal_us'|'gal_uk')`, `distance(m, 'm'|'km'|'mi')`, `pressure(bar, 'bar'|'psi')`.
- User unit preferences are view state (frontend) plus `Settings.units` for server-spoken text (the engineer says "km/h" or "mph").
- **Audit**: `speed_kmh` currently lives in `values`. Keep it as a registered *derived* channel; new code uses `speed` (m/s) internally.
- Tests cover round trips and the engineer phrasing in both unit systems.

## 10. Registry pattern (one pattern, many registries)
Each registry is a module-level `Registry[T]` (`register(item)`, `get(id)`, `all()`, duplicate-id error at import, `to_public()`).

| Registry | Location | Seeds from |
|---|---|---|
| channels, derived channels | `telemetry/frame.py`, `derived.py` | `FIELDS`, `CAPABILITIES` |
| alert rules | `engineer.py` → `domain/alerts.py` rule defs | `engineer.RULES` (+ `tyre_heat`) |
| engineer intents | `requests.py` | `CATALOG` (100 intents) |
| commands | `core/commands.py` | `/api/control` actions, group admin actions |
| capabilities | `core/permissions.py` | the role matrix (§12) |
| graphics templates | `group/models.py` → `graphics/registry.py` (optional move) | `GRAPHICS` (26+) |
| export formats | `storage/exports.py` | the bundle (zip), CSV, JSONL, HTML report |
| panels (frontend) | `frontend/src/domain/panels.ts` | the redesign's panel types |
| achievements/challenges | `training/` (definitions only) | none yet (definitions + evaluator interface) |
| modules | `core/modules.py` | §23 |

## 11. Commands and results (`core/commands.py`)
Separate **commands** (change state or are externally visible) from **queries** (read-only GETs).
```python
class ResultCode(StrEnum):
    OK="ok"; REJECTED="rejected"; NOT_AUTHORIZED="not_authorized"; INVALID_STATE="invalid_state"
    INVALID_INPUT="invalid_input"; TIMEOUT="timeout"; CONNECTION_LOST="connection_lost"
    RATE_LIMITED="rate_limited"; NOT_FOUND="not_found"; CONFLICT="conflict"; UNAVAILABLE="unavailable"

@dataclass(slots=True)
class CommandResult:
    code: ResultCode; message: str; diagnostic: str | None = None; data: dict | None = None
    command_id: str = field(default_factory=uid); audit_id: str | None = None

@dataclass(frozen=True)
class CommandDef:
    id: str                          # 'session.start', 'raceControl.setFlag', 'graphics.take', 'engineer.ask'
    capability: str                  # permission required (§12)
    schema: type[BaseModel]          # payload validation
    handler: Callable[[Ctx, BaseModel], Awaitable[CommandResult]]
    audited: bool = False            # race-control/broadcast/destructive → audit log (§16)
    rate: tuple[int, float] | None = None   # (max, per seconds)
    destructive: bool = False        # requires a confirmation token from UI (ARM→EXECUTE / confirm)
```
- **Dispatcher**: `dispatch(ctx, command_id, payload) → CommandResult`. It validates, checks the capability, applies the rate limit, runs the handler, and writes an audit row when `audited`.
- **Adapters**:
  - `POST /api/commands/{id}` (new, generic).
  - The existing `POST /api/control {action}` and group admin routes keep working by mapping to commands. Staged: existing handlers become command handlers; the routes stay as thin shims.
  - HTTP status comes from the code (`ok`→200, `invalid_input`→422, `not_authorized`→403, `rate_limited`→429, `invalid_state`/`conflict`→409, `not_found`→404, `unavailable`→503).
- **Initial command set** (wrap existing behaviour, no new features):
  - Session: `session.start|end|mark_incident|set_reference|set_target|box|unbox`.
  - Recording and sources: `recording.*` (implicit today; expose status only), `source.live|demo|replay|replay_pause|replay_seek|replay_speed`.
  - Audio and engineer: `audio.mute|resume|ptt_start|ptt_stop|hands_free|speaker_test|mic_test`, `engineer.ask` (text intent), `engineer.ai_brief`.
  - Tracks and training: `track.select|confirm|restore|import`, `training.start|stop|retry|restart`.
  - Storage: `sessions.protect|archive|purge|export|import|update_meta`, `settings.update`, `recovery.*`.
  - Group: `group.create|configure|hosting|session.{start|end|finalize|close}|invite|revoke|admit|remove|lock`.
  - Race control: `raceControl.setFlag|cancelFlag|message|decision|zone.*`.
  - Broadcast: `graphics.saveDraft|take|clearProgram|focusBattle|credential.issue|workspace.share`, `branding.update|asset.upload`.
- **Frontend**: `domain/commands.ts` `run(commandId, payload) → Promise<CommandResult>`. The UI reacts to `code`/`message` (toast or inline) instead of inferring success from state changes.
- **Undo policy**: only editor-type state (layouts, graphics draft, branding draft) gets undo. Sent race-control commands, flags, messages, decisions and takes have **no undo**. They may have a compensating command (e.g. `cancelFlag`, decision `supersedes`), labelled as a new action.

## 12. Capabilities and roles (`core/permissions.py`)
- **Capabilities** (dot-namespaced strings):

  | Area | Capabilities |
  |---|---|
  | local | `local.admin` (the paired local operator; everything in the local API), `settings.write`, `sessions.manage`, `sessions.purge` |
  | telemetry | `telemetry.viewOwn`, `telemetry.viewAll`, `telemetry.publishOwn` |
  | race control | `raceControl.setFlag`, `raceControl.message`, `raceControl.messageAll`, `raceControl.steward`, `raceControl.session`, `raceControl.zones`, `raceControl.admit` |
  | graphics | `graphics.view`, `graphics.edit`, `graphics.take`, `graphics.issueOutput` |
  | league | `league.configure`, `branding.edit` |
  | driver | `driver.respond` (acknowledge, pit intent, …) |
  | overlay | `overlay.read` |

- **Roles are data** (not hardcoded branches):
  - `host`: all group capabilities plus `local.admin` on the host machine.
  - `driver` (member): `telemetry.publishOwn`, `telemetry.viewOwn`, `driver.respond`, and `telemetry.viewAll` only if the host enabled traffic sharing.
  - `spectator`: `graphics.view|edit|take|issueOutput` scoped to own/shared workspaces, plus read of published data.
  - `overlay`: `overlay.read` scoped to one workspace.

  Future roles (steward, commentator, team manager) are new entries in the map.
- **Scopes**: a permission check takes `(principal, capability, resource)`. Resource-level ownership (workspace owner/shared list, own entry) is evaluated by a small `ScopeRule` per capability. This replaces the inline checks in `group/service.py` (`principal['kind'] in (...)`, `p['role']!='spectator'`, workspace owner checks), staged per call site with tests proving identical allow/deny behaviour first.
- **Server always validates.** The frontend gets `GET /api/me/capabilities` (local) and `/group-api/me` includes capabilities. `domain/permissions.ts` exposes `can(cap, resource?)` for hiding and disabling UI. **UI hiding is never the enforcement.**
- **Tests**: a table-driven matrix of every role × every command → expected `ok`/`not_authorized` (reuse the existing group permission tests as seeds).

## 13. Identity model (confirm; mostly exists)
Stable IDs for league, event, group, session (group session + local session UUIDs), participant, entry, driver (`driver_id`), team, car model (`car_id` = GT7 model, **never** a participant identity), track layout (catalogue ID), lap (UUID).
- Display names are mutable attributes.
- Document it in `docs/architecture/DOMAIN_MODEL.md`, with a diagram of the relations.
- Add `team_id` where teams are currently only names in branding (`Branding.teams` gets stable ids; migrate existing name keys).

## 14. Networking boundary and protocol (`group/protocol.py`)
The current group protocol is ad hoc JSON (`telemetry`, `lap`, `ping`/`pong`, `clock`, `response`/`response_ack`, `hello`, `state`, `error`, `lap_ack`), with `version:1` only inside `Join` and `Packet`. Introduce a versioned envelope **with backward compatibility**.
- **Envelope v2**:
  ```json
  {"v":2,"type":"telemetry","id":"<uuid>","ts":<source_utc>,"sender":"<participant_id>","session":"<group_session_id>","seq":123,"payload":{...}}
  ```
- **Hello/handshake**:
  - The client sends `{"type":"hello","payload":{"protocol":[1,2],"app_version":"x.y.z","capabilities":["telemetry.publishOwn",...],"boot_id":…}}`.
  - The server replies with `{"type":"hello","payload":{"protocol":2,"app_version":…,"compatible":true|false,"reason":…,"server_capabilities":[…],"session_id":…}}`.
  - If `compatible:false`, the server closes with a clear error code (`protocol_incompatible`), which the client UI surfaces.
- **Channels by reliability**:
  - **Ephemeral** (`telemetry`, `state_delta` for fast fields): latest-wins, droppable, rate-limited by the existing publish rate.
  - **Reliable** (`lap`, `response`, `instruction`, `message`, `decision`, `ack`, `workspace_taken`): carry `id`, require `ack {id}`, retried with backoff until acked or expired, deduplicated by `id` on the receiver. The existing `lap_ack`/`response_ack` flow is the model; generalize it.
- **State sync**: subscribe → full `snapshot` (slow state: roster, zones, flags, messages, decisions, branding snapshot, workspace program), then `delta` messages for slow changes plus `fast` frames for telemetry/timing at the configured rate. **Don't resend full snapshots every tick** (today the subscribe path recomputes/sends snapshots about every 200 ms; see the load-test note). Keep a server-side snapshot cache per publication filter and delay.
- **Security** (keep and centralize): max message size (existing bounds), type allowlist per role, schema validation with Pydantic per `type`, per-principal rate limits (existing `limit()`), session membership checks, origin checks (browser) vs token auth (native). Credentials are never in logs. Overlay tokens stay in the URL fragment (never the query string).
- **Time**: every message keeps `source_utc`, host receipt time and the clock offset/uncertainty (exists in `boots`). Ordering by `seq`, never by arrival.
- **Transport isolation**: `group/service.py` works on decoded envelopes. WebSocket specifics stay in `public.py`/`client.py`. Unit-test service logic without sockets.
- **Migration**: accept v1 messages for one release (adapter converts v1 → v2 internally). Log a `DEPRECATION` event when a v1 client connects. The demo and tests cover both.
- **Cloud**: out of scope. Document in `NETWORKING.md` how a relay transport would slot in behind the same envelope. Build nothing.

## 15. Storage architecture (`storage/`)
- **Data-dir layout doc** (`docs/architecture/STORAGE.md`), with the current reality:

  | Kind | Location |
  |---|---|
  | configuration | `settings.json` (versioned) |
  | credentials | `control-token`, group credential hashes in SQLite |
  | UI preferences | frontend `localStorage` `ui:v1:*` (per browser) |
  | session data | `telemetry.sqlite3` (sessions/laps/samples/events/profiles) |
  | group data | `group_*` tables |
  | track data | `track-maps/` (legacy), `track-models/` (v3 user), `track-training/`, `_corpus.jsonl` |
  | media | `league-assets/` |
  | logs | `logs/` (new, §20) |
  | exports | user-chosen paths |
  | cache | `cache/` (new, §28) |

- **`SessionRepository` protocol**, wrapping `storage.py` (don't replace the SQL):
  ```python
  class SessionRepository(Protocol):
      def list(self, *, query: SessionQuery) -> Page[SessionSummary]      # index only, no samples
      def get(self, sid) -> SessionDetail | None                          # metadata + laps + report, no samples
      def samples(self, sid, *, after=None, lap_id=None, channels=None, limit=10000) -> Page[SampleRow]
      def lap_series(self, sid, lap_id, channels, points) -> LapSeries    # extrema-preserving (redesign endpoint)
      def update_meta(self, sid, patch) -> SessionDetail
      def protect(self, sid, on: bool); def archive(self, sid); def purge(self, sid, *, confirm: str)
      def annotations(self, sid) -> list[Annotation]
  ```
- Session listing must never load samples; verify the query plans. Add an index if `sessions` listing sorts by `started` (check `EXPLAIN QUERY PLAN`).
- **Retention** (exists): formalize `RetentionPolicy{days, max_bytes, protect_favourites}`. **Protected and active sessions are never deleted automatically** (keep and extend the existing tests). Add `max_storage_gb` (optional).
- **Exports**: an `ExportFormat` registry (`id, name, extension, supports: session|lap|group, write(session, stream, options)`). Register `bundle_v1` (existing zip), `csv`, `jsonl`, `html_report`. Pages call the export service by id.
- **Imports**: `ImportHandler` registry with validation (size cap, checksum/manifest, schema version, compatibility), **never** pickle/eval. The existing `inspect_bundle` becomes the first handler.

## 16. Annotations, alerts, insights, audit (`domain/`)
- **`Annotation`** (one event representation across charts, logs, replay, race control, analysis):
  ```python
  @dataclass(slots=True)
  class Annotation:
      id: str; session_id: str | None; kind: Literal['incident','flag','pit','radio','user_marker','engineer_alert',
          'system','race_control','lap_boundary','bookmark']
      mono: float | None; utc: str; lap: int | None; distance_m: float | None
      severity: Literal['info','notice','warning','critical']; source: str; message: str; metadata: dict
  ```
  Persist to the existing `events` table (payload JSON; add a `kind` column via migration 003 plus an index). Adapters convert existing events, marked incidents, box intent, engineer decisions and group events.
- **`Alert`**: `{id, time, source: telemetry|race_control|engineer|network|hardware|session|storage, severity, title, message, acknowledged, expires, action: {command_id, payload}|None, context}`.
  - The **engineer Scheduler stays the speech arbiter**. Alerts are the display/notification model feeding the notification center. Rules produce `Alert` + optional speech `Event`.
  - **Rule definitions**: move `engineer.RULES` conditions from the long `conditions` dict into declarative `RuleDef(id, priority, prerequisites, entry(frame,ctx)->bool, exit(frame,ctx)->bool, persist_s, cooldown_s, message(frame,ctx)->str, evidence(frame,ctx)->dict)`, registered per rule, with identical behaviour (regression tests on the existing positive/negative/noisy/stale cases).
  - Don't make rules user-editable code.
- **`Insight`**: `{id, category, severity, title, description, lap, corner_id, evidence: dict, metric: {name, value, unit}, comparison, suggested_followup: {command_id|route}}`. Adapt `analytics.improvements()` and `spatial_coaching` items to it. The UI renders insights generically.
- **Audit log**: a separate authoritative table `audit_log(id, utc, actor, capability, command_id, target, payload_hash, result_code, message, session_id)` in the same SQLite (migration 003).
  - Written by the dispatcher for `audited` commands. Group race-control actions already write `group_events`; mirror them into the audit log (or make `group_events` the audit store for group actions). Pick one and document it in an ADR.
  - Debug logs are **not** audit.
  - `GET /api/audit?session=&since=` (local admin only).

## 17. Configuration versioning (`core/config_migrations.py`)
- `Settings.schema_version` exists (=1). Add a migration chain: `MIGRATIONS = {1: m1_to_2, 2: m2_to_3, …}`. Load raw JSON, then apply the migrations in order, then validate. On failure, keep the existing behaviour (preserve the invalid file, load safe defaults, notice).
- Before any migration writes, back up `settings.v{n}.bak.json` (keep the last 3).
- The first real migration (2) adds the fields introduced by this pass: `units`, `performance_profile`, `log_level`, `feature_flags`, `safe_mode_on_crash`, …. Any fields added by the action-director work that shipped without a version bump get normalized here.
- Group documents: `group_schema` exists; add a per-document `schema` and an upgrade function registry (`group/migrations.py`).
- Track models, league packages (branding export) and session bundles all get a `schema` integer and an upgrade path (bundle v1 import keeps working).
- **Centralize defaults and magic numbers** in `core/defaults.py`, and reference them. Examples:
  - ports 33739/33740/8000/8090/28380;
  - heartbeat default; stale 2 s; interrupt 30 s;
  - recorder queue size, UI Hz, group publish rate;
  - buffer lengths (trace/history), history 180 s, battle tick 2 Hz;
  - map capture 4096 points, corpus 40 MB, upload 5 MiB, quotas.

  Settings validators reference the same constants.

## 18. Audio services boundary
- Already isolated in `voice.py` (mic worker process + speaker). Formalize the interfaces:
  - `AudioInputService` (enumerate devices, start/stop, level/clipping, state);
  - `SpeechRecognizer` (Vosk grammar → text + confidence; VAD/hands-free/PTT policy);
  - `SpeechOutput` (render + play, engine selection, device, busy/cancel);
  - `AlertSounds` (future);
  - `UiSounds` (frontend only, WebAudio, for Broadcast key clicks).
- **Pipeline doc**: Microphone → AudioInput → VAD/PTT gate (suppressed during TTS + 0.6 s tail) → Vosk grammar → intent (`voice.intent`) → `engineer.ask` command → response → Scheduler → SpeechOutput.
- **Privacy is explicit**: no raw audio is stored (keep it); transcripts are in memory unless `retain_transcripts`. Document this in `STORAGE.md`, with a test asserting no audio file is written.
- UI components never touch the microphone. The browser only uses `audio.*` commands and status.

## 19. Engineer service boundary
```python
class EngineerService(Protocol):
    async def ask(self, question: str, ctx: EngineerContext) -> EngineerResponse
    def brief(self, ctx: EngineerContext) -> EngineerBrief                     # evidence items (local_ai.evidence)
    def alerts(self) -> list[Alert]
@dataclass
class EngineerResponse:
    message: str; severity: str; category: str; intent: str; evidence: dict; related_lap: int | None
    related_corner: str | None; recommended_action: dict | None; confidence: Literal['low','moderate','high']|None
    source: Literal['rules','template','local_ai_selected','local_ai_rephrased']
```
- The implementation composes the existing `requests.CATALOG` + `Runtime.command()` answers + `local_ai` (selection/rephrase guard) + `spatial_coaching` + `clean_air`.
- The UI doesn't know whether the implementation is rules, local model or future remote.
- A remote LLM is **not** added. The interface just permits it later, behind a feature flag and explicit user opt-in.
- Move `Runtime.command()` logic into `engineer/` over several commits, keeping answers byte-identical (snapshot tests over all 100 intents × fixture states).

## 20. Structured logging (`core/logging_setup.py`)
- stdlib `logging` with a JSON-lines formatter: `{"t": iso, "lvl": "INFO", "sub": "telemetry.receiver", "event": "variant_changed", "details": {...}}`.
- Subsystem loggers: `system`, `network`, `telemetry`, `session`, `race_control`, `broadcast`, `engineer`, `audio`, `storage`, `ai`, `training`.
- `RotatingFileHandler` at `data/logs/app.jsonl` (5 MB × 5), with the console human-readable in dev.
- **Never log**: per-frame telemetry at INFO or above, raw packets (DEBUG only and sampled, at most 1/s), tokens/credentials/invitation keys/overlay fragments (a redaction filter with tests), microphone audio.
- Rate-limit repeated errors (same key, at most once per 60 s, with a suppressed count).
- `Settings.log_level` (default INFO); debug mode raises it per subsystem.

## 21. Diagnostics
- `GET /api/diagnostics` aggregates:
  - service statuses; receiver (phase, variant, rate, duplicates, gaps, stale, parse errors, unexpected senders, port owners);
  - bus metrics (subscriber errors, handler time p95); recorder backlog/drops; storage (DB and WAL size, free disk);
  - group (clients, subscribers, publish rates); CPU/RSS/thermal (when readable); loop lag;
  - last errors (the ring of the last 50 structured errors); versions; feature flags; platform.
- **Copy diagnostics** creates a redacted JSON bundle (no tokens, invitation keys, IPs masked to /24 unless the user opts in, no personal paths). Tests assert the redaction.
- **Developer mode** (`Settings.developer_mode`, off by default) unlocks: packet viewer (last N parsed frames plus raw hex if captured), state inspector (the snapshot tree), event/audit viewer, simulator scenario picker, network simulator (inject latency/loss into the group client in dev only), layout inspector (frontend). It's hidden in normal UI.

## 22. Safe mode and crash recovery
- **Safe mode** (`run.py --safe-mode`, or automatic when the previous run didn't shut down cleanly **and** `safe_mode_on_crash` is on, or when startup stage 2–4 fails):
  - default UI layout; experimental feature flags off; no auto-start of hosting, group client, local AI or mic;
  - receiver bound but no heartbeat until the user confirms;
  - diagnostics and `/recovery` available; a banner explains why.
- A clean-shutdown marker is `data/.running` (written at start, removed at stop).
- **Crash recovery** exists for sessions (incremental SQLite WAL batches; unfinished sessions recovered). Document the durability window: max buffered samples at risk = recorder batch size / rate. Add a test that kills the writer mid-session and verifies recovery with bounded loss.
- **Auto-save**: settings are atomic already. Layouts/preferences are debounced frontend writes (≥ 500 ms). The graphics draft is saved explicitly (keep the Save draft semantics) plus a sessionStorage safety copy (from the redesign). Session notes are debounced to 1 s.

## 23. Module registry (`core/modules.py`), lightweight
```python
@dataclass(frozen=True)
class ModuleDef:
    id: str; name: str
    services: tuple[Callable[[Ctx], Service], ...] = ()
    commands: tuple[CommandDef, ...] = ()
    capabilities: tuple[str, ...] = ()
    settings_model: type[BaseModel] | None = None    # namespaced settings section
    channels: tuple[Channel, ...] = ()
    rules: tuple[RuleDef, ...] = ()
    routes: Callable[[APIRouter, Ctx], None] | None = None   # adapter layer registers HTTP
    diagnostics: Callable[[], dict] | None = None
    feature_flag: str | None = None
```
- Register existing features as modules: `telemetry`, `sessions`, `engineer`, `voice`, `local_ai`, `tracks`, `training`, `group_race_control`, `broadcast_graphics`, `strategy` (fuel scenarios, clean air), `coaching` (spatial, tyre heat).
- The composition root iterates the modules. A new feature is a new module file plus one line in the module list.
- **Not a public plugin API**: no dynamic loading of third-party code.
- Frontend mirror: `src/domain/modules.ts` registers routes, panels, palette commands and settings sections, so the shell/router/palette/settings discover features instead of hardcoding them (coordinate with the redesign's router and palette).

## 24. Frontend domain layer (`frontend/src/domain/`)
- **API clients**, one per backend area:
  ```ts
  export async function listSessions(q: SessionQuery): Promise<Page<SessionSummary>>
  export async function runCommand<T>(id: CommandId, payload: unknown): Promise<CommandResult<T>>
  ```
  - Shared `http.ts`: base fetch, pairing token header, JSON, `AppError` mapping, abort signals, retry for idempotent GETs.
  - **Components never call `fetch`, open sockets, or read `location` for data.** Migrate the 9 components listed in §0 one at a time.
- **Stores**:
  - Shared domain: `liveStore` (exists; add typed slice selectors), `servicesStore`, `capabilitiesStore`, `sessionsStore` (index cache), `groupStore`, `notificationsStore`.
  - View state (the redesign's `viewStore`): workspace, route, layouts, lanes, laps, zoom, filters, selections. **Never persist domain data** in view stores.
  - Workspace-scoped view state is namespaced: `driver.*` (telemetry layout, reference/comparison, Training view) and `broadcast.*` (selected production source, template, race-control selection, Studio workspace UI).
- **Types**: `domain/types.ts` holds handwritten TS mirrors of backend contracts, plus the generated `channels.generated.ts`, `commands.generated.ts`, `capabilities.generated.ts`, `graphics.generated.ts` from `scripts/gen-contracts.py` (it reads the Python registries and Pydantic `model_json_schema()`). Validate external payloads at runtime at boundaries with small hand-written guards (no zod dependency unless justified).
- **Live data**: typed-array ring buffers for charts (`telemetryRing`, from the redesign) hold at most the last 60 s at received UI rate in memory. Full data comes from the repository endpoints on demand.
- **Error boundaries**: one per page and one per panel (charts, map, graphics preview). A crash shows the panel error state with retry and copy-diagnostics, and reports to the backend `POST /api/client-errors` (rate-limited, redacted, logged under the `ui` subsystem). OBS overlay pages (`GroupPublic`) keep their own boundary and never share state with the editor.

## 25. Performance and platform
- **Budgets** (measure and record in `docs/architecture/PERFORMANCE_BUDGETS.md`):
  - ingest + bus fan-out ≤ 0.5 ms per frame p95 on the dev PC;
  - recorder zero drops at 60 Hz for 30 min (soak);
  - `/ws` snapshot build ≤ 2 ms;
  - group snapshot per subscriber served from cache;
  - frontend App commits ≤ 1/s at idle (redesign target);
  - no unbounded memory growth over a 2 h soak (RSS slope ≈ 0).
- **Performance profile** `AUTO|DESKTOP|LOW_POWER` (a setting; AUTO picks LOW_POWER when CPU count ≤ 4 or RAM ≤ 4 GB).
  - LOW_POWER lowers UI Hz (8), group publish (5 Hz), history buffer length and ambient motion; defers heavy analysis to lap end or session end; reduces local AI frequency.
  - **It never changes recording rate or accuracy.** If a setting would, the UI must say so explicitly.
- **Workers**: keep the existing isolation (mic worker process, asset decode process, `to_thread` for disk/SQLite). Candidates only if profiling justifies: session analysis cache builds and export jobs (a thread-pool job runner with progress events). Don't move UDP decode off the event loop unless measured.
- **Platform adapters** (`core/platform.py`): data-dir resolution (already partly in launchers), audio device enumeration differences, speech engine discovery (Windows System.Speech vs eSpeak/Piper), process/port-owner lookup (exists in diagnostics), desktop window integration (pywebview/GTK). Feature code calls adapters, never `sys.platform` directly. Add a test that greps for `sys.platform`/`os.name` outside `core/platform.py` (allowlist the launchers).

## 26. Contracts and docs generation
- `scripts/gen-contracts.py` produces `docs/architecture/CONTRACTS.md` (tables of channels, commands + capabilities + rate limits, capabilities × roles, alert rules, graphics templates, export formats, settings fields with defaults and units, protocol message types) plus the frontend generated TS files.
- A CI/test check (`tests/test_contracts_fresh.py`) fails when the generated outputs are stale.
- **Document each service boundary** in one short block: owns / accepts / returns / emits / failure modes. Cover TelemetrySource, TelemetryBus, Recorder, SessionRepository, TrackService, EngineerService, SpeechRecognizer/Output, GroupService (host), GroupClient, GraphicsService (workspace/program/overlay output), ExportService, CommandDispatcher, PermissionService.

## 27. Tests for the foundation (add; keep the existing suite green)
- **Unit**: channel registry (every `FIELDS` entry registered, units correct, experimental flags); derived channels; units; command dispatcher (validation, capability, rate limit, audit); permission matrix; config migrations (1→2 with real old settings fixtures); envelope v1↔v2 conversion; RuleDef regression parity; redaction filter; registry duplicate detection.
- **Integration**:
  - replay determinism: the same recorded session through ReplaySource gives an identical sequence of bus events, laps, alerts and report (golden file);
  - telemetry → recorder under a burst (bounded loss accounted);
  - session repository paging and lap series;
  - group handshake compatibility (v1 client, v2 client, incompatible client);
  - reliable message retry and dedup;
  - safe-mode startup after a simulated crash;
  - service lifecycle start/stop ordering and failure isolation (one service FAILED doesn't stop others).
- **Architecture**: `test_architecture.py` (import edges, no fastapi outside adapters, no cycles), the bounded-queue assertion, the platform grep, the frontend `check:arch`.
- **Fixtures**: keep `tests/fixtures/packets.json` and the generator. Add fixture sets for normal sequence, duplicates, out-of-order, gaps, each variant, reconnect and stale stream if missing. Document their provenance (synthetic vs captured). Never rely only on a live PS5.
- **UI** (coordinate with the redesign): navigation and workspace state preservation, command-result display, capability-gated controls.

## 28. Caching for analysis
- An `AnalysisCache` keyed by `(session_id, source_hash, analysis_version, settings_hash)`, stored in `data/cache/analysis/` (JSON, bounded to 500 MB, LRU eviction; protected sessions' cache also evictable, since it's rebuildable).
- `source_hash` = the SQLite max record id + sample count + lap ids hash (cheap).
- Used by: session report, lap comparisons (`align_laps`), corner report (spatial coaching), training evaluation.
- Pipeline stages are separately testable functions: lap segmentation → corner segmentation → derived metrics → comparison → insights → cache.

## 29. Training, achievements, challenges (definitions only this pass)
- Training consumes analysis results (never re-parses telemetry): `Telemetry → Analysis/Insights → TrainingEvaluation → progress events → XP/achievements`.
- **Definitions**:
  - `Achievement(id, name, description, category, tier, condition: EvaluatorRef, progress(ctx)->0..1, reward_xp)`;
  - `Challenge(id, name, scope: daily|weekly|seasonal|league|custom, window, objective: EvaluatorRef, target)`.
  - Evaluators are pure functions over the stored summaries (laps saved, layouts completed, consistency, clean laps).
- Register 3 example achievements as tests of the pattern. The catalogue itself is future work.
- Keep the visual badge art independent (frontend).

## 30. Graphics and broadcast boundaries
- **The output runtime is independent of the editor** (true today: overlays subscribe via `/group-api/subscribe` and read the server-side program). Keep it that way and add a test: closing or navigating the Studio editor doesn't change program revision or overlay output.
- **Graphics data adapters**: graphics consume only published state models: `RaceState`/`TimingState` (classification), `SelectedEntries` (slots), `FlagState` (applicable instructions), `MessageState`, `DecisionState` (public), `BattleState`, `ProjectionState`, `SessionClock`, `BrandingSnapshot`, `StewardCue`. Name them explicitly in `graphics/state_models.py` as `TypedDict`s produced by `filter_snapshot` and consumed by `GroupGraphics.tsx` (typed via the generated TS). No graphic reads editor stores.
- **Template contract** (extend the `GRAPHICS` tuple into a dataclass): `id, name, category, default_size, required_sharing, required_models, config_schema (the Graphic.settings keys), renderer id, preview fixture, lifecycle: {enter_ms, exit_ms, supports_popup}, stage: experimental|stable`. The Studio library, validation and docs all read it. Keep all 26+ current templates working; add none in this pass.
- **League branding** stays separate from app theme tokens (it already is). Formalize a `LeaguePackage` export (schema version, branding, asset references + checksums, fonts only if licensed and embedded as user uploads, graphic defaults) through the export/import registries.
- **Media assets**: `league-assets/` + the `asset` documents are the asset registry. Add metadata fields (`kind: logo|sponsor|team|driver_photo|background`, `name`, `license_note`, `created_by`) via a document migration. Components reference assets only by id through the media route.

## 31. What to implement now vs later
- **Implement in this pass** (adapting the existing code):
  - audit doc; `core/` (lifecycle, registry, events, commands/results, permissions, errors, features, version, defaults, config migrations, logging);
  - telemetry frame + channel registry + derived registry + units + bus + sources (live/demo/replay) + simulator scenarios;
  - service wrappers + `/api/services`; command dispatcher + `/api/commands` with existing actions mapped;
  - capability matrix + server enforcement at existing checks; group envelope v2 with v1 compatibility + handshake;
  - SessionRepository wrapper + export/import registries; annotations + audit log (migration 003); alert/insight models;
  - structured logging + redaction; diagnostics aggregate + redacted copy; safe mode;
  - frontend `domain/` API clients (migrate all direct `fetch` calls), typed stores, generated contracts, error reporting;
  - architecture/contract tests; docs + ADRs + tech-debt register.
- **Defer** (extension points only): new OBS graphics, cloud/relay, a league backend beyond the current group system, a full AI engineer or remote LLM, a championship system, subscriptions, a large achievement catalogue, new strategy algorithms, new network roles beyond the data-driven role map, a public plugin API.

## 32. Deliverables
- **Code**: as above, in small reviewable commits, each keeping `pytest -q`, `npm run build` and e2e green.
- **Docs** (update existing files instead of duplicating them):
  - `ARCHITECTURE.md`, rewritten: layers, a Mermaid system diagram, the dependency rules, runtime composition.
  - `docs/architecture/`:
    - `AUDIT.md`, `DOMAIN_MODEL.md`
    - `TELEMETRY.md` (pipeline, frame, channels, derived, sources, units; links `PROTOCOL.md` and `DATA_FIELDS.md`)
    - `STATE_MANAGEMENT.md` (backend services/state vs frontend domain vs view stores)
    - `NETWORKING.md` (group protocol v2, handshake, reliability classes, sync, security, time)
    - `STORAGE.md`, `COMMANDS_AND_PERMISSIONS.md`, `LOGGING_AND_DIAGNOSTICS.md`
    - `EXTENDING_THE_APP.md` (§33 recipes)
    - `TESTING.md`, `PERFORMANCE_BUDGETS.md`
    - `CONTRACTS.md` (generated)
    - `TECH_DEBT.md` (issue / risk / recommended refactor / subsystem; seeded from §0)
- **ADRs** in `docs/adr/NNNN-title.md` (≤ 1 page each):
  1. Normalized frame = typed view over `Sample.values` (no copy).
  2. In-process TelemetryBus with delivery modes; no broker.
  3. Live/Demo/Replay behind TelemetrySource.
  4. Capability-based permissions with data-driven roles.
  5. Commands vs queries; the CommandResult codes.
  6. Group protocol envelope v2 with a v1 compatibility window.
  7. Audit log vs debug logs (and the `group_events` decision).
  8. Hash routing + frontend domain layer (references the redesign).
  9. Legacy vs v3 track authority and migration plan.
  10. Performance profiles never alter recording fidelity.

## 33. Required end state: every one of these has an obvious answer in `EXTENDING_THE_APP.md`
Each answer includes the file, a code snippet and the test to add.

| Task | Answer |
|---|---|
| New telemetry channel | register `Channel` in `telemetry/frame.py` (+ `DATA_FIELDS.md` row, regenerate contracts) |
| New derived metric | `DerivedChannel` in `telemetry/derived.py` |
| New Pit Wall panel | `frontend/src/domain/panels.ts` + component under `ui/driver/panels/` |
| New Race Control command | `CommandDef` in the `group_race_control` module + capability + audit flag |
| New network message | type + Pydantic schema in `group/protocol.py`, reliability class, role allowlist |
| New OBS graphic | template def in the graphics registry + renderer in `GroupGraphics.tsx` + preview fixture |
| New permission | capability in `core/permissions.py` + role map + matrix test |
| New alert | `RuleDef` in `domain/alerts.py` (+ `ALERT_RULES.md`) |
| New Training achievement | `Achievement` definition + evaluator |
| New session analysis | pipeline stage + `AnalysisCache` version bump |
| New settings value | the module's `settings_model` + config migration + `core/defaults.py` |
| New export format | `ExportFormat` registry |
| New engineer intent | `requests.CATALOG` entry (3 forms) + `EngineerService` handler |

## 34. Completion report
Report on:
- **Existing architecture discovered**: summary of `AUDIT.md`.
- **Changes made**: grouped by layer.
- **New extension points**.
- **Migrations**: config 1→2, DB 003, group docs, protocol v2.
- **Compatibility preserved**: settings, sessions, bundles, maps, league assets, v1 group clients, OBS URLs.
- **Tests added and run**: counts and results.
- **Before/after performance numbers**: measured.
- **Remaining technical debt**: the `TECH_DEBT.md` highlights.
- **Recommended next milestone**: likely retiring the legacy track system and finishing the `runtime.py` decomposition.

**Final principle**: a feature added six months from now should have a clear home, a clear API, a clear data source, a clear permission, a clear test, and minimal impact on unrelated systems. Start with the audit, then implement in stages.
