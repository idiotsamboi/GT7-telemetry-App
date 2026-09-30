# GT7 Race Engineer — AI context file
<!-- Purpose: complete feature and architecture map for AI agents (Claude Code, Codex). Dense by design. Generated 2026-09-28 from source inspection. Source code wins if it disagrees with this file. -->

## 0. Legend
- `[OK]`: implemented and wired.
- `[PARTIAL]`: implemented with known gaps.
- `[UNWIRED]`: code exists but is not used at runtime.
- `[N/A-BY-DESIGN]`: GT7 does not transmit it; the app must show it as unavailable.
- `→` means "data flows to".

## 1. Identity
- **What it is**: a local-first Gran Turismo 7 (PS5) telemetry receiver, spoken race engineer, recorder/analyzer, league Race Control and OBS broadcast studio.
- **Stack**:
  - Backend: Python 3.12, FastAPI, Uvicorn, Pydantic v2, stdlib sqlite3 and asyncio.
  - Frontend: React, TypeScript, Vite (built `frontend/dist`, served statically), uPlot, lucide-react, GSAP (`motion.ts`).
- **Runs on**: Windows (pywebview/WebView2 native window or browser) and Linux (GTK/WebKit or browser). There is an ARM64 Ubuntu package.
  - The Orange Pi 4 GB target was **dropped by the user**. The goal is now general lightweight operation. README and INSTALL docs still mention the Orange Pi, and that is stale.
- **Principles, enforced everywhere**:
  - Truthful data: every value is reported telemetry, a labelled calculation, user-entered, or unavailable. No fake zeros or values.
  - Loopback by default; no cloud and no account.
  - A single GT7 receiver; bounded queues.
  - Live, demo and replay provenance never mix.
- **Status**: independent beta. Release packages 1.3.0 predate most recent features, so run from source for the current ones.

## 2. Entry points and CLI
- `run.py [run|diagnostics|connection-test] --data DIR --demo --host --port --ps5 IP --duration S`: headless server, diagnostics, or a standalone UDP connection test (the normal receiver must be stopped first).
- `windows_app.py --desktop|--browser|--self-test|--webview-test --data --port`: Windows launcher. `Open desktop app.vbs` and `Open in browser.vbs` run it without a console.
- `desktop.py`, `scripts/desktop-launch.sh`: Linux GTK/WebKit desktop.
- `scripts/launch.sh|launch.ps1`, `install-ubuntu.sh` (venv), `install-service.sh` (opt-in systemd user service).
- **Data dir**:
  - Source installs use `data/` (override with `--data`).
  - Packaged Windows uses `%LOCALAPPDATA%\GT7 Race Engineer`; packaged Linux uses `~/.local/share/gt7-race-engineer`.
  - Contents: `settings.json`, `control-token`, `telemetry.sqlite3` (+WAL), `track-maps/`, `track-training/`, `league-assets/`.
- **Ports**:
  - HTTP 8000 (local UI and admin API).
  - UDP receive 33740; heartbeat is sent to PS5:33739.
  - The group/LAN listener defaults to 8090 and is off by default.
  - The local AI llama-server uses 28380.

## 3. Repository map (key files)
```
backend/app/
  telemetry.py        GT7 packet decrypt+parse (A/B/~/C), FIELDS offset table, CAPABILITIES/UNSUPPORTED registry
  runtime.py          Orchestrator: receiver, sessions, recorder, engineer, voice, track map, training, live state (/ws payload)
  api.py              FastAPI local admin API + /ws + /recovery
  config.py           Pydantic Settings + atomic save + control-token + invalid-settings recovery
  sessions.py         Session/lap state machine, fuel, reports
  storage.py          Single-writer SQLite WAL recorder (sessions, samples, laps, events, profiles)
  analytics.py        fuel_prediction, lap_statistics, downsample(extrema), align_laps, approximate_compare, braking_episodes, improvements
  live_analysis.py    5 Hz trailing-30 s metrics + 15 s reception test
  live_delta.py       Position-aligned live delta vs reference lap
  engineer.py         Alert RULES + speech Scheduler (priority/quota/cooldown/expiry)
  requests.py         100-intent request catalogue x 3 answer forms
  voice.py            Vosk intent grammar mic worker; TTS (eSpeak NG / Piper / Windows System.Speech)
  local_ai.py         Optional llama-server (Qwen 0.5B GGUF) evidence ranking
  exporting.py        Session bundle zip export/import with checksums
  diagnostics.py, cars.py (car-id -> identity), tracks.py (ACTIVE track map/recognition, legacy v2)
  track_model.py, track_recognition.py, track_store.py, track_fusion.py, track_overlap.py,
  track_bundle.py, track_catalogue.py   v3 world-model system [UNWIRED at runtime: see section 9]
  training.py         Track Training lap recorder (feeds v3 build pipeline)
  group/              Race Control + Broadcast: service.py (core), admin.py (/api/group local), public.py (LAN listener),
                      client.py (driver publisher), models.py (schemas, GRAPHICS registry), repository.py (SQLite docs),
                      timing.py (projection/zones/flag precedence), assets.py+asset_worker.py (image upload), demo.py (synthetic league)
  data/               tracks.json (41 venues/122 layouts), cars.json, track-references.json (legacy),
                      track-models.bundle.json.gz (v3, ~7.9 MB), recovery.html/js
backend/migrations/   001_initial.sql, 002_archive.sql (user_version=2)
frontend/src/
  main.tsx            Shell, modes, Pit Wall tabs, Settings, Sessions, Engineer, Strategy, Telemetry, Analysis
  RaceVisuals.tsx     CircuitMap (the one map renderer), TrackSelect, current-car panel
  WheelDash.tsx/.css  Wheel full-screen dash
  Training.tsx, TrackVisualizer.tsx, RouletteWheel.tsx   Track Training mode
  GroupControl.tsx (Race Control setup/hosting/replay), RaceDesk.tsx (race director), GroupStudio.tsx (Broadcast Studio),
  GroupGraphics.tsx/.css (26 overlay renderers x 10 styles), LeagueBranding.tsx, Broadcast.tsx, RequestLibrary.tsx,
  LocalBrief.tsx, Chart.tsx (uPlot), colors.ts (semantic colours), motion.ts
scripts/              track-tool.py (build v3 bundle), evaluate-track-*.py, verify-track-recording.py, group_load_test.py,
                      soak.py, backup.py, download-model.py (Vosk), install-local-ai.py, verify-local-ai.py,
                      fetch-car-assets.py, import-race-assets.py, package-windows.py, package-linux.py, verify-*.py
tests/                pytest (~225 tests): protocol, udp, core, api, reliability, requests, hands_free, local_ai,
                      live_analysis, driver_line, tracks, track_memory, track_world, track_gt7tracks, training,
                      group, broadcast, graphics_registry, recovery
tests/e2e/            Playwright: app, group, league-demo, broadcast-expanded, track-memory, wheel-map, recovery
docs/                 USER_GUIDE, RACE_CONTROL, BROADCAST_GRAPHICS, TRACKS, TRACK_MEMORY, TRACK_WORLD_COVERAGE,
                      RECOVERY, LOCAL_AI, VALIDATION, *.json validation/benchmark evidence, prompts/, licenses/
root docs             README, IMPLEMENTATION_STATUS (newest first), ARCHITECTURE, PROTOCOL, DATA_FIELDS,
                      ALERT_RULES, VOICE_COMMANDS, PERFORMANCE, TROUBLESHOOTING, THIRD_PARTY_NOTICES
```

