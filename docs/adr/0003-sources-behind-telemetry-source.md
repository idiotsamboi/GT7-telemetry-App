# 0003. Live, demo and replay behind `TelemetrySource`

Status: accepted (interface + scenarios done; loop extraction staged)

## Context
`source_loop` switches inline on `self.source` between live UDP, the synthetic demo generator and SQLite
replay. Consumers sometimes ask the receiver about state that only exists for live.

## Decision
`TelemetrySource` (`telemetry/sources.py`) is the contract: `kind` (`live | demo | replay`), `status()`
returning a `ServiceStatus`, plus optional replay controls. `provenance` is stamped by the source, never
by consumers. Invariants (already enforced and tested): replay/demo send no heartbeat and never write
live track maps, personal bests or the training corpus.

A deterministic `ScenarioDemo` (seeded) provides `normal_laps`, `lap_transition`, `fuel_burn_and_refuel`,
`braking_zones`, `packet_loss_burst`, `out_of_order`, `stream_stale_10s`, `session_end` and
`variant_switch_A_to_C`. Scenario output is always labelled synthetic.

## Consequences
- The receiver phase is exposed as the `telemetry_receiver` service; the UI reads service state, not
  `receiver` internals.
- Extracting the three code paths of `source_loop` into adapter classes is a mechanical next step (see
  TECH_DEBT #1); the interface and tests exist so it can be done without behaviour changes.
