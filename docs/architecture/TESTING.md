# Testing

Backend tests are pytest under `tests/`; browser tests are Playwright under `tests/e2e/`; the frontend has a build check and
an architecture check. Count on 2026-09-30: 786 pytest tests collected (`pytest --co -q`); 7 Playwright specs.

## 1. Running

```
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=<writable dir>
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=<writable dir> tests/test_commands.py -k catalogue
.venv/Scripts/python.exe -m pytest --co -q -p no:cacheprovider --basetemp=<writable dir>     # list and count
npm --prefix frontend run build         # tsc -b && vite build (writes frontend/dist)
npm --prefix frontend run check:arch    # node scripts/check-arch.mjs
.venv/Scripts/python.exe scripts/gen-contracts.py --check
```

Why `--basetemp` and `-p no:cacheprovider` on this Windows dev PC: pytest's default temp base under the user profile is
permission-broken here, and `.pytest_cache` in the repo is unreadable (`Permission denied`), so both are pointed away. Any writable
directory works (the docs work used a folder in the session scratchpad). On a normal machine plain `pytest` is fine.

Tests build their own data dirs under `tmp_path`, pick their own HTTP ports for `TestClient` and never bind the real
UDP port, so they can run in parallel with a dev server. Several tests spawn a child Python process (the crash test) or use real
sockets (`test_udp.py`, on loopback).

## 2. Layout

Backend tests by area (`ls tests`):

| area | files | what they cover |
|---|---|---|
| Wire and parsing | `test_protocol.py` (independent Salsa20 fixtures, bad lengths), `test_udp.py` (real loopback UDP: heartbeat, parse, record, bad packets, sender filter, receiver reopen), `test_telemetry_units.py` (unit conversions) | packet layer |
| Telemetry model | `test_telemetry_frame.py` (channel registry), `test_telemetry_derived.py` (derived channels, engine isolation), `test_telemetry_bus.py` (delivery modes, isolation), `test_telemetry_scenarios.py` (synthetic scenarios, determinism) | `backend/app/telemetry/` |
| Runtime | `test_runtime_foundation.py` (bus wiring, lifecycle events, replay determinism, crash recovery, privacy, scenarios), `test_core.py` (laps, fuel maths, scheduler, intents, config), `test_reliability.py` (each rule, crash queue, DB full, replay), `test_driver_line.py`, `test_live_analysis.py`, `test_broadcast.py` (live delta and reference), `test_local_ai.py`, `test_hands_free.py`, `test_requests.py` (100-request catalogue) | `Runtime`, sessions, engineer |
| Engineer | `test_engineer_rules.py` (declarative rules, parity with the frozen oracle), `test_modules_engineer.py` (module registry, engineer service), `test_tyre_heat.py`, `test_fuel_scenarios.py`, `test_spatial_coaching.py` | alert rules and coaching |
| Core and platform | `test_core_foundation.py` (registry, errors, lifecycle, features, permissions, dispatcher, logging, config migrations), `test_commands.py` (role x command matrix, race-control flow), `test_permissions_matrix.py`, `test_foundation_api.py` (services, features, diagnostics, safe mode, developer mode over HTTP), `test_recovery.py`, `test_api.py` | `core/`, `api.py` |
| Storage | `test_storage_layout.py`, `test_storage_migrations.py`, `test_storage_repositories.py`, `test_storage_retention.py`, `test_storage_exports.py`, `test_storage_cache.py`, `test_storage_audit.py`, `test_domain_annotations_alerts.py`, `test_domain_insights_training.py` | `storage/`, `analysis_cache.py`, `domain/` |
| Group and Race Control | `test_group.py` (admission and boundary), `test_protocol_v2.py` (envelope, negotiation, reliable delivery, snapshot cache), `test_group_graphics_contract.py`, `test_graphics_registry.py`, `test_group_migrations.py`, `test_group_history.py`, `test_battles.py`, `test_battle_focus.py`, `test_steward_cues.py`, `test_projection.py`, `test_clean_air.py`, `test_clean_air_wiring.py`, `test_traffic_sharing.py` | `backend/app/group/` and strategy |
| Tracks | `test_tracks.py` (legacy maps), `test_track_memory.py`, `test_track_service.py`, `test_track_world.py`, `test_track_gt7tracks.py`, `test_training.py` | track identity and training |
| Repository hygiene | `test_architecture.py`, `test_contracts_fresh.py`, `test_packaging_imports.py` | sections 3 and 4 |

