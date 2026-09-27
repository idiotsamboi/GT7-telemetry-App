# Validation log — 2026-09-24

## Executed

- `.venv/Scripts/python.exe -m pytest -q`: **65 passed**, one Starlette TestClient/httpx deprecation warning, 8.48 s.
- `.venv/Scripts/python.exe -m pytest tests/test_protocol.py tests/test_udp.py -q`: **30 passed**, 3.24 s.
- `npm run build` in frontend: TypeScript + Vite **passed**. Bundled output includes local React/Lucide assets and lazy-loaded uPlot.
- `GT7_TEST_URL=http://127.0.0.1:18080 node node_modules/@playwright/test/cli.js test`: **1 passed**, 16.3 s total (8.3 s test), using installed Chrome. Covers demo stream, engineer command, settings save, 360 px overflow check, End Session → Analysis, session history, and absence of page errors. Test server has a separate data directory/port.
- `scripts/soak.py --seconds 20 --rate 600`: **12,000 samples**, no queue drops or failed rows. Detailed Windows-only synthetic results: benchmark.json.
- ARM64 Python 3.10 core dependency wheel resolution/download: passed. Vosk 0.3.45 aarch64 and sounddevice 0.5.2 wheel availability: passed. wsproto 1.3.2 is pure Python.
- Frontend npm audit after updating Vite 6.4.3 and Playwright 1.63.0: zero reported vulnerabilities.

## Problems found and fixed during checks

- Missing Uvicorn WebSocket transport: added and locked wsproto.
- Source switch incorrectly triggered Analysis: transition now checks source continuity.
- Monotonic timestamp collisions could omit paged export/replay records: added record-ID cursor pagination and a regression test.
- UDP/parser failures lacked actionable distinction: added classified parser errors and receiver phases/counters/owner diagnostics.
- Network configuration saved without reopening an existing socket: console/UDP changes now reconnect; covered by an actual socket test.
- A parser exception could stop reception: per-datagram fault boundary tested by injecting a parser exception, then confirming the next valid packet records.

## Not established

No successful live PS5 receipt, physical microphone/TTS output, Orange Pi execution or multi-hour endurance test. Three Tractivvity Telemetry Agent processes held UDP 33740 during the live diagnostic. They were left running pending the user's choice. Synthetic crypto fixtures and loopback UDP are not hardware certification.

Screenshots: screenshots/live-desktop.png, screenshots/live-phone.png, screenshots/analysis-desktop.png. These display explicitly labeled synthetic data.

## Release 1.1 beta validation
71 backend tests and 3 Chromium browser workflows passed. Frozen Windows EXE: local HTTP backend, compiled frontend, Vosk model loading, 584-car database, 45 enumerated audio devices, and native Edge WebView2 dashboard verified. See windows-frozen-self-test.json and windows-frozen-webview-test.json. Audio enumeration/model decode does not establish physical microphone recognition or audible speaker output. Initial nonintrusive PS5 test received 900 packets at 60 Hz with zero reported loss/errors. Linux Debian archive and offline ARM64 CPython 3.12 dependency resolution checked; no Orange Pi hardware test.

Final archives: checksums and contents verified by scripts/verify-release.py, with no generated control tokens, settings or recordings included. Backend import regression passed after removing import-time configuration creation. Final CSS build and manufacturer-panel browser regression passed. The compact desktop keeps the driving-line panel visible.

## Engineer release 1.2.0
179 backend tests passed, including every one of the 100 request intents and all three rotating reply forms. Four browser workflows passed (the new library/device workflow was rerun after correcting an accessible-role assertion). The frozen Windows 1.2.0 executable returned all 100 requests, rotated three radio replies, and generated/played 307086 PCM frames over 6.96 seconds to the default 29EA93 Intel Display Audio device with no error. Device-rate conversion was verified in the frozen module. Completion confirms the software/device playback path; physical audibility still depends on the selected endpoint and its hardware volume. See speaker-validation.json and frozen-engineer-validation.json.

Driver line circuit-exit update: 185 Python tests pass. Automatic clearing on off-track telemetry, lap rollback, car change and session interruption; pause/loading preserves the line and does not append positions. Live delta references reset with the line. Circuit exit without further packets is handled by the configured session interruption timeout.

### Reception recovery — 2026-09-25
The receiver launched by the development tool inside its offline sandbox bound UDP 33740 and counted send attempts but received zero packets. The PS5 at 192.168.88.67 responded to ping. Restarting the identical source outside that sandbox, with LAN permission, immediately restored reception. Do not launch a live PS5 receiver inside an offline/network-restricted development sandbox. Use the normal desktop launcher or a tool execution explicitly authorized for LAN access; do not disable firewall rules.

Verification: one UDP 33740 owner (GT7 backend); SIMDashboardServer was on UDP 39897, not the GT7 port. No changes to socket binding, heartbeat logic or packet parsing were required. A 15-second test received 900 A packets at 60 Hz, all 42 A fields present, zero sequence gaps, duplicates, parse/pipeline errors or storage drops/failures. See reception-recovery-validation.json. The circuit-exit reset and transparent-logo changes remain enabled.


## 1.3.0 audit and hands-free validation
190 Python tests and five browser workflows passed. All referenced logo and model assets exist; manufacturers without a supplied logo use a named fallback. Production npm audit: zero vulnerabilities. pip check: no broken requirements. Actual microphone capture and local Vosk phrase recognition passed. Live heartbeat trials covered 1, 0.5 and 0.25 seconds; all sustained approximately 60 Hz with occasional UDP sequence gaps and no parse/pipeline/storage errors. Repeated comparison did not establish that heartbeat frequency caused those gaps. Current user setting is 0.25 seconds; conservative new-install default is 1 second. See program-audit.json, recognition-validation.json, heartbeat-handsfree-validation.json and heartbeat-confirmation.json.

Windows package smoke test passed after repairing a missing Tcl/Tk launcher payload. The actual frozen 1.3.0 app started its default microphone worker, reached listening at 16 kHz without errors, and exposed all 100 requests. Release verification now requires the Tcl/Tk runtime files in addition to model and UI assets. Both 1.3.0 archives pass integrity and checksum checks. See frozen-handsfree-validation.json and release-validation.json.
