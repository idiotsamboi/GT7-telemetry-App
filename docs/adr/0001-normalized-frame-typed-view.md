# 0001. The normalized frame is a typed view over `Sample.values`

Status: accepted

## Context
`telemetry.parse()` already produces `Sample.values`, a flat dict keyed by field name plus normalized keys
(`gear`, `throttle`, `speed_kmh`, ...). Features read it directly. A parallel "frame" object that copies
these values would add an allocation per packet on a 60 Hz path that already costs ~0.35 ms.

## Decision
`TelemetryFrame` is a two-slot wrapper (`sample`, `meta`) around the existing `Sample`; `.values` returns
the same dict (no copy) and `FrameMeta` carries ingestion facts (mono, provenance, sequence gap, source).
The **channel registry** (`telemetry/frame.py`) describes every key: id (identical to the `values` key),
unit (canonical SI-ish), source (`reported | calculated | experimental | unavailable`), minimum packet
variant, accessor. Derived channels (`telemetry/derived.py`) are computed by a `DerivedEngine`, never
written back into `values`.

## Consequences
- Zero-copy; features keep using `values` while new code goes through `frame.get(channel_id)`.
- Frontend, backend and docs share one source: `GET /api/channels` and `channels.generated.ts`.
- Anything GT7 does not provide is registered as `unavailable` with a reason instead of a fake field.
- Undocumented packet-C fields are always decoded (the parser is table-driven) but registered `experimental`;
  `trust_c_fields` (feature flag `packet_c_interpretations`) gates whether the app *uses* them (session `current_ms`
  timing, the `off_surface` rule).
