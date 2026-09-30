# 0002. In-process TelemetryBus with delivery modes; no broker

Status: accepted

## Context
`Runtime.consume()` called each consumer explicitly. One consumer raising skipped every later consumer
and, for demo/replay, killed `source_loop`. Adding a consumer meant editing `consume()`.

## Decision
A synchronous, in-process `TelemetryBus` (`telemetry/bus.py`). Subscribers choose `every` (inline),
`rate` (decimated by frame time) or `latest` (a slot the consumer pulls). A handler exception is caught,
counted per subscriber, logged at most once per 60 s, and reported to the runtime, which counts it as a
pipeline error and flags the session quality — it never reaches ingestion or other subscribers.
Discrete events (`lap_completed`, `session_started/ended`, `source_changed`, `connection_changed`,
`track_locked/unlocked`, `pit_detected`) use `bus.emit`.

The runtime subscribes its consumers in **the original call order** (see TECH_DEBT #14 for why the
recorder is not yet "critical-first"). No message broker, no threads: one publish costs a tuple walk.

## Consequences
- Adding a consumer is one `bus.subscribe(...)` line in the composition root.
- Backpressure is unchanged: the recorder keeps its bounded queue with loss accounting; UI is latest-wins;
  group publish keeps the newest frame. `tests/test_architecture.py` asserts every queue/deque is bounded.
- Handler budget: `every` handlers must stay cheap (≤ 50 µs); heavy consumers use `rate`.
