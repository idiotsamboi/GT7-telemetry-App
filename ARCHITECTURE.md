# Architecture

## Owners and schedules

`telemetry.py` parses explicit little-endian wire offsets into a slotted Sample. `runtime.py` owns exactly one UDP socket on its asyncio loop. Unique samples go synchronously through cheap rule/session metrics, then into the bounded writer queue. Slow clients never influence sample ingestion.

- Receive / record / cheap rule evaluation: each valid unique packet, nominal 60 Hz.
- UI latest-state publish: configured 12 Hz, reduced to 4 Hz under sustained pressure.
- Browser history / player trace: 10 Hz, 600 points each; recorded history remains on disk.
- Speech arbitration / microphone result polling: 20 Hz.
- Health: 1 Hz.
- Lap aggregates: incrementally during reception; finalization at lap change/end.
- Exports / database reads / comparison: thread-pool work, bounded requests. CPU-heavy comparison is bounded to 2,400 spatial points but currently uses a thread, not a process; avoid doing this while driving on the board until benchmarked.

`storage.py` has one owning writer thread. All reads use short-lived independent connections; database writes are never performed by request handlers directly. SQLite uses WAL, synchronous NORMAL, 1,000-page auto-checkpoint, 240-job or 200-ms batches. Schema v1 migration is idempotent. Unfinished database sessions become interrupted on restart. Existing reports may be provisional after a crash; uncommitted buffered samples cannot be recovered.

## Queue contracts

| Queue | Capacity/unit | Producer/overflow |
|---|---|---|
| Database | 8,192 jobs, normally samples | Nonblocking drop-new, counted separately; never overwrite old samples |
| Speech | 16 nonurgent + up to 4 urgent candidate slots | Category supersession, then suppress-and-log when full |
| Microphone PCM | 64 blocks, 1,600 mono int16 frames/block | Drop-new with explicit microphone error |
| Microphone control | 8 commands | Reject/count via visible control error |
| Microphone results | 64 small messages | Drop-new; level updates are expendable; recognition result loss is possible under a stalled consumer |
| WebSocket | No application frame queue | Serialize latest snapshot only; one-second send timeout disconnects slow clients |
| Live history/trace | 600 entries each | Rolling display-only overwrite; independent of recorder |
| Event display | 100 events | Rolling UI view; full submitted decisions persist to database |
| Lap aggregates | 2,000 laps | Bounded live list; originals persist on disk |

The writer buffer holds at most about 136.5 seconds at 60 Hz. Normal batches are at most 200 ms. Power loss can lose the buffer and recently committed OS-cached WAL contents; no lossless power-failure guarantee is made. Queue drops and failed transactions have distinct counters. A write failure does not kill live telemetry, and later transactions can recover.

## Session state

Implemented states: disconnected, connected/idle, driving, paused, suspected pit activity (configured region only), completed by user End Session, and interrupted. Demo and replay are separate provenance, not live facts. Replay/unknown *game* provenance cannot reliably be inferred from the base flags.

Opening lap is partial. Each lap has a UUID so repeated lap numbers do not overwrite data. Car or lap counter reset ends an interrupted epoch and starts another. A source-ID reset also opens a new epoch. Missing packets and long receive gaps mark application quality. Official lap validity remains unknown. Pause frames do not advance estimated active time.

UDP silence makes data stale; after the configured 30 seconds it produces an interrupted report, never a confirmed finish. Manual End Session suppresses automatic restart until Start Session/source change. No official finish detector is implemented. Track changes require a user profile/session boundary, not a guessed car-ID mapping.

## Truth and analysis

Timing prefers completed game `last_ms`; active receive-time duration is labeled estimated otherwise. Optional C current timing is opt-in. Fuel uses median of the last seven clean positive burns, requiring at least three; refuel/partial/gapped laps are excluded. Distance-to-finish includes an approximate timing fraction and configured reserve. A user fuel multiplier is not applied.

Spatial comparison requires matching named track/layout, direction, car and provenance plus application-comparable laps. Forward-window segment projection includes vertical position, rejecting missing coverage/divergence. It is not universally validated on bridges/pit lanes; uncertain comparisons fail instead of claiming a precise delta. Original samples remain unchanged.

## Security

Loopback by default. Strict origins/hosts and token pairing protect APIs and WebSockets; cookies are HttpOnly/SameSite Strict. No evaluation of settings as code. Speech uses argument arrays/stdin, never shell commands. Exports use generated IDs, escaped HTML and safe CSV cells. Imports accept a fixed member set, sizes/checksums and a schema, never pickle, and do not extract arbitrary paths. LAN pairing is not encryption; see installation documentation.
