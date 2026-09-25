# Desktop release

The Ubuntu 24.04 ARM64 desktop build and installation instructions are in [release/INSTALL.md](release/INSTALL.md). It includes Vosk, default audio devices, a red interface, live reception testing, and initial real-time analysis. Orange Pi hardware validation is still required.

# GT7 Race Engineer

A local-first Python and React race engineer for Gran Turismo 7. Receives encrypted PS5 UDP telemetry, records unique samples at arrival rate, runs a throttled engineer, serves a live dashboard, and prepares session reports. No cloud service, API key, Docker, Electron or Node runtime is required.

**Delivery status:** a working end-to-end application, with important advanced requirements still incomplete. Read [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) before relying on any feature. No PS5, Orange Pi or physical audio testing has been performed here. Synthetic demo data never proves hardware compatibility.

## Quick start: Ubuntu / Orange Pi

```bash
bash scripts/install-ubuntu.sh
bash scripts/launch.sh --demo
```

Open **http://127.0.0.1:8000**. The demo has visibly labeled synthetic data and 30-second laps. End Session opens the report immediately. Sessions lets you inspect recorded data, replay it, protect it, and export a bundle. Production assets are already included in `frontend/dist`.

For your PS5, open Settings, enter its current IP, save, restart, and select Use PS5. `192.168.88.21` is only your previous address suggestion. Default local bind: `0.0.0.0:33740`. Heartbeats go **to** the PS5 at UDP 33739. The web UI listens separately on loopback TCP 8000. Never put the PS5 IP in the local bind field. Start driving in GT7; menus can legitimately be silent.

Read [INSTALL_ORANGE_PI.md](INSTALL_ORANGE_PI.md) for microphone models, audio routing, LAN pairing, native installation and the opt-in user service.

## Windows development launch

The current workspace already has an isolated environment:

```powershell
.\.venv\Scripts\python.exe run.py --demo
```

For a fresh checkout on a development machine:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python run.py --demo
```

Windows equivalents use `.venv\Scripts\python.exe`. Python 3.10+ is supported; development tests ran on Python 3.12. Node 20.19+ is needed only to rebuild assets. Use one server process and one worker. The receiver ownership lock rejects a second instance.

## Useful commands

```bash
.venv/bin/python run.py diagnostics
.venv/bin/python run.py connection-test --ps5 192.168.88.21
.venv/bin/python -m pytest -q
.venv/bin/python scripts/soak.py --seconds 30 --rate 60
.venv/bin/python scripts/soak.py --hours 4 --rate 60 --output docs/soak-local.json
```

Browser tests: start the application on port 8000, then `cd frontend && npm run test:e2e`. The checked-in test defaults to installed Chrome; set `PW_CHANNEL=msedge` for Edge. For a downloaded Playwright Chromium, remove the channel setting and run `npx playwright install chromium` first. Tests use a separate data directory, for example `python run.py --data data/browser-test`.

## What is real

- Explicit A/B/~/C parsing, Salsa20, sender checks, modular packet ordering, reconnect and stale detection.
- Bounded SQLite WAL writer with sample loss counters, session recovery and source provenance.
- Seven functional dashboard views; telemetry charts, player trace, session history, strategy inputs and diagnostics.
- Vosk offline PTT worker, eSpeak NG speech, optional Piper subprocess, priority/expiry/cooldown arbitration, hard mute and stop.
- Clean-lap fuel estimates, pace statistics, coasting/overlap/limiter observations, reports, compatible spatial lap comparisons and braking episodes.
- CSV/JSONL/HTML bundle export, checksum-validated bounded import and recorded-sample replay.

Unsupported facts (leaderboard, opponent radar, official validity, penalties, damage, tyre wear/pressure, official finish) are not fabricated. See [DATA_FIELDS.md](DATA_FIELDS.md) and the in-app registry. C timing/surface semantics remain explicitly opt-in until checked on the actual game build.

## Data and privacy

Default data lives in `data/`; use `--data /local/ssd/gt7` to change it. Do not run the live WAL database on a network share. This workspace happens to be in OneDrive: use an unsynced local data directory for real recording. No raw microphone audio is retained. Transcript display is opt-in and in memory. All production web assets are local. Model downloading is a separate explicit command.

Never treat a disconnected session as a confirmed race finish. End Session records a user-confirmed completion; stale telemetry eventually creates an interrupted report. Reports retain incomplete laps and application quality flags separately from unknown game validity.

Protocol primary source: [MacManley/gt7-udp](https://github.com/MacManley/gt7-udp), pinned in [PROTOCOL.md](PROTOCOL.md). Source, license and original request are preserved in the repository.