## 4. Telemetry receiver `[OK]`
- **Protocol**: a port of MacManley/gt7-udp (MIT, pinned `a768574b…`).
  - Salsa20 key: the first 32 bytes of `"Simulator Interface Packet GT7 ver 0.0"`.
  - Nonce: `pack('<II', seed^XOR[variant], seed)`, where the seed is at 0x40.
  - Magic `0x47375330`.
- **Variants by length**:

  | Variant | Length (bytes) | XOR constant |
  |---|---|---|
  | A | 296 | 0xDEADBEAF |
  | B | 316 | 0xDEADBEEF |
  | ~ | 344 | 0x55FABB4F |
  | C | 368 | 0xDEADBEEF |

- **Heartbeat**: selects the variant; configurable interval 0.25–15 s, default 1 s. It's a keepalive, not the sample rate.
- **Parse**: explicit little-endian offsets from the `FIELDS` table. Extension fields are reset to null on shorter variants. Negative timing sentinels become null.
- **Channels**:
  - Motion: position xyz (y = elevation), velocity, rotation, north, angular velocity, body height.
  - Engine and fuel: rpm, fuel and capacity, speed m/s, boost (raw +1), oil pressure, water/oil temp (constant; never alert on them).
  - Tyres: tyre surface temperatures ×4.
  - Timing and race: packet_id, lap and total_laps, best/last ms, day_ms (time of day; never used as lap time), start_position/start_cars (pre-race only).
  - Gearbox: rpm_min/max (shift-light range), transmission_max, flags, gears nibble (current / suggested), throttle and brake 0–255.
  - Road and wheels: road plane, wheel angular velocity (rad/s), tyre radius, suspension.
  - Drivetrain: clutch and engagement, gearbox rpm, gear ratios, car_id.
  - B adds: steering rotation and velocity, acceleration.
  - ~ adds: filtered pedals, torque vectors, energy recovery.
  - C adds: surface codes, current_ms, wheel steering, wheelbase, category. C interpretations are opt-in via `trust_c_fields`.
- **Flags bitfield**:

  | Bit | Meaning |
  |---|---|
  | 0 | on track |
  | 1 | paused |
  | 2 | loading |
  | 3 | in gear |
  | 4 | has turbo |
  | 5 | rev limiter |
  | 6 | handbrake |
  | 7 | lights |
  | 8 | high beam |
  | 9 | low beam |
  | 10 | ASM |
  | 11 | TCS |

- **Robustness**:
  - Sender validation; tracking of duplicates, reordering, gaps and wraparound.
  - Classified `PacketError` codes; a parser exception never kills reception.
  - Reconnect/backoff and stale detection (`stale_seconds`, default 2).
  - Port-owner PID diagnostics; unexpected-sender count.
- **Diagnostics**: receiver phase (bind / heartbeat / no-data / rejected / receiving), counters, last sender/length/variant/error, `rate_hz`, and a nonintrusive 15 s reception test (healthy / degraded / no_data).
- **`[N/A-BY-DESIGN]`** (`telemetry.UNSUPPORTED`):
  - Race and timing: leaderboard/position, gaps, opponents, official sectors, official lap validity, race finish.
  - Race control and conditions: race flags, penalties, weather, track name/ID.
  - Car state: tyre wear/pressure/compound, damage, understeer diagnosis, brake bias, TC/ABS levels, fuel map.
  - The UI flag widget shows **player status** only (on track / paused / loading / off track).

## 5. Runtime pipeline and live state
- **Flow**: UDP → parse → `runtime.consume`, which feeds:
  - the session state machine;
  - the recorder queue (every sample);
  - live_delta, live_analysis;
  - track map recognition, training;
  - engineer rules → scheduler → TTS.
- **UI stream**: `/ws` WebSocket, latest-state-wins, at `ui_hz` (default 12, range 2–20). There's also `GET /api/state`.
- **State payload keys**:
  - Status: `host_only`, `recovery_notice`, `source` (live/demo/replay), `stale`, `age_ms`, `status`, `socket_error`.
  - Track and car: `track_selection{layout_id,name,status}`, `car` (identity from car_id).
  - Analysis: `local_ai`, `live_delta{available,delta_s,trend,reason,stale}`, `race_flags{available:false}`, `reception_test`, `live_analysis{longitudinal_g,coast_percent,overlap_percent,tyre_spread_c,braking_episodes,window_s}`.
  - Telemetry: `sample{values,mono,utc,variant,provenance,quality,...}`.
  - Session: `session_id`, `report`, `fuel{litres_per_lap,laps_remaining,margin_l,save_percent,refuel_l,uncertainty_l,remaining_distance_laps}`.
  - Engineer: `subtitle`, `events[20]`, `box`.
  - System: `health{rate_hz,cpu,rss,thermal_c,loop_lag_ms,storage,clients,...}`, `receiver`.
  - Audio: `audio{hands_free,microphone,level,clipping,delivery,speaking,muted,transcript,...}`.
  - Other: `trace`, `history`, `training`, `replay{paused,speed,cursor}`.
