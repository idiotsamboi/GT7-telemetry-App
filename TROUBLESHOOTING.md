# Troubleshooting

| Symptom | Check |
|---|---|
| No telemetry | Start driving; check console IP, same LAN, firewall, UDP ports, competing receiver. Menus can be silent. Run connection-test with main app stopped. |
| Bind failed / address in use | Close another telemetry app or duplicate process. Local UDP bind is your local interface, never the PS5 IP. |
| Invalid magic / parse failures | Verify variant/layout, capture encrypted datagrams only if opted in, record game build and compare to pinned source. |
| Stale but values visible | Grey values are the last sample, not current facts. Header shows waiting/stale. Disconnection becomes interrupted, not completed. |
| Live UI does not connect | Install the complete lockfile including wsproto. Check exact allowed origin, pairing cookie and one-worker startup. |
| Pairing denied | LAN needs the token stored on the Orange Pi and an exact allowed origin. Never put token in a URL. |
| Another GT7 instance owns lock | Only one worker is permitted. HTTP port+1 is the loopback ownership lock. Change HTTP port or stop the other process. |
| Fuel estimate unavailable | Need three clean, complete positive-consumption laps. Refuel, gaps, partial opening laps, zero capacity and unknown race distance limit predictions. |
| No current C time | Explicitly select C and enable validated C interpretation only after checking it against the game. A has no current-lap-time field. |
| Microphone unavailable | Install optional requirements and native PortAudio, choose the extracted Vosk model directory, inspect devices/rate and restart the worker. |
| No speech | Enable spoken output; install eSpeak NG; verify selected output and desktop audio session. Hard mute includes critical messages. |
| Piper error | Verify current Piper executable and model file; switch manually to eSpeak. Model licenses are separate. |
| Recording error/drops | Check free space, writable local storage and queue age. Logs with nonzero losses are not lossless. Live engineer can continue. |
| Replay ended immediately | Seek cursor must lie within recorded monotonic times; Restart replay resets it. Imported/malformed data is rejected. |
| Comparison denied | Both laps must be complete/comparable and have matching car, named track, named layout, direction and provenance. Setup/weather can still confound them. |
| Node build fails on Windows | Use a normal native Node/npm installation. This environment needed matching native Rollup/esbuild optional packages. Production uses compiled dist without Node. |

## Safe backup

Stop the application and copy the whole local data directory, or use SQLite's online backup API:

```bash
.venv/bin/python scripts/backup.py --database data/telemetry.sqlite3 --output data/backups/session-backup.sqlite3
```

Do not copy only the main `.sqlite3` file while a WAL writer is active. Bundle export covers one ended session. Imported bundles are capped at 32 MiB compressed, 128 MiB expanded and 100,000 samples; large endurance import/streaming is not supported yet.

To recover after a crash, restart normally. Open Sessions and inspect the interrupted record. Its report may reflect the most recent lap-boundary checkpoint; full committed samples remain available in telemetry export. Never delete an existing database to resolve a schema/config error. Preserve it and inspect diagnostics.

Settings are atomically replaced after validation. HTTP listen/origin changes require restart; console/UDP changes reconnect immediately; ordinary thresholds and verbosity apply immediately. Reset by stopping the app, backing up `settings.json`, and replacing it with `config.example.json`; do not remove recordings or the pairing token unless deliberately rotating it.
