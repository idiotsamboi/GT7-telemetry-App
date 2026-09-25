# Native Orange Pi installation

## Before installing

Use the Orange Pi Ubuntu image appropriate to your board. The vendor's Orange Pi **4 Pro** description is Allwinner A733, two Cortex-A76 plus six Cortex-A55 cores; other Orange Pi 4 variants differ. Do not infer your actual machine from the product name. `run.py diagnostics` reports architecture, OS, Python, `/proc/device-tree/model`, memory, disk and audio devices. CPU-only is the supported baseline. No GPU/NPU assumptions are made.

Connect the Orange Pi and PS5 to the same LAN, preferably wired. Confirm the PS5 address in its network settings. A DHCP reservation is helpful. Stop other GT7 telemetry receivers using UDP 33740.

## Install

1. Copy this directory to local storage, preferably an SSD. A microSD works but endurance logs are large.
2. Open a terminal in this directory.
3. Run `bash scripts/install-ubuntu.sh` as your regular user. It uses sudo only for apt packages, creates `.venv`, installs the lockfile and runs diagnostics. It never replaces system Python.
4. Run `bash scripts/launch.sh --demo` and open `http://127.0.0.1:8000`.
5. Try End Session, Analysis, Sessions, replay and bundle export before using the console.
6. In Settings enter the PS5 IP, save, then select Use PS5. Select packet A initially. Current-lap C timing requires selecting C and deliberately enabling its interpretation after verification.
7. Start driving. The header should show incoming Hz, freshness and recording. If not, stop the app and run `.venv/bin/python run.py connection-test --ps5 YOUR_PS5_IP`.

Console/UDP changes reconnect immediately. HTTP settings require restart. A missing response in a menu is not evidence that C/B/~ is unsupported. Try A manually if extended formats fail in a supported driving context; this version does not auto-probe or change variants mid-session.

## Offline microphone and TTS

```bash
.venv/bin/pip install -r requirements-voice.txt
.venv/bin/python scripts/download-model.py --accept-license
```

The explicit download is Vosk small English 0.15, approximately 40 MB, Apache-2.0. Review [Vosk models](https://alphacephei.com/vosk/models). The script records a SHA256 and can verify a supplied trusted `--sha256`; no publisher hash is invented. No model is downloaded at startup.

Set `vosk_model` to the absolute extracted model directory. In Settings, inspect device indices, select input/output and use the two-second calibration and recording/playback tests. PortAudio must support the selected mono sample rate (default 16 kHz); unsupported device/rate combinations show an error rather than silently misrecognizing. Automatic resampling and wake-word listening are not implemented.

Enable local spoken output; eSpeak NG is the default. Initialize the offline microphone in Engineer. Hold to talk uses the **Orange Pi microphone**, not the phone's microphone. A local browser's focused PTT button also supports Space on an attached keyboard or USB device acting as that key. PTT interrupts output, then starts capture after a short guard. Recognition stops on release or after 12 seconds. Raw recordings are kept only in memory. No cloud recognizer is used.

Use desktop PipeWire/PulseAudio routing for your headphones or speakers. It does not inject audio into a PS5 headset. A wheel plugged into the PS5 does not automatically expose its buttons to the Orange Pi. Remote-browser microphone transport and browser speech output are not implemented.

Optional Piper: install the current [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) CLI in a separate environment or discoverable executable path, review its GPL license and the selected voice's model license, then configure the `.onnx` path and choose Piper. This route also needs sounddevice/numpy playback. eSpeak remains the dependable baseline. Piper is not installed automatically or hardware-tested here.

## LAN access and pairing

Loopback is the default. To opt in, set `http_host` to your Orange Pi interface address (or `0.0.0.0`) and add the precise browser origin, e.g. `http://192.168.88.40:8000`, to `allowed_origins` in `data/settings.json` while stopped. Restart. On another device open that origin and enter the value stored locally in `data/control-token`. Do not expose this service to the public internet. Do not disable your firewall globally. Only allow the required ports on your trusted LAN.

Control and data endpoints require a paired HttpOnly SameSite cookie or `X-Control-Token`. WebSockets check the configured origin and cookie. The health endpoint only exposes service liveness. HTTP does not encrypt LAN traffic. For encryption, place an explicitly configured HTTPS reverse proxy in front of loopback, use a trusted certificate, add its exact HTTPS origin, and ensure only that proxy can access the backend. Do not bypass browser certificate warnings. Remote browser microphone support is absent, so HTTPS alone does not add that feature.

## Headless / service

The app works with no local browser. Enable the service only when wanted:

```bash
bash scripts/install-service.sh
journalctl --user -u gt7-engineer -f
systemctl --user stop gt7-engineer
systemctl --user disable gt7-engineer
```

This is a user service. Desktop audio depends on that user's audio session. Do not run it as root to try to fix audio. User lingering is not enabled automatically; headless audio routing needs explicit host setup. The service sets conservative OpenMP/BLAS thread limits.

## Retrieving recordings

End Session → Analysis gives the immediate summary. Sessions → View analysis opens a saved report; Printable report can be printed to PDF, and Session bundle downloads CSV, metadata, raw sample JSONL, HTML and checksums. Shut down cleanly before copying the entire data directory; copy the database and WAL together if you cannot stop. Use the safe backup command documented in TROUBLESHOOTING for a running database.