- **Resource degradation**: UI rate reduction with hysteresis; recording is protected.

## 6. Sessions, recording, replay, export
- **Session state machine** (`sessions.py`): disconnected → connected/idle → driving ↔ paused → completed | interrupted.
  - Manual Start/End controls.
  - Interruption after `interrupt_seconds` (default 30) with no data.
  - Car/lap/source resets start a new epoch. Session and lap IDs are UUIDs.
  - Partial and incomplete laps are kept, with quality flags.
  - UDP stopping is never treated as a finish.
- **Storage**: SQLite WAL, a single batched writer with bounded buffering and explicit loss counters.
  - Tables: `sessions` (status, provenance, meta, report, protected, archived_at), `samples` (session, lap_id, mono, packet_id, payload JSON), `laps`, `events`, `profiles`.
  - Group tables are separate (see section 12).
  - Crash recovery of unfinished sessions.
- **Replay**: recorded samples go through the same pipeline, with pause, speed, seek and restart. Replay sends no heartbeat and never overwrites live maps or personal bests.
- **Demo**: synthetic source, labelled `SYNTHETIC DEMO`.
- **Export**: zip with `metadata.json`, `samples.jsonl`, `telemetry.csv` (formula-injection safe), `report.html`, `manifest.json` (sha256).
  - Import is bounded and checksum-validated; no pickle or eval.
- **Maintenance API**:
  - Session metadata, notes and tags; protection.
  - Manual corrections (`/correct`).
  - Archive; retention preview/apply (`retention_days`, default 90).
  - Confirmed purge; protected and active sessions are never deleted.
- **Raw capture**: optional encrypted-datagram capture (`raw_capture`).

## 7. Analysis and strategy
- **Fuel** (`analytics.fuel_prediction`):
  - Needs 3 or more clean laps, using the median burn.
  - Outputs: laps remaining after the reserve; needed/margin; saving percentage; refuel litres; uncertainty; confidence moderate or low.
  - Uses the remaining distance including the current-lap fraction. Refuel jumps are excluded.
  - Timed races use `race_minutes` + `extra_lap`.
- **Pace**: best, mean, median, pstdev, trend (last 3 vs previous 3), count.
- **Lap comparison**:
  - `align_laps` does spatial projection with a forward-continuity corridor of 25 m and rejects on poor coverage.
  - `approximate_compare` is a labelled distance-normalization fallback.
- **Braking episodes**: entry/exit speed, duration, peak. **Improvement cards**: repeated-evidence cards with lap numbers and advice.
- **Live analysis**: 5 Hz over a trailing 30 s window: longitudinal g (speed derivative), coasting %, pedal overlap %, tyre spread, braking episodes.
- **Live delta**: position-aligned to a clean reference lap (manual selection or "use last lap"). Old limit: 1500 points / 5 minutes. Green means gaining, red losing, grey no reference.
- **Strategy page**: reserve and race-length inputs, finish margin, saving target, pit intent "Box this lap" and "Unmark pit intent / stay out".
- **Session report**: generated immediately on End, with lap tables, fuel, observations, and the top improvement cards.
- **`[PARTIAL]`**:
  - no corner-by-corner coaching, custom-sector theoretical best, or pit-loss model;
  - no understeer/oversteer diagnosis (deliberately);
  - incident detection is limited.

## 8. Race engineer and voice
- **Alert rules** (`engineer.RULES`), each with priority (P0–P3), persistence, entry/exit hysteresis and `alert_cooldown` (default 60 s):

  | Rule | Priority | Entry → exit | Prerequisite |
  |---|---|---|---|
  | `fuel_critical` | P0 | fuel < 0.5 L while moving → > 0.8 L | — |
  | `low_fuel` | P1 | < `low_fuel_l` → > +0.5 | — |
  | `handbrake` | P1 | handbrake flag at > 30 km/h | — |
  | `pit_speed` | P1 | speed > limit + 2 | `pit_region` + `pit_limit_kmh` configured |
  | `tyre_hot` | P2 | > `tyre_limit_c` | user-set limit |
  | `tyre_imbalance` | P2 | L/R difference > `tyre_imbalance_c` (default 18) | — |
  | `off_surface` | P2 | ≥ 2 tyres report surface D/G/S/s | C fields trusted |
  | `limiter` | P3 | rev-limiter flag | — |
  | `pedal_overlap` | P3 | both pedals > 20% at > 36 km/h | — |

  Rules are cleared when paused or off track.
- **Scheduler**:
  - One utterance at a time.
  - Bounded queue: 20 total / 16 normal.
  - Superseding by the same category.
  - Expiry (TTL 12 s); session invalidation; stale suppression.
  - Quotas: `speech_gap` 8 s, `speech_per_min` 4, `speech_seconds` 20 per minute.
  - P0 repeats limited to one per 15 s. Workload deferral for P2+.
  - Every decision is logged (selected / merged / expired / suppressed / muted).
- **Modes**: Quiet, Normal, Detailed, Coaching (enables P3), Critical-only. `hard_mute` silences everything, including P0. "Quiet for two minutes" is a temporary suppression.
- **Requests** (`requests.py`): 100 intents × 3 answer forms. Searchable in Engineer → Request library; accepts typed commands via `/api/command`.

  | Category | Count | Examples |
  |---|---|---|
  | Radio | 9 | radio check, repeat, speak less/more, quiet 2 min, mute, stop talking, resume, is speech on |
  | Race | 1 | status |
  | Fuel | 10 | fuel, can I finish, save, capacity, %, consumption, laps left, margin, refuel, uncertainty |
  | Strategy | 1 | when should I pit |
  | Controls | 5 | box this lap, use last lap as reference, mark corner, mark incident, end session |
  | Timing | 12 | last, best, delta, lap #, game lap count, average, median, consistency, comparable laps, laps completed, reference time, gaining/losing |
  | Analysis | 7 | where am I losing time, what happened that lap, compare with best, acceleration, coasting, overlap, last braking |
  | Tyres | 8 | overall, each corner, front/rear average, spread |
  | Navigation | 3 | show live / analysis / strategy |
  | Car | 16 | speed, revs, gear, suggested gear, shift ceiling, steering angle/rate, wheel speeds ×4, suspension ×4, which car |
  | Inputs | 3 | throttle, brake, clutch |
  | Unavailable | 6 | tyre wear, pressures, position, gap ahead, sectors, flags — each answered honestly as unavailable |
  | Setup | 8 | track, layout, direction, reserve, race distance/duration, target lap, pit limit |
  | System | 11 | source, packet type, rate, missing packets, decode errors, backlog, dropped records, storage, CPU temp, load, memory |

