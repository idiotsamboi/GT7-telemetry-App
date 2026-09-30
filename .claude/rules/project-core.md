# project-core
- Source code wins over docs. Search symbols first, read line ranges only.
- Telemetry reception/recording has priority; gamification errors are logged, never raised into the runtime.
- Never invent telemetry; tag provenance (REPORTED/CALCULATED/EXPERIMENTAL/USER_AUTHORED/SHARED_DRIVER/UNAVAILABLE/SYNTHETIC/REPLAY). Calculated is never 'official GT7'.
- Reuse existing systems (track identity, store, WebSocket, shell). No parallel systems, no second WebSocket.
- Hotspots: prefer new focused modules over growing runtime.py, api.py, storage/store.py, group/service.py, main.tsx.
