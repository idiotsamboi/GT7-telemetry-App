# Current source update: circuit maps and race artwork

41 venues / 122 layouts are selectable in Live Race, with local logos or original text badges. A bounded 4096-point capture learns a full continuous driving path after the initial partial lap and persists live maps by chosen layout. JSON import/export uses validated world coordinates. Selection is manual, not automatic circuit identification. 574 official transparent car thumbnails are local; missing images show a labelled generic fallback. README and docs/USER_GUIDE.md describe the current source features and startup steps. Existing 1.3.0 archives have not been rebuilt for this update.

Local AI evidence ranking, pit-intent cancellation and source launcher interpreter recovery are also implemented. Orange Pi hardware validation remains outstanding.

# Audit and hands-free update 1.3.0

Hands-free microphone operation now starts automatically, handles Vosk end-of-utterance results, resumes after each command, and suppresses recognition during engineer speech plus a 0.6-second tail. Microphone errors are visible; failed workers retry after 30 seconds. Device/model changes restart the microphone. Manual PTT remains available when hands-free is disabled. No raw microphone audio is retained.

Fixed optional empty text settings, loading/off-track metric accumulation, replay-seek delta references, and unhandled audio/capability fetch failures. Heartbeat is configurable from 0.25 to 15 seconds, with a 1-second default. It is a keepalive, not telemetry sampling frequency. Hardware comparison results are in docs/heartbeat-handsfree-validation.json and docs/heartbeat-confirmation.json.

Audit: 190 Python tests and five Playwright workflows passed, all 53 referenced brand images exist, all required Vosk model components exist, Python dependencies are consistent, and npm reported no production vulnerabilities. Actual microphone capture runs on the default Realtek device at 16 kHz; three synthesized requests decoded correctly through the actual offline Vosk model. Physical voice accuracy depends on microphone placement/background noise. Orange Pi hardware operation remains unverified.

Historical status follows; newer entries supersede older test counts and feature notes.

# Engineer update 1.2.0

100 distinct offline requests and 300 response forms are implemented, tested, and searchable in Engineer. Speech is enabled for new configurations; Resume engineer also enables it. Named device selection, speaker-only testing, waveform validation, device-rate conversion, and explicit playback/error state are available. Actual source and frozen Windows speech tests completed successfully through the default display-audio endpoint. The Windows and ARM64 Linux release artifacts are version 1.2.0. See VOICE_COMMANDS.md for the complete catalogue.

# Windows beta and broadcast update

Windows x64 portable beta is in release/GT7-Race-Engineer-1.1.0-beta-windows-x64.zip. Frozen executable model/backend/audio-library smoke test and actual Edge WebView2 rendering passed on this PC. The launcher offers native-window and browser modes without a console. Broadcast styling, semantic channel colors, clutch display, offline brand identities, unavailable race-flag/sector indicators, and bounded live delta alignment are implemented. Validation: 71 Python tests and 3 Playwright workflows passed. Linux ARM64 package rebuilt with the same interface; Orange Pi hardware execution remains unverified.

# Desktop release 1.1 update

See `release/INSTALL.md` for the Ubuntu 24.04 ARM64 desktop package. Live PS5 reception was independently verified on 2026-09-24: a 15-second observation received 900 valid A packets at 60 Hz with zero sequence gaps, parsing errors or storage drops. Prior C-format reception also validated. Vosk small English downloaded from its publisher and loaded successfully; default audio devices configured. Settings now has a nonintrusive reception test; Telemetry has bounded causal analysis. GTK/WebKit desktop packaging includes ARM64 Python wheels and model. Orange Pi installation, physical audio and sustained thermal/RAM performance remain unverified. Full advanced corner/reference coaching is not complete. Earlier status below is historical and may be superseded by this update.

# Implementation status — September 24, 2026

The application is runnable end to end. **The original full specification is not completely implemented, and live PS5/Orange Pi/audio acceptance is not established.** The original request is preserved verbatim in docs/ORIGINAL_REQUEST.txt. No feature is considered complete merely because it has a card or API name.

## Implemented, with automated checks

