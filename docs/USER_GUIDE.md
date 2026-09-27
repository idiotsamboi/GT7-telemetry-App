# New-user guide

This guide describes the current source version. Older downloadable releases may not include the latest maps, artwork or local AI. Start with the installation instructions in [README](../README.md).

## 1. Open the application

**Windows release:** extract the entire ZIP and run `GT7 Race Engineer.exe`. Choose desktop or browser. Keep the `_internal` directory alongside the EXE. **Windows source:** run `Open desktop app.vbs` or `Open in browser.vbs` after creating `.venv` and installing dependencies. Both source launchers use the same settings and recordings.

**Linux package:** open GT7 Race Engineer from the applications menu. Do not run it with sudo. Browser mode uses `http://127.0.0.1:8000` on the same computer. Keep its controller/server running while driving. Closing a launcher that owns the backend stops recording; a launcher attached to an existing receiver leaves that receiver running.

The local browser pairs automatically. Remote browsers require the token in the data folder and an explicitly configured allowed origin. Do not publish that token or expose the receiver to the public internet.

## 2. Connect your PS5

Find the current PS5 IP in the console's network status. Enter it in **Settings → Console & connection**. The local bind address belongs to the computer, not the console: normally leave it `0.0.0.0`. Default ports are receive **UDP 33740**, heartbeat **UDP 33739**, and local dashboard **TCP 8000**.

Save settings and click **Use PS5** if necessary. Drive on a circuit. The connection panel reports whether the receiver is unconfigured, binding, waiting, rejecting packets or receiving data. A menu can legitimately stop telemetry. Allow the app through the computer's firewall on your private LAN. Close competing telemetry applications if they own the same receive port.

Run **Settings → Test telemetry - 15 seconds** while driving. It observes the existing connection without stopping recording. Review packet rate, sequence gaps, parsing/storage errors and fields seen. Constant fields still count as received; unavailable packet fields are not errors. The heartbeat is a keepalive, not a sampling-rate control. Start at the default 1 second.

## 3. Choose the circuit and build a map

In **Live Race → Circuit & driving line**, choose a venue, then its exact layout. Reverse layouts are separate entries. Selection is saved immediately and updates the track profile. The library currently includes 41 venues and 122 layouts. Some newer venues use an original text badge where source logo artwork was missing.

GT7 positions do not carry a reliable track name. The app therefore asks you to select the circuit instead of guessing from a short trace. **Change the selection whenever you change circuit/layout.** An unassigned circuit still draws a temporary map.

Drive across the start/finish line, then complete a continuous lap. The opening partial lap is discarded. A successful full lap saves a map under `data/track-maps/<layout-id>.json` for live telemetry. Pauses, loading, packet gaps and large jumps invalidate that capture; simply complete another continuous lap. Demo/replay maps stay temporary. Saved maps return when you select that layout on a later visit.

The broad gray outline is a recorded driving path. The recent line overlays green when gaining delta, red when losing, and gray without a reference. The dot is the most recent displayed position. The map is not a surveyed track boundary or recommended racing line. Its horizontal and vertical scales are equal. The live driver trace resets when leaving a circuit; named saved maps remain available.

**Export map** downloads JSON. **Import map JSON** accepts a map for the selected layout, replacing that saved map. The file must contain the matching `layout_id` and 20–4096 finite `[x, z]` points in GT7 world-space metres. Export a backup before replacing one. Arbitrary SVG/PNG maps do not contain the coordinate calibration needed to overlay your car, so they are not accepted as driving maps.

The current-car panel uses the received car ID to select a local transparent catalogue thumbnail. It cannot reproduce your custom paint/livery. A generic illustration appears when artwork is missing, clearly labelled as such. A stale signal marks the panel as last received.

## 4. Read the dashboard

Throttle is green, brake red, clutch baby blue, personal-best timing green, ordinary timing yellow, and the overall-fastest legend purple. Overall race fastest data may be unavailable. **Race flags N/A** means race-control flags are not transmitted; ON TRACK/PAUSED/LOADING are player statuses.

Tyre readings are surface temperatures. They do not prove wear, pressure or available grip. Stale values are visibly marked. Minimal display hides the larger visual panels. Use fullscreen for a dedicated race screen.

## 5. Talk to the engineer

