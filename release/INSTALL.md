# GT7 Race Engineer desktop 1.1

Target: Orange Pi 4 Pro with 4 GB RAM, running an **ARM64 Ubuntu 24.04 desktop** with Python 3.12. This package is not for Android, 32-bit Linux, Ubuntu 22.04, or a headless system. Hardware execution has not yet been validated on the Orange Pi.

Copy `gt7-race-engineer_1.1.0_arm64.deb` and its `.sha256` file onto the board, open a terminal in that folder, then run:

```sh
sha256sum -c gt7-race-engineer_1.1.0_arm64.deb.sha256
sudo apt install ./gt7-race-engineer_1.1.0_arm64.deb
gt7-race-engineer
```

Alternatively launch **GT7 Race Engineer** from the applications menu. Apt needs network access for missing system packages. The application, Python wheels, compiled interface, and English Vosk model are bundled; first-launch Python setup and subsequent operation are offline. No Node installation or separate browser is needed. The GTK desktop window uses the system WebKit renderer and a loopback-only backend. Closing the window shuts down its receiver and flushes recording.

Enter the PS5's current LAN address in Settings, save, start driving, then select **Test telemetry - 15 seconds**. This observes the existing receiver without changing packet format or stopping recording. It reports sequence gaps, rejected packets, storage failures, reception pauses, rate, field coverage, and unavailable fields. Healthy reception does not validate undocumented field meanings. Menus or a stopped game may produce no data.

Real-time analysis is on the **Telemetry** page. It reports measured longitudinal acceleration, trailing coasting/pedal overlap, tyre surface temperature spread, and recent braking episodes. It does not infer grip, tyre wear, racing line quality, or time gain. Advanced corner/reference coaching remains future work.

Audio input and output default to the operating system devices (blank device indices). Select the desired devices in Ubuntu Sound settings. The small English Vosk model is included and selected automatically. Enable spoken output and initialize the offline microphone in Engineer; use Hold to talk. eSpeak NG is installed as a system dependency. Physical audio and microphone operation require board validation. Model source: https://alphacephei.com/vosk/models (small English 0.15, Apache 2.0).

The desktop defaults to six display updates per second; causal analysis samples at five Hz with 150 retained points. Recording keeps the full incoming stream. Vosk runs in a separate process, loads on microphone initialization, and uses push-to-talk. No GPU inference or cloud service is required. CPU, memory, thermal behavior and long-race stability must still be measured on your actual board; 4 GB is a target configuration, not a measured memory guarantee.

User settings, SQLite recordings and logs are under `~/.local/share/gt7-race-engineer` (or `$XDG_DATA_HOME/gt7-race-engineer`). Packaged model and assets are read-only under `/opt/gt7-race-engineer`. Setup errors are in `install.log`; backend startup errors are in `desktop.log`. Never launch the application with sudo. Removing the Debian package leaves your user recordings intact. Do not run the old background receiver/service alongside the desktop app: only one program can own UDP 33740.

Build: install frontend dependencies and build `frontend/dist`; run `scripts/download-model.py --accept-license`; prepare the ARM64 CPython 3.12 wheel set from `requirements-desktop.txt` into `data/linux-wheels` (build the pure-Python srt wheel first); run `python scripts/package-linux.py`. The package includes third-party license notices and wheel metadata/licenses. The downloader records an observed SHA256; this is not a publisher-signed checksum.