- **Recognition**:
  - Vosk small English with a constrained grammar (aliases + "engineer …" + `[unk]`), number parsing, and a `recognition_confidence` threshold of 0.7.
  - Hands-free is on by default. Push-to-talk interrupts playback.
  - Suppressed during TTS plus a 0.6 s tail; the mic worker retries after 30 s; device/model changes restart it.
  - No raw audio is retained. Transcripts are in memory only, with opt-in `retain_transcripts`.
- **TTS**: eSpeak NG (default), Piper (optional, GPL, a separate binary), or Windows System.Speech via PowerShell.
  - Rate and volume are configurable; device selection; device-rate conversion.
  - Speaker test, mic test, noise calibration. The browser needs **Enable audio**.
- **Local AI** (`local_ai.py`) `[OK, optional]`:
  - Runs llama-server with a Qwen 0.5B quantized GGUF (install via `scripts/install-local-ai.py`).
  - Threads = cpu−1, clamped to 2–6; one inference at a time; interval `local_ai_interval` (default 45 s).
  - It only **ranks** pre-computed evidence items; it cannot invent metrics, change settings or raise alerts.
  - Falls back to deterministic briefs under memory, thermal or CPU pressure.
  - UI: `LocalBrief.tsx`; action `ai_briefing`.

## 9. Tracks, maps, recognition
Two generations of the track system coexist.

- **ACTIVE: legacy v2** (`tracks.py TrackMap`, used by `runtime.track_map`) `[OK]`:
  - Learns driving lines in world x/z. Capture is bounded to 4096 points at about 10 m spacing. The opening partial lap is discarded; a map is saved after one continuous clean lap.
  - Per-layout JSON in `data/track-maps/`, with 8-revision history, atomic writes and restore.
  - `_candidates.json` holds unnamed laps awaiting confirmation. `_corpus.jsonl` is an append-only log of confirmed laps (40 MB cap).
  - Recognition matches complete laps against saved fingerprints (`track_geometry.Fingerprint`, direction-aware, ordered progress).
  - Reference-shape suggestions come from normalized outlines (`track-references.json`, 101 of 122) and always require confirmation.
  - Same-length variants need confirmation. Leaving the circuit clears state.
  - Manual `TrackSelect` always wins.
  - API: `/api/track-map*`.
- **NEW: v3 world models** `[UNWIRED at runtime]`:
  - `track_model.build_model`: 2 m centreline `[x, elev|null, z]`, cumulative s, heading, curvature, auto corners, spatial grid with 25 m cells. `TrackProgress` projects a position to s.
  - `track_recognition.TrackRecognizer`: bounded Viterbi with particles over s. Evidence: distance, heading, elevation (σ≈3 m), progress continuity. It includes an unknown hypothesis, discriminating intervals and equivalence classes. Manual `select` and `reject`.
  - `track_fusion.fuse_laps`: median lateral consensus. `track_overlap`: separating intervals. `track_store`: v3 JSON files, user layers, pack export/import.
  - Bundle `backend/app/data/track-models.bundle.json.gz` (~7.9 MB) is built by `scripts/track-tool.py refresh|build|report`.
  - Bundle coverage: world capture 69, surveyed 29, GT7Tracks capture 3, none 21, out of 122.
  - Bundle sources:
    - jbhoorasingh/gt7-datalogger-track-data @dd9ab8ef (world-metre signatures and surveyed bundles with borders and corners);
    - zetetos gt-telemetry captures (vendored);
    - vthinsel/GT7Tracks @905f5ef, which adds elevation for 22 layouts, elevation transferred to same-venue siblings, and new layouts 790, 795, 846. Its Keras model is deliberately not used.
  - Evidence:
    - Synthetic eval: 98 layouts, 0 false locks, 74.8% lock within 1 km.
    - One recorded live lap (Willow Springs Big Willow): median 3.4 m, p95 ≈25 m from the model; runtime p95 8.8 ms.
  - `[PARTIAL]` gaps:
    - Nordschleife (95), Lago Maggiore Centre (791/793) not built;
    - bundle packing/LOD/lazy-load/ETag optimization not done;
    - **not yet wired into `runtime.py` / `api.py` / UI**; `TrackProgress` not yet replacing `group/timing.Projection` or `live_delta`.
- **Map UI**: one renderer, `RaceVisuals.CircuitMap(map, trace, markers, showReference, showLearned, interactive)`.
  - Used in: Pit Wall → Live Race "Circuit & driving line" panel, Wheel → MAP page and race mini-map, Race Control desk (`RaceDesk`), OBS Track map graphic.
  - Shows a delta-coloured recent line, reference/learned toggles, map export/import JSON, and restore of the previous map.
- **Circuit catalogue**: `tracks.json` holds 41 venues and 122 layouts with ID (ddm999/gt7info course IDs), name, direction, length_m, and a logo (local PNG/SVG or a labelled original badge).
- **Track Training mode** (`Training.tsx`, `training.py`, `/api/training/*`) `[OK]`:
  - Tabs: Untrained (layouts with no model) and Goals (progress).
  - A roulette wheel randomly picks an untrained layout; the driver can also pick one directly.
  - Start/stop capture. Laps are segmented by GT7's own lap counter. Retry lap; restart.
  - A live point-cloud visualizer.
  - Goal: 2500 saved points per km, roughly 2–4 laps.
  - Laps are saved to `data/track-training/<layout>.jsonl` for a later `track-tool.py build` under "user" precedence. It never writes the bundle directly.

