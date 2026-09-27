# Performance and endurance validation

## Actually measured on this development machine

See `docs/benchmark.json` for the recorded run: Windows x64, Python 3.12, synthetic input, no speech model or browser in the benchmark. 12,000 samples in 20.071 seconds (~597.9 samples/s), p95 per-sample ingestion work 1.271 ms, initial incremental report 1.160 ms, writer queue peak 61, **zero queue drops or failed rows**. Database bytes after this run: ~50.0 MB; WAL ~4.66 MB. These numbers are not board acceptance and not receive-to-visible latency.

The parser/schema is intentionally comprehensive and SQLite currently stores JSON per sample. The measured ~4 KB/sample disk footprint implies roughly 0.9 GB/hour at 60 Hz before optional raw capture, index/free-space variations and exports. Raw encrypted capture adds up to 736 hex characters plus JSON overhead per C packet. Use local SSD storage when possible. Disk-space warning defaults to 500 MiB. Retention cleanup is not automatic in this delivery.

Core Python Linux ARM64 wheels were resolved/downloaded using `pip download --platform manylinux2014_aarch64 --python-version 310 --abi cp310 --only-binary=:all:`. Vosk 0.3.45 provides an aarch64 wheel; sounddevice 0.5.2 is pure Python but needs native PortAudio. This verifies artifact availability, not audio device operation or Orange Pi performance. `wsproto` is a pure-Python WebSocket dependency added after the browser test exposed its necessity.

## Reproduce

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/soak.py --seconds 30 --rate 60
.venv/bin/python scripts/soak.py --seconds 60 --rate 600
.venv/bin/python scripts/soak.py --hours 4 --rate 60 --output docs/soak-board.json
```

The soak harness generates deterministic samples through session/recorder/rules. It uses a temporary database removed when done, bounds latency measurements to 100,000 entries, and prints counts, CPU time, p95 work latency, report time, queue peak, DB/WAL bytes and losses. It does **not** exercise UDP encryption, actual playback/recognition or browser load; do not call it a complete hardware soak.

For board acceptance: run diagnostics, live GT7 with full-rate logging for several hours, one/multiple browser clients, Vosk PTT and TTS active, and repeated mute/end actions. Record total RSS of all app workers plus browser, CPU, thermal state, p95 displayed age, write backlog and precise recording gaps. Test PS5 restart, Wi-Fi loss, game pause/menu, refueling, car/track change, full/slow disk and microphone unplug/replug. Test actual C offsets/units before enabling C interpretation. None of those physical tests ran here.

Targets remain: stable 60 Hz receipt/logging, 10–20 Hz display, p95 visible age around 200 ms, app RSS ~1.25 GB or less, browser-inclusive memory ~2 GB, initial summary ~2 seconds. Current UI shows server sample age, not a calibrated receive-to-screen measurement. Unix health reports peak RSS for the main process, not aggregate worker/browser memory.

Degradation has hysteresis: >4,096 writer jobs, >200 ms loop lag or >80°C for >3 seconds enables 4 Hz UI; 20 stable seconds restores the configured rate. This version does not automatically switch speech models, stop raw capture, or implement all requested resource-shedding stages. Bounded queues limit backlogs, but measured endurance evidence on the Orange Pi is still required.

## Race Control / Broadcast group load test

`scripts/group_load_test.py` is a separate, standalone diagnostic (requires `pip install psutil websockets` in the active environment; not part of the app's own requirements) that runs the real app, enables the LAN group listener, drives the built-in synthetic league demo at 4/8/16 drivers, and opens 1/8/32/60 concurrent overlay WebSocket subscribers against it — the same connection type an OBS Browser Source or spectator page uses. Results: `docs/group-load-test-validation.json`. Summary and the identified bottleneck (per-connection re-authentication, not snapshot computation) are in `docs/RACE_CONTROL.md`.

The Orange Pi 4 GB hardware target has been dropped in favor of general lightweight operation on whatever host runs the app; local-AI inference thread count now scales to the host's CPU count instead of a fixed value tuned for a 6-core board. `psutil` is used as an optional cross-platform fallback for the memory-pressure check when `/proc/meminfo` is unavailable (Windows/macOS); its absence degrades gracefully to "unknown," matching prior non-Linux behavior — it is not a hard dependency of the shipped app.