Install/select the small English Vosk model if using a source checkout. Choose microphone and output devices in Settings, or leave them at **System default**. First use **Enable and test speaker**; check the named output device and hardware volume if nothing is audible. Windows speech is generated locally; Linux normally uses eSpeak NG. Piper requires a separately installed model.

Hands-free listening starts automatically when configured. Speak clearly and pause at the end. Try “radio check,” “fuel status,” or use an exact phrase from the **Engineer request library**. The library contains 100 requests and three rotating response forms per request. An optional “Engineer” prefix is accepted. Recognition briefly pauses while the engineer speaks to reduce feedback. A headset helps in a noisy room.

Use **Pause listening** for manual push-to-talk, **Stop talking** to interrupt speech, or **Mute** for silence. **Resume engineer** enables speech again. Microphone/noise tests are in Settings. No raw microphone recording is retained. Display of the last transcript is optional and held in memory.

## 6. Fuel strategy and pit intent

Set fuel reserve and planned race length in **Strategy**. Estimates need suitable completed laps and can change with driving style. Review the displayed assumptions, fuel requirement and margin. Select **Box this lap** to mark intent; select **Unmark pit intent**, or say “stay out” / “cancel pit stop,” to cancel it. This changes the engineer's reminders, not the game's pit menu.

## 7. Analysis, AI and sessions

**Telemetry** shows live acceleration, coasting/overlap, temperature spread and braking episodes. Its charts also explore recordings. **Analysis** summarizes laps, pace, fuel and observations, with reference comparisons where compatible data exists. Delta matching needs clean complete laps and has an approximately five-minute reference limit.

**Engineer → Local AI briefing** displays a calculated summary. Optionally install the small local model using [LOCAL_AI.md](LOCAL_AI.md), select the GGUF and llama-server paths, then enable it in Settings. The model ranks supported observations; it cannot invent telemetry values. It runs on two CPU threads, normally every 45 seconds, and falls back under resource pressure. Orange Pi timing and thermal performance remain unverified.

Recordings begin with active telemetry. **End session** records your explicit completion and opens the report. Lost telemetry produces an interrupted session rather than a claimed race finish. **Sessions** lets you review, replay, protect and export data. Replay has pause, speed and seek controls and is labelled separately from live telemetry. Export bundles include machine-readable data and a report. Inspect imported data as recorded evidence, not current PS5 state.

## 8. Troubleshooting and backups

| Symptom | Check |
| --- | --- |
| No packets | Correct PS5 IP, active driving, private-LAN firewall, same reachable network, receiver port ownership. Use Reconnect telemetry and the diagnostics panel. |
| App will not start | Extract the complete release, or install source dependencies into `.venv`. Use the provided launcher instead of an unrelated Python file association. Check desktop/runtime logs. |
| Desktop renderer fails | Install Edge WebView2 on Windows, or use browser mode. Linux desktop needs its GTK/WebKit dependencies. |
| Engineer is silent | Enable/test speaker, clear mute, verify output device and volume. Check playback errors separately from microphone status. |
| Voice is not recognized | Verify Vosk path, microphone permission/device and noise level; try an exact request with a short pause. |
| Map never completes | Finish a full lap after the initial partial lap without pausing, loading, large position jumps or telemetry gaps. Check the selected layout. |
| Wrong map | Select the correct circuit/layout. Imported maps must use that layout's GT7 world coordinates. |
| Missing car picture | That car ID has no bundled thumbnail; the labelled fallback is intentional. |
| SBC runs hot/slow | Reduce UI refresh to 6 Hz, enable minimal display, disable optional local AI, and check cooling/storage. Keep full-rate recording on a local disk. |

Stop the application before copying its complete data folder for backup. Source defaults to `data/`; Windows release defaults to `%LOCALAPPDATA%\GT7 Race Engineer`; Linux release defaults to `~/.local/share/gt7-race-engineer`. Keep the pairing token private. Use unsynced local storage for active recordings rather than OneDrive/network shares.

When reporting a bug on GitHub, include your OS/architecture, version/commit, packet variant, reproduction steps and redacted errors. See [capabilities](../DATA_FIELDS.md), [protocol](../PROTOCOL.md), and [implementation history](../IMPLEMENTATION_STATUS.md) for technical details.