## 10. Frontend modes and pages (`main.tsx` MODES)
- **Pit Wall** (tabs):
  - **Live Race**:
    - Telemetry and timing: speed, RPM bar, gear; throttle (green) / brake (red) / clutch (light blue) bars; lap timing (current requires C fields, last, personal best, estimated delta, S1–S3 shown as unavailable, overall fastest); timing colours: fastest purple, personal best green, other yellow.
    - Car state: fuel and range, tyre surface temperatures, recent pace chart.
    - Map and car: circuit/layout select, map, current-car panel with a transparent car image and manufacturer.
    - Status and controls: engineer subtitle, player-status flag, recording indicator, a synthetic-demo badge with Try demo / Use PS5; controls for mute, hold-to-talk, hands-free, mark incident, start/end session.
  - **Telemetry**: the real-time analysis card and the telemetry explorer (uPlot). Channels: speed, rpm, throttle, brake, clutch, gear, fuel, steering, wheelbase. Recorded overview is extrema-preserving; drag-zoom and paging.
  - **Analysis**: session report, lap stats, comparisons, improvement cards, braking.
  - **Strategy**: fuel assumptions (Apply assumptions), margin, saving, pit intent.
  - **Engineer**: last utterance, request library, typed command, radio verbosity (Save radio settings), transcript when enabled, alert/decision history.
  - **Sessions**: library, metadata/tags/protect, replay, export/import, retention.
- **Race Control**: `GroupControl` + `RaceDesk` (section 12).
- **Studio**: `GroupStudio` + `LeagueBranding`, with Edit and Deliver tabs (section 13).
- **Wheel**: full-screen `WheelDash`.
  - Pages: RACE, TIMING, FUEL, TYRES, STRATEGY, MAP. ←/→ keys page; Esc exits. The user can show or hide pages.
  - Fields: shift lights (rpm_min/max, flashing on rev limiter), gear plus suggested gear, speed, RPM dial, boost, THR/BRK/CLU bars, overlap, long g, slip, delta plus bar, last/best, lap and total laps, fuel, tyre temperatures, status lamps (flags), mini-map, box-this-lap, LIVE/DEMO/REPLAY/NO SIGNAL, Hz.
- **Training**: section 9.
- **Settings**: every `Settings` field (section 14), Pair browser, the connection test, audio tests, local AI, display (theme, minimal, reduced motion, UI Hz).
- **Recovery**: a header button, an error fallback, and the standalone `/recovery` page (plain HTML/JS, independent of React). Actions:
  - return to PS5 / exit host-only;
  - restore full dashboard;
  - restore UDP defaults (keeps the PS5 IP);
  - reset audio to defaults.
- **Styling**: dark by default with a light option. Semantic colours in `colors.ts`: throttle `#25e58b`, brake `#ff354b`, clutch `#9edbff`, fastest `#ba65ff`, personal `#25e58b`, other lap `#f4d34e`. Other channels get hashed colours.
  - F1-broadcast styling, a red logo, black/grey backgrounds. Responsive down to 360 px; fullscreen.

## 11. Local admin API (`api.py`, loopback, pairing token for non-loopback)
- **System and state**: `GET /api/health`, `POST /api/pair`, `GET /api/state`, `WS /ws`, `GET|PUT /api/settings`, `GET /api/capabilities`, `GET /api/audio`, `GET /` (SPA).
- **Tracks**: `GET /api/tracks`, `GET|PUT /api/track-map`, `POST /api/track-map/{select,confirm,restore}`, `GET /api/track-map/library`.
- **Training**: `GET /api/training/{candidates,progress}`, `POST /api/training/{start,stop,retry-lap,restart}`.
- **Engineer**: `POST /api/command` (text intent), `GET /api/engineer/requests`.
- **`POST /api/control` actions**:
  - Session: `start`, `end`, `stop`, `live`, `connection`, `reconnect`, `telemetry_test`.
  - Demo and replay: `demo` (via source), `replay`, `replay_pause`, `replay_seek`, `replay_speed`.
  - Audio and voice: `mute`, `resume`, `ptt_start`, `ptt_stop`, `listen_on`, `mic_enable`, `audio`, `audio_test`, `speaker_test`.
  - Other: `display`, `ai_briefing`.
  - Engineer intents handled in runtime: `radio`, `status`, `fuel`, `box`, `unbox`, `delta`, `loss`, `compare`, `reference`, `target`, `tyres`, `quiet`, `repeat`, `lap_summary`, `end`, `stop`, `unknown`.
- **Sessions**: `GET /api/sessions`, `GET /api/sessions/{sid}[/samples|/report|/export]`, `PUT …/metadata`, `POST …/{correct,archive,purge}`, `GET|POST /api/retention`, `POST /api/import`, `POST /api/compare`, `GET|PUT /api/profiles`.
- **Recovery**: `GET /recovery`, `GET /recovery.js`, `POST /api/recovery`.
- **Security**:
  - Strict origin allowlist (`allowed_origins`, max 32 exact origins).
  - A control token (`control-token`, 32 bytes) for paired remote browsers.
  - Atomic settings writes; invalid settings are backed up as `settings.invalid-*.json` and safe defaults load.
  - Settings changes can't lock out the running loopback origin.

## 12. Race Control (league/group) `[OK, development preview]`
- **Roles**:
  - **Host/Race Director**: admit/remove members, configure the event, view shared telemetry, flags, messages, stewarding, publication, canonical branding.
  - **Member/Driver**: publishes telemetry for their own entry via `group/client.py` (native WS, `/group-api/publish`); receives and acknowledges instructions; can send limited responses (acknowledged, pit intent, staying out, request assistance, report incident).
  - **Spectator/Broadcaster**: read-only; runs their own Studio workspaces.
  - Permissions are enforced server-side and deny by default.
- **Joining**:
  - Separate driver and spectator invitations; host address + key; optional admission approval; expiry; join lock/unlock.
  - Credential rotation. Participant removal revokes access; revoking an invitation does not revoke existing members.
  - Members see and consent to sharing categories before joining.