Playwright (`tests/e2e/`): `app.spec.ts` (live demo, engineer, settings, report, mobile layout), `group.spec.ts` (group controls,
graphic renderers, preview isolation), `league-demo.spec.ts`, `broadcast-expanded.spec.ts`, `track-memory.spec.ts`,
`wheel-map.spec.ts`, `recovery.spec.ts` (recovery page with the dashboard bundle blocked).

## 3. Architecture tests

`tests/test_architecture.py` parses imports with `ast` (nothing is imported or executed):

| test | rule |
|---|---|
| `test_layering_edges` | `core` may import only `core`; `telemetry` only `core` and `telemetry`; `domain` only `core` and `domain`; `storage` only `core`, `storage`, `domain`, `telemetry`. Upward edges are allowed only in `LAYER_EXCEPTIONS` |
| `test_core_imports_no_app_modules_and_no_web_framework` | `core/` imports nothing else from the app and neither `fastapi` nor `starlette` |
| `test_only_adapters_import_fastapi` | only `api.py`, `group/admin.py`, `group/public.py` (`ADAPTERS`) |
| `test_no_import_cycles_among_app_modules` | no cycle among module-level imports; function-level (lazy) imports are the sanctioned cycle breakers |
| `test_every_queue_and_deque_is_bounded` | every `deque` needs `maxlen`, every `Queue` a `maxsize`, except `UNBOUNDED_ALLOWLIST` |
| `test_platform_checks_only_in_platform_adapter` | `sys.platform` and `os.name` only in `core/platform.py` (`PLATFORM_ALLOWLIST`; leftovers in `PLATFORM_DEBT`, currently empty) |

Allowlists (`docs/architecture/TECH_DEBT.md` mirrors them; they may only shrink):

- `LAYER_EXCEPTIONS`: `domain/insights.py` -> `analytics`, `spatial_coaching`; `storage/repositories.py` -> `analytics`; `storage/exports.py` -> `exporting`.
- `UNBOUNDED_ALLOWLIST`: `group/history.py` (time-window pruned), `tyre_heat.py` (rolling windows pruned by time).

`tests/test_packaging_imports.py`: every backend module imports without optional dependencies (Vosk, sounddevice, pywebview), new
packages are discoverable by PyInstaller (`--collect-submodules backend`), and packaged data files exist.

Frontend: `npm run check:arch` fails if a file under `src/domain/` imports a `.tsx` component (or anything under `ui/` that is not `.ts` or
`.css`), or if `fetch()` is called outside `src/domain/http.ts` (`ALLOWLIST` is empty and must stay so).

## 4. Contract freshness

`tests/test_contracts_fresh.py` loads `scripts/gen-contracts.py`, and fails if any generated output differs from the live registries:
`docs/architecture/CONTRACTS.md`, `frontend/src/domain/{channels,commands,capabilities,graphics}.generated.ts`. It also checks that the
generation is deterministic and that the content is complete (every `FIELDS` row and unsupported slot exported, core commands present, five
roles, 26 or more graphics, rules, message types). Fix a failure with `python scripts/gen-contracts.py`; never edit the outputs.

## 5. Fixtures and provenance

| file | what it is | how it is produced |
|---|---|---|
| `tests/fixtures/packets.json` | one encrypted packet per variant (A, B, ~, C) | `tests/fixture_generator.py` (`python tests/fixture_generator.py` from the repo root): an independent scalar Salsa20/20 implementation, not the production decryptor. Synthetic: hand-set field values, not captured from a PS5 |
| `tests/fixtures/replay_golden.json` | expected laps, pace, event categories and quality flags of a 4000-frame demo run | written by `test_replaying_the_same_frames_gives_identical_bus_events_laps_and_report` the first time it runs and asserted afterwards; delete it to regenerate after an intended change, and review the diff |
| `tests/fixtures/legacy_engineer.py` | the pre-port `Rules` implementation and its `RULES` table | frozen copy used only as a behavioural oracle by `tests/test_engineer_rules.py`; never imported by the app |