- [x] Native A/B/~/C Salsa20 parser; classified errors; explicit packed offsets; null extension reset; raw timing sentinels and signed packet bits retained; parser/version/length metadata.
- [x] Independent synthetic encrypted fixtures and Salsa20 known vector; all declared offsets checked by parsing the pinned C++ header declarations.
- [x] Actual loopback UDP integration: heartbeat send/repeat, independent encrypted datagrams, sender filtering, mixed variants, duplicates/reordering/gaps and recovery after malformed data or an injected parser exception.
- [x] Receiver diagnostics: bind/heartbeat/no-data/rejected/receiving phases, counts, last sender/length/variant/error and competing port-owner PIDs. Names depend on OS permissions. Does not stop other apps or share their UDP socket.
- [x] Console/UDP changes reconnect immediately, closing the old receiver; demo/replay send no heartbeats. HTTP changes still require restart.
- [x] Session/lap UUID epochs, pause handling, partial/incomplete laps, car/lap/source resets, manual end and interrupted reports.
- [x] Bounded single-writer SQLite WAL recorder, batches, recovery status, loss counters and record-ID pagination preserving equal-timestamp packets.
- [x] Built React interface with seven pages, uPlot, player trace, source/stale labels, loopback pairing, semantic styling, phone and compact landscape layouts.
- [x] Clean-lap fuel median and reserve margin with partial-lap timing fraction; pace mean/median/deviation/trend; coasting/overlap/limiter summaries and repeated-evidence cards.
- [x] Compatible recorded-lap spatial projection comparison, corridor/continuity rejection and braking episodes. Approximate fallback is explicitly labeled and not presented as precise live delta.
- [x] Central scheduler: bounded priority queue, supersession, hard mute, expiry, session invalidation, cooldown, quota, workload deferral and cancellation.
- [x] Session bundles with CSV/JSONL/metadata/printable HTML/checksums; bounded validated import; replay pause/speed/restart; full original data retained.
- [x] Ubuntu venv installer, launcher, diagnostics/connection-test, explicit model-download script, opt-in user service, safe backup and configurable soak harness.

## Implemented paths that require further validation

- Offline Vosk/sounddevice microphone worker, fixed command grammar, confidence threshold, PTT interruption/guard, device selection and in-memory calibration/playback. No physical microphone/model test was run here.
- eSpeak NG output and optional current Piper CLI/model playback. No audible output validation here. Engines/models are not all installed automatically.
- Linux ARM64 package availability checked for the core lockfile and Vosk/sounddevice wheels; no Orange Pi execution, memory/thermal/audio test or board-specific installer test.
- Packet C semantics remain opt-in and hardware-unverified. Source layout confidence is not a claim that every upstream interpretation is correct on the user's game build.
- Metadata/protection and profile APIs work with existing UI controls. Newly added archive/restore/retention/purge/manual-correction backend routes are development work; complete UI and dedicated acceptance coverage remain pending.

## Actual results so far

- Latest full Python suite: **65 passed**, one upstream Starlette TestClient deprecation warning. Includes 30 parser/UDP-focused cases.
- Production TypeScript/Vite build: passed; assets are included in frontend/dist.
- Full browser workflow: passed on installed Chrome at 1440×1050 and 360×800 before the latest parser diagnostics rebuild; final rerun result is recorded in docs/VALIDATION.md. Screenshots are in docs/screenshots.
- Synthetic stress: 12,000 records in 20.071 s (~598/s), p95 ingestion work 1.271 ms, initial report 1.160 ms, zero recording drops/failures. Windows-only, no audio/browser in that benchmark; see docs/benchmark.json.
- Frontend dependency audit after patched Vite/Playwright upgrades: zero reported vulnerabilities at check time.

## Live connection blocker observed

The visible instance uses the user's configured PS5 address and retains it across updates. Three Tractivvity Telemetry Agent 3.7.9 processes occupied UDP 33740 during diagnosis (PIDs 12348, 20760, 24588). Our application therefore had **zero received live datagrams**. Those processes were not terminated. Close competing receivers and start driving to perform the real-console acceptance step. Do not interpret passing synthetic/local UDP tests as PS5 compatibility evidence.

## Remaining original-request gaps

1. No confirmed automatic race-finish provider; manual completion and timeout interruption are implemented. Track changes/official validity cannot be inferred reliably from the base stream.
2. No learned track fingerprint, corner/split editor, custom-sector/theoretical-best engine, live reference delta/projected-lap calculation or fully validated crossing/bridge alignment library.
3. No complete pit/stint/pit-loss model, conserving-versus-stop time scenarios or the full requested advanced incident/driver coaching families. No understeer/oversteer diagnosis.
4. No wake phrase/VAD, remote-browser mic/audio endpoint, arbitrary spoken notes/target times, robust device resampling/reconnect, phrase cache or comprehensive audio latency testing.
5. Telemetry exploration is bounded paged overview plus chart zoom; automatic full-resolution zoom fetch, every multichannel array selection and distance-axis tools need expansion.
6. Complete session/profile editing, reference library/personal best search, archive/retention controls and per-car/per-track inheritance UI remain incomplete.
7. No process-isolated deep analysis worker. Comparisons are bounded and run off the receive loop in a thread; CPU/GIL effects still need board measurement.
8. Resource degradation currently reduces UI rate with hysteresis. Aggregate worker/browser RSS, calibrated receive-to-visible latency and other proposed shedding stages are incomplete.
9. Large endurance bundle imports are capped; no Parquet export or standalone chart-image export. Crash recovery preserves committed samples but provisional reports may stop at the previous aggregate checkpoint.
10. No multi-hour hardware soak or stress with actual speech, multiple slow clients and disk exhaustion has been run. Transaction-failure tests are not a physical full-disk test.

Latest user priority: make the telemetry parser/receiver actually work. Work is focused on that path before expanding the remaining analytics/UI breadth.
