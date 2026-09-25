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