`demo_sample(t, index)` in `telemetry/parser.py` builds a synthetic, deterministic packet (always labelled `provenance='demo'`); most
runtime tests feed it. `scripts/bench_ingest.py` reuses `fixtures()` to build encrypted packets.

## 6. Determinism, crash and privacy tests

- Replay determinism: `test_runtime_foundation.py::test_replaying_the_same_frames_gives_identical_bus_events_laps_and_report` runs the
  same 4000 frames through two fresh runtimes and requires identical bus event sequences, laps, pace and quality, and equality with the golden
  file. `::test_replay_source_reproduces_the_recorded_laps` records with the demo source and feeds the stored rows back like `source_loop`'s
  replay path. `::test_normal_laps_scenario_produces_laps_deterministically` covers the scenario source.
- Crash recovery: `::test_recorder_recovers_after_abrupt_kill_with_bounded_loss` kills a child process with `os._exit(1)` mid-session and
  checks `interrupted` status and at most 440 lost rows (`STORAGE.md`). `tests/test_reliability.py::test_crash_recovery_and_bounded_queue`
  and `::test_database_full_keeps_writer_alive` cover the queue and a failing writer.
- Privacy: `::test_no_audio_or_transcript_is_persisted`, `::test_transcript_is_only_kept_when_the_user_opts_in`.
- Fault isolation: `::test_failing_subscriber_is_isolated_and_counted_as_pipeline_error`, `::test_demo_replay_paths_survive_a_subscriber_failure`.
- Safe mode and diagnostics over HTTP: `test_foundation_api.py` (`LOGGING_AND_DIAGNOSTICS.md`).

## 7. End-to-end (Playwright)

Config: `frontend/playwright.config.ts`: `testDir: '../tests/e2e'`, `workers: 1`, 30 s timeout, headless, `channel` from `PW_CHANNEL`
(default `chrome`, the installed Chrome), `baseURL` from `GT7_TEST_URL` (default `http://127.0.0.1:8000`). There is no `webServer`
block: the specs need a backend already serving the built frontend at that URL. Typical use:

```
.venv/Scripts/python.exe run.py run --data <isolated data dir> --port 8000 --demo     # or the "gt7-backend-dev" entry of .claude/launch.json
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Use an isolated data directory: the specs pair the browser, switch sources, and some change settings on the running instance
(`recovery.spec.ts` saves `minimal: true`). A hard-killed dev server makes the next start a safe start (heartbeat withheld; TECH_DEBT #16),
which does not affect the demo-based specs. There are no unit tests for React components.

## 8. Soak, benchmark and load scripts

| script | purpose | notes |
|---|---|---|
| `scripts/bench_ingest.py [--frames N] [--repeat N] [--output PATH]` | micro-benchmark of `Runtime.ingest_datagram` (decrypt, parse, sequence guard, bus, recorder queue): p50, p95, p99, frames per second | baseline in `docs/architecture/bench_baseline.json`; regression guard is relative (5 percent); see `PERFORMANCE_BUDGETS.md` |
| `scripts/soak.py [--seconds N or --hours H] [--rate HZ] [--output PATH]` | paces `Runtime.consume` with demo frames at `--rate` (default 60) and reports `consume` p95, CPU seconds, queue peak and storage health (drops, failed rows) | **default `--output` is `docs/benchmark.json`, which overwrites a committed file; always pass `--output`** |
| `scripts/group_load_test.py` | starts the real app as a subprocess, enables the group listener, runs the league demo (4, 8, 16 drivers) and opens increasing numbers of overlay WebSocket subscribers; reports CPU, RSS, snapshot latency and recording drops | needs `pip install psutil websockets httpx` (test-only); uses ports 8971 and 8990 |

Other verification scripts (`verify-release.py`, `verify-windows-runtime.py`, `verify-local-ai.py`, `verify-track-recording.py`,
`evaluate-track-*.py`) are release and data checks, not part of the routine suite.

## 9. Before merging

The checklist is in `EXTENDING_THE_APP.md` ("Before you merge"): pytest, `npm run build`, `npm run check:arch`,
`gen-contracts.py --check`, and the ingest bench when the hot path changed.