- **Sharing categories** (`group/service.CATEGORIES`):
  - `basic`: position, lap, last/best, flags, car_id.
  - `telemetry`: speed, rpm, gear, pedals, tyres, current_ms.
  - `fuel`: fuel, capacity.
  - `strategy`.
  - Filtering happens on the server.
- **Session formats**: practice, qualifying, laps, timed, manual. Session controls don't control GT7.
- **Host-only mode**: suspends local telemetry and mic acquisition without changing saved settings.
- **Identities**: league, group, event, session, participant, entry, driver and car are all separate IDs; car_id is never used as identity.
  - Entry fields (host-editable): race number, team, class, grid, roster/driver-link reassignment.
- **Timing**: "connected-group standings" labelling; stale detection; qualifying vs race logic; provisional vs host-finalized results. Projection onto the selected layout map is in `group/timing.Projection`.
- **Flags** (`Instruction`):
  - Values: green, yellow, double_yellow, red, blue, white, black, warning (black-and-white), mechanical, checkered, safety_car, fcy, vsc.
  - Scopes: global, zone (marshal zones as progress ranges, wrap-safe), entry.
  - Deterministic precedence: `FLAG_ORDER` (red first) then version. Cancellable; expiry.
  - Applicability is "uncertain" when position is unknown.
  - Separate from GT7 player-status flags.
- **Messages**: scopes all, class, team, entry. Priority, expiry, templates, optional acknowledgement. Statuses: delivered, displayed, acknowledged. Integrated with the engineer subtitle/speech.
- **Stewarding** (`Decision`):
  - Kinds: incident, investigation, warning, time, laps, disqualification, order, correction.
  - Statuses: open, investigating, resolved, withdrawn.
  - Private vs public visibility; audit history of who changed what and why.
- **Hosting**: an explicit LAN listener (port 8090) with an exact origin allowlist. Hashed invitation/member/output credentials; short-lived subscription tickets; bounded frames and rates. Remote use needs a user-managed VPN or an HTTPS/WSS reverse proxy. There's no relay.
- **Rehearsal/league demo**:
  - 4, 8 or 16 synthetic drivers with PRO/AM classes, a generated circuit, 2 marshal zones and a 10-layer workspace.
  - Controls: pause/resume, 1×/2×/4×, simulate disconnect, simulate acknowledgement.
- **Group replay**: recorded group sessions on a shared timeline; exit returns to live. Group recordings are host network samples, not full driver recordings.
- **Storage**: `group_documents`, `group_credentials`, `group_events`, `group_frames` in SQLite.
- **Local admin API** (`/api/group/…`):
  - Group lifecycle: `create`, `configure`, `hosting`, `session/{action}`, `revoke`, `connection`, `connection/response`.
  - Leagues: `leagues`, `leagues/{id}`, `leagues/{id}/assets`.
  - People: `invitations`, `participants/{id}`, `entries/{id}`.
  - Race control: `instructions` (DELETE `instructions/{id}`), `messages`, `decisions`.
  - Map: `map`, `map/library`.
  - Workspaces: `workspaces` (with `/take`, `/clear`, `/credential`, `/share`, `/program`).
  - Read and replay: `state`, `events`, `recordings`, `replay`, `demo`, `assets/{id}/{size}.png`.
- **Public LAN API** (`public.py`):
  - Joining: `/group-api/{info,join,me,state,consent,response}`.
  - Workspaces: `/group-api/workspaces[/{id}[/take|/credential]]`.
  - Streams: `/group-api/ticket`, WS `/group-api/subscribe`, WS `/group-api/publish`.
  - Pages and assets: `/media/{id}/{size}.png`, `/group`, `/overlay/{id}`.
