# Architecture audit (baseline before the foundation pass)

Snapshot of the repository as found at the start of the foundation pass (git `7da325e` plus the uncommitted
redesign/track/broadcast work in the tree). Numbers are measured, not estimated. See `TECH_DEBT.md` for what
we chose not to fix yet and `ARCHITECTURE.md` for the target design.

## 1. Stack and packaging

| Concern | Reality |
|---|---|
| Backend | Python 3.12 (dev venv), FastAPI 0.142, Uvicorn 0.54, Pydantic v2, stdlib asyncio/sqlite3/struct/socket, PyCryptodome (Salsa20). Optional: Vosk + sounddevice (mic), eSpeak / Piper / Windows System.Speech (TTS), `llama-server` (local AI) |
| Frontend | React 19, TypeScript 5.9, Vite 6, uPlot, lucide-react, GSAP. No router or state library (own `app/store.ts`, `app/router.ts`) |
| Desktop | `desktop.py` (pywebview/GTK), `windows_app.py`; `run.py` CLI (`run`, `diagnostics`, `connection-test`) |
| Packaging | `scripts/package-windows.py` (PyInstaller, `--collect-submodules backend`, so new subpackages are collected), `scripts/package-linux.py` (ARM64 `.deb`) |
| Tests | 418 pytest tests at baseline (all green), Playwright e2e under `tests/e2e` |
| Platform | Windows is the primary dev target; Linux/ARM64 still ships. The Orange Pi 4 GB ceiling was dropped as a design constraint |

## 2. Modules, owners and data flows

Flat `backend/app/` (≈45 modules before this pass; sizes in bytes):

| Area | Modules | Notes |
|---|---|---|
| Composition | `runtime.py` (42 KB), `api.py` (28 KB) | `Runtime` is the god object: 5 asyncio loops, `consume()` fan-out, `snapshot()`, `command()`, `switch()`, `update_settings()` |
| Wire + parse | `telemetry.py` → now `telemetry/parser.py` | `decrypt_datagram`, `parse()` → `Sample`, `Sequence` (uint32 modular ordering), `demo_sample`, `FIELDS` table, `CAPABILITIES`/`UNSUPPORTED` |
| Sessions | `sessions.py`, `analytics.py`, `exporting.py`, `storage.py` → `storage/store.py` | `Sessions.consume` segments laps and writes samples to the `Store` queue |
| Live analysis | `live_analysis.py`, `live_delta.py`, `spatial_coaching.py`, `clean_air.py`, `tyre_heat.py`, `requests.py` (100 intents) | |
| Engineer | `engineer.py` (`Scheduler`, `Rules`, `RULES`), `voice.py` (mic worker process, speaker), `local_ai.py` | Scheduler is the speech arbiter |
| Tracks | Legacy: `tracks.py` (`TrackMap`, `LAYOUTS`). v3: `track_service.py`, `track_model.py`, `track_bundle.py`, `track_catalogue.py`, `track_recognition.py`, `track_fusion.py`, `track_overlap.py`, `track_store.py`, `track_geometry.py`; `training.py` | Two track systems coexist (see TECH_DEBT) |
| Group / Race Control | `group/`: `service.py` (53 KB, largest file), `admin.py` (local `/api/group`), `public.py` (LAN listener), `client.py`, `models.py`, `repository.py`, `battles.py`, `history.py`, `pit.py`, `projection.py`, `steward.py`, `timing.py`, `assets.py`, `demo.py` | |
| Config | `config.py` (`Settings`, `Config`), `diagnostics.py` | |

### Runtime data flow (baseline)

```
UDP datagram ─▶ source_loop (bind, heartbeat, sender check) ─▶ ingest_datagram
   ─▶ telemetry.parse ─▶ Sequence.accept (dup/reorder/gap/reset) ─▶ Runtime.consume(sample)
         track_map ▶ training ▶ track_service ▶ live_delta ▶ live_analysis ▶ reception_test
         ▶ sessions (laps + recorder queue) ▶ tyre_heat / spatial lap ▶ engineer rules + lap events
   ─▶ snapshot() at ui_hz ─▶ /ws        (latest-state-wins, no queue)
```

Demo and replay enter at `consume()` from the same `source_loop`, selected by `self.source`.

### Tasks and threads

- asyncio tasks: `source_loop`, `engine_loop` (20 Hz: speech, mic polling, history), `health_loop` (1 Hz), `ai_loop` (2 s), `track_loop` (2 Hz), group `loop` + `record_loop`, per-connection WS tasks.
- Threads: `sqlite-writer` (single writer, 240-job/200 ms batches), speaker thread, `asyncio.to_thread` for disk/SQLite/analysis.
- Processes: microphone worker (`multiprocessing`), asset decode worker (`group/asset_worker.py`).

## 3. Persistence

| Kind | Location |
|---|---|
| Settings | `settings.json` (Pydantic `Settings`, `schema_version`, atomic write; invalid file preserved + safe defaults) |
| Credentials | `control-token`; group credential hashes in SQLite |
| Sessions | `telemetry.sqlite3` (WAL, single writer, `PRAGMA user_version`) |
| Group | `group_*` tables (`group_schema`) |
| Tracks | `track-maps/` (legacy), `track-models/` (v3 user), `track-training/`, `_corpus.jsonl` |
| Media | `league-assets/` |
| UI prefs | browser `localStorage` (`ui:v1:*`), per browser |

## 4. Entry points

`run.py run|diagnostics|connection-test`, `desktop.py`, `windows_app.py`, `scripts/*` (soak, group load test, packaging, track tools), `uvicorn` factory `backend.app.api:create_app`.

## 5. Findings that drove the pass

1. `Runtime` mixes lifecycle, ingestion, fan-out, snapshot building and intent handling.
2. Consumers are wired by explicit call lines inside `consume()`; an exception in one skipped all later consumers and (for demo/replay) killed `source_loop`.
3. Status is scattered (`receiver` dict, `audio` block, `health` block, `track.status`, group `client.status`).
4. `fetch(` was called directly from 9 components; components built URLs and interpreted errors themselves.
5. Permissions were inline (`principal['kind'] in (...)`, workspace-owner checks) in `group/service.py`.
6. `group/service.py` raised `fastapi.HTTPException`, so the service layer depended on the web framework.
7. No structured logging, no diagnostics bundle, no safe-mode start.
8. No versioned group protocol (only `version:1` inside `Join`/`Packet`), no explicit reliability classes.
9. Settings had `schema_version=1` but no migration chain; defaults and magic numbers were scattered.
10. Registries existed (`CAPABILITIES`, `CATALOG`, `RULES`, `GRAPHICS`, `tracks.json`) but with four different shapes.

## 6. Baseline numbers

- `scripts/bench_ingest.py` (`ingest_datagram` incl. decrypt, parse, sequence, all consumers, recorder queue; 20 000 frames, Windows, Python 3.12): p50 0.32–0.37 ms, p95 0.58–0.74 ms, ≈2.2–2.6 k frames/s. (`docs/architecture/bench_baseline.json`.) Note the 0.5 ms p95 budget in `PERFORMANCE_BUDGETS.md` was already exceeded at baseline on this machine while the box was under other load; the budget is tracked as a target, the regression guard is relative.
- 418 tests, all passing (`pytest --basetemp=<writable dir>`; the default Windows temp base is permission-broken on the dev PC).