- **Load test** (`scripts/group_load_test.py`, laptop): RSS about 80–105 MB. The scaling limit is overlay viewer count: latency rises from about 220 ms to 0.5–1 s at 60 viewers. The cause is suspected per-tick SQLite re-auth; a fix is proposed, not done.
- **Broadcast Action Director and spatial strategy/coaching** (`group/history.py`, `group/pit.py`, `group/battles.py`, `group/steward.py`, `group/projection.py`, `tyre_heat.py`, `spatial_coaching.py`, `analytics.fuel_scenarios`, `clean_air.py`):
  - **Distance model**: per-entry `DistanceHistory` (`group/history.py`) is a bounded, decimated (≤5 Hz), monotonic-in-distance series of `(common_timeline, race_distance_m)` samples, built once a v3 track model is bound and telemetry is fresh. `interval()` looks up a following car's time-at-distance to get a real (not linear-estimated) gap; `gap_uncertainty()` combines both cars' clock uncertainty in quadrature. Feeds battles, projections and clean-air.
  - **Battle Index** (`group/battles.py`, `GroupService.battle_loop`, 2 Hz): heat-scores every adjacent pair on track from gap, closing rate and recent swaps, with hysteresis (forming → hot → critical → ended) and per-battle-per-alert-kind cooldowns. Desk sees `GET /api/group/battles`, can dismiss or focus one into a workspace (`focus_battle`, 30 s grace period so a flicker doesn't drop the take); drivers never see battle data in their own app.
  - **Steward cue scheduler** (`group/steward.py`): recording a `Decision` while stewarding isn't paused enqueues a timed, priority-preempting overlay cue; `active_cue()` is a pure function of `(cues, now)` so delayed/replay viewers reproduce the same cue history.
  - **Net position / pit-window projector** (`group/projection.py`, `GroupService.projection_loop`, 0.5 Hz): per-entry stops-needed and pit-window math from each car's own reported or host-learned fuel burn; `learned_pit_loss`/`learned_refuel_rate` (`group/pit.py`) fall back to a host-entered value, never a guess. The published (`_public_projection`) view never carries raw fuel litres - rank, stops, net gap, window, pit-loss source and value only.
  - **Tyre heating-rate alert** (`tyre_heat.py`, wired into `engineer.Rules._tyre_heat_events`): EMA-smoothed per-tyre temperature vs a track-position baseline; alerts on a sustained OLS slope + anomaly, with independent hysteresis that keeps accumulating through warm-up/post-pit suppression windows so an alert can fire immediately once suppression lifts.
  - **Spatial braking and micro-coaching** (`spatial_coaching.py`, live path only - no recorded-analysis UI yet): a 10 m-binned `SpatialLap` trace per lap; `LiveBrakingTracker` detects per-corner braking episodes (onset/min-speed/exit, exit measured 50 m past throttle reapplication); `corner_report()` compares the latest lap to a reference lap per corner and attributes a loss to onset/min-speed/throttle-timing, or reports a clean gain with no cause needed. Reachable via voice (`voice.ALIASES`/regex only - not in the fixed 100-entry `requests.CATALOG`) as "how was turn N" / "what cost me the most" / "compare my braking".
  - **Fuel branch scenarios** (`analytics.fuel_scenarios`): on a fuel deficit (or the explicit "what are my fuel options" ask), proposes a SAVE branch (feasible only under `config.max_save_percent`) and a SPLASH branch (needs a known pit loss; adds refuel time only when the rate is known, otherwise says so), overriding to SAVE when a splash would cost a track position on a known gap. `cost_per_l` is OLS-learned from ≥6 comparable laps with ≥3% fuel-used spread, else a labelled default.
  - **Clean-air pit advice** (`clean_air.pit_advice`, `Runtime.clean_air_advice`): on a driver's own app, appended to the "pit" voice answer only when connected to a group with `GroupConfig.share_traffic_with_drivers` on. Projects each shared traffic car's own rejoin position for staying out 0..N extra laps using that car's own lap pace, flags ones that would land within a 2 s window ahead, and recommends the cheapest lap count only if it beats boxing now by ≥1 s. The answer text always describes what boxing *now* would rejoin into; the recommended lap count is the fix, not necessarily still-blocked traffic.
  - **Known scoping gaps**: recorded-lap (post-session) corner-report UI is not built, only the live in-race coaching path; `config.Settings.tyre_heat_rate_c_s`/`tyre_heat_anomaly_c`/`coaching_min_loss_s` exist as schema fields but are not yet wired as dynamic overrides (the tyre-heat and coaching thresholds are still hardcoded constants); battle "recent swap" grouping uses same-tick continuity rather than a true 5 s buffer window.

## 13. Broadcast Studio and OBS `[OK]`
- **Workspaces**:
  - Draft vs Program: Save draft, atomic Take to program, Clear program now (reversible).
  - Drag placement on a 1920×1080 canvas; up to 20 layers.
  - Per-graphic settings: position/size, popup duration, follow-slot or lock-to-entry, title.
  - Shared selection slots: primary, a, b. Modes: manual, leader, class_leader, position.
  - Broadcast delay: bounded, applied to all overlay data (not to driver instructions).
  - Workspace sharing between broadcasters. Discard unsaved changes; reset placement.
- **26 graphics** (`group/models.GRAPHICS`), recommended size in px:

  | Graphic | Size | Needs sharing |
  |---|---|---|
  | timing tower | 440×850 | |
  | session bar | 1200×100 | |
  | flag banner | 1000×130 | |
  | race-control message | 1100×160 | |
  | driver lower third | 900×210 | |
  | selected-car telemetry | 620×260 | telemetry |
  | head-to-head | 1000×300 | |
  | track map | 600×600 | |
  | grid/results | 1200×850 | |
  | league/event slate | 1920×1080 | |
  | fastest lap | 900×160 | |
  | class leader | 680×460 | |
  | penalty/investigation | 1000×160 | |
  | podium | 900×620 | |
  | sponsor rotation | 700×220 | |
  | fuel level | 420×220 | fuel |
  | tyre temperatures | 420×320 | telemetry |
  | pit board | 700×220 | |
  | starting soon | 1920×1080 | |
  | session clock | 420×180 | |
  | classification strip | 1824×180 | |
  | team roster | 700×500 | |
  | lap-time board | 800×520 | |
  | speed comparison | 1000×300 | telemetry |
  | connection status | 700×500 | |
  | event information | 780×440 | |

- **10 style presets** (Style gallery with live swatches): formula, endurance, minimal, neon, vintage, rally, oval, carbon, heritage, holo. System fonts only; no network fonts.
- **OBS output**:
  - A scoped, revocable, read-only URL with the credential in the `#access=` fragment (`&graphic=` for a single graphic).
  - Transparent background; 30 FPS recommended. Composite scene (1920×1080, one subscription) or per-graphic sources.
  - Survives refresh and reopen. Stale data is hidden or dimmed. No controls or secrets on the canvas.
- **League branding** (`LeagueBranding.tsx`):
  - Profiles: name, short name, tagline.
  - Logo plus variants (light, dark, compact, watermark), previewed on light/dark/checkerboard.
  - Colours (primary, secondary, accent, background, text); fonts (system, sans, mono).
  - Sponsors (ordered, toggleable), teams (logo, colour), event overrides.
  - Inheritance: defaults → league → event → workspace → graphic.
  - A branding snapshot is frozen at session start.
  - Uploads: PNG, JPEG or WebP, max 5 MiB. Decoded in an isolated process (5 s limit), re-encoded to 512/1024/2048 PNG variants, originals stored privately. Quotas: 50 MB per league, 1 GB total. SVG is rejected.

## 14. Settings (`config.Settings`, defaults)
- **Network**: `ps5_ip`=null, `udp_bind` 0.0.0.0, `udp_port` 33740, `remote_port` 33739, `http_host` 127.0.0.1, `http_port` 8000, `allowed_origins`, `variant` A, `heartbeat` 1.
- **Display and timing**: `ui_hz` 12, `stale_seconds` 2, `interrupt_seconds` 30.
- **Race assumptions**: `reserve_l` 2, `race_laps`, `race_minutes`, `extra_lap` true, `target_ms`.
- **Engineer**: `mode` Normal, `hard_mute`, `speech_enabled` true, `speech_gap` 8, `speech_per_min` 4, `speech_seconds` 20.
- **Voice**: `tts` espeak|piper, `voice` en-us, `voice_rate` 165, `voice_volume` 80, `piper_model`, `vosk_model`, `input_device`, `output_device`, `mic_rate` 16000, `recognition_confidence` 0.7, `retain_transcripts` false, `hands_free` true.
- **Local AI**: `local_ai_enabled` false, `local_ai_model`, `local_ai_binary`, `local_ai_port` 28380, `local_ai_interval` 45.
- **Alerts and data**: `trust_c_fields` false, `low_fuel_l` 3, `tyre_limit_c`=null, `tyre_imbalance_c` 18, `alert_cooldown` 60, `raw_capture` false.
- **Track and car**: `track_id`, `track`, `layout`, `direction`, `setup_notes`, `pit_limit_kmh`, `pit_region` [minX, minZ, maxX, maxZ].
- **UI and retention**: `theme` dark, `minimal`, `reduced_motion` true, `retention_days` 90.
- **Validation**: the bind address can't equal the PS5 IP; origins must be exact http(s).

## 15. Assets and licences
- **Car assets**: 574 transparent car thumbnails by car_id (`carImages.json`) plus manufacturer logos, with a labelled generic fallback. Provenance: `docs/*provenance*.json`. Rights belong to their holders.
- **Licences**: MIT (gt7-udp, GT7Tracks, gt-telemetry), CC0 track data, Apache-2.0 Vosk model, GPL Piper (optional), ISC Lucide, MIT React and uPlot. See `THIRD_PARTY_NOTICES.md`, `docs/licenses/`.

## 16. Build, test, package
- **Backend**: `.venv/bin/python -m pytest -q` (about 225 pass; a Windows temp-dir `PermissionError` flake happens at fixture setup).
- **Frontend**: `cd frontend && npm ci && npm run build && npm run test:e2e` (Playwright uses installed Chrome against an isolated instance, e.g. `data-frontend-dev`, `data-preview`).
- **Other**: `scripts/soak.py --seconds N --rate 60`; `run.py diagnostics`.
- **Packaging**: `scripts/package-windows.py` (portable x64 zip with bundled Vosk model), `package-linux.py` (ARM64 .deb), `verify-release.py`.
- **Dependencies**: `requirements-lock.txt` (core), `-voice.txt` (vosk, sounddevice), `-desktop.txt` (pywebview). Node is only needed to rebuild the UI.

## 17. Known gaps and housekeeping (agent attention)
1. **The v3 track system is not wired into runtime, API or UI.** Runtime still uses `tracks.py`, and Race Control still uses `group/timing.Projection`.
2. Track bundle optimization (packing, LOD, lazy loading, ETag) hasn't been done. The bundle is about 7.9 MB gzipped, and the models' retained memory measured about 13.9 MB.
3. Overlay scaling: per-subscriber SQLite re-auth every tick. A fix is planned but not done.
4. No verification inside OBS itself, and no multi-hour hardware soak.
5. No corner coaching, custom sectors, pit-loss model or full incident detection.
6. Stale docs: README still describes the Orange Pi target and "two CPU threads" for local AI, and docs are spread across many files. `IMPLEMENTATION_STATUS.md` is newest-first and historical below the top.
7. Repo hygiene:
   - `data-frontend-dev/telemetry.sqlite3` (~6 GB) and `data-preview/` aren't covered by `.gitignore` (which ignores `/data/` and `*.db*` only).
   - The project folder is inside OneDrive (SQLite WAL on a synced folder is risky).
   - `release/` binaries are in the repo tree.
8. Code style: older modules use dense one-line style; newer track modules are formatted (ruff/black). When editing, keep changes local and don't reformat unrelated code.

## 18. Architecture foundation (added 2026-09-30; details in `docs/architecture/`, ADRs in `docs/adr/`)
- **Layers**: `backend/app/core/` (depends on nothing: registry, errors/`AppError`+`ResultCode`, lifecycle `ServiceRegistry`, events, features, permissions/roles, commands+dispatcher, config migrations, logging, platform, modules, defaults, version) → `telemetry/` (parser re-exported, `frame` channel registry, `derived`, `units`, `bus`, `sources`+scenarios), `domain/` (annotations, alerts, insights, training defs), `storage/` (Store, schema v3, repositories, layout, exports/imports, retention, audit) → feature modules → `runtime.py` composition root → adapters (`api.py`, `group/admin.py`, `group/public.py` are the only fastapi importers; `tests/test_architecture.py` enforces edges, bounded queues, no `sys.platform` outside `core/platform.py`).
- **Runtime**: `Runtime.consume()` publishes a `TelemetryFrame` on `TelemetryBus`; subscribers wired in `_wire_bus` in the original order (driver_line, track_map, training, track_service, live_delta, live_analysis, reception_test, sessions, coaching, rules, derived@20Hz, dev_packets@10Hz). A failing subscriber is isolated and counted (`pipeline_errors`). Services (`runtime_services.build_services`, 10) expose `ServiceStatus` via `GET /api/services` and `snapshot()['services']`.
- **Commands**: `POST /api/commands/{id}` → `core.commands.dispatch` (capability, rate, schema, confirm, audit). Catalogue in `commands_catalog.py` (55+ ids incl. group/raceControl/graphics); legacy routes are shims over `control.py`/`operations.py`. Audit rows in `audit_log` (`GET /api/audit`).
- **Safe mode** (`safe_mode.py`): `--safe-mode`, unclean shutdown (`data/.running` marker), invalid settings or storage failure → no heartbeat/mic/local AI/experimental flags until `safe_mode.leave`.
- **Contracts**: `python scripts/gen-contracts.py` regenerates `docs/architecture/CONTRACTS.md` and `frontend/src/domain/*.generated.ts` (`tests/test_contracts_fresh.py` fails when stale).
- **Frontend**: `frontend/src/domain/` (http, api clients, commands, permissions, units, channels, stores); components never call `fetch` (`npm run check:arch`).
- **Group protocol v2**: `group/protocol.py` (envelope, hello/negotiate, message registry, `ReliableChannel`), `group/snapshots.py`, `group/principals.py` + `core/permissions` for every capability check, `group/migrations.py` for document upgrades, `group/graphics.py` template registry.
- **Simulation**: `run.py --demo --scenario NAME` / `Settings.demo_scenario` (deterministic, SYNTHETIC). Developer mode: `/api/dev/packets`, `/api/dev/scenarios`.
- Known gaps: see `docs/architecture/TECH_DEBT.md` (30 items).
