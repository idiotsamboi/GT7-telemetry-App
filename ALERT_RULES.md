# Engineer rules and arbitration

Implemented sustained-condition rules are declared as `RuleSpec` rows in `backend/app/engineer.py` (registry `RULE_SPECS`; `RULES` is the derived legacy-shape dict `{id: {priority, persist, prerequisite, entry, exit}}`), exposed through `/api/capabilities`, and individually exercised with positive, negative, noisy and stale-evidence tests (`tests/test_reliability.py::test_each_rule`, `tests/test_engineer_rules.py`).

**Where to edit.** A rule is one `RuleSpec(id, priority, persist_s, prerequisite, entry_text, exit_text, entry, exit, message)` in the `for _r in (...)` block of `engineer.py`. `entry_text`, `exit_text` and `prerequisite` are the documented conditions and feed the table below (and the generated `docs/architecture/CONTRACTS.md`); `entry`, `exit` and `message` are the executable form, functions of a `RuleContext` (`v`, `cfg`, `fuel`, `valid_fuel`, `temp`, `imbalance`, `speed` in km/h, `inside`). Keep the text and the code in step, add the id to the `engineer` module in `backend/app/modules.py`, and add a case to `tests/test_engineer_rules.py`. `RuleSpec`s without callables (`tyre_heat_rate`) are evaluated by their own method. The step-by-step recipe is `docs/architecture/EXTENDING_THE_APP.md` ("New alert rule").

**Alert centre.** A rule that fires becomes an engineer decision (`Runtime.decision`). Unrequested `selected`/`subtitle` decisions are also raised as visible, acknowledgeable alerts by `Runtime._raise_alert` into the `AlertCenter` (`backend/app/domain/alerts.py`): source `telemetry` for a rule category, else `engineer`, `network` or `storage`; severity `critical`, `warning`, `notice`, `info` for priority 0 to 3; `notice` and `info` expire after 600 s; alerts with the same category are refreshed rather than duplicated. They are listed by `GET /api/alerts` and acknowledged with the `alerts.acknowledge` command. The Scheduler below stays the speech arbiter; an alert is only what the UI lists. (`RuleDef`/`RULE_DEFS` in `domain/alerts.py` is an unused parallel data shape; `RuleSpec` is the source of truth.)

| Rule | Priority | Persistence | Gate |
|---|---|---:|---|
| Low fuel | P1 | 3 s | Positive capacity; configured L threshold; +0.5 L exit hysteresis |
| Critical fuel | P0 | 2 s | Below 0.5 L while moving (above 5 km/h); exit above 0.8 L or at 5 km/h or below |
| High tyre surface | P2 | 8 s | Explicit user temperature threshold; -3°C exit |
| Left/right temperature imbalance | P2 | 10 s | Four finite values; configured difference; -3°C exit |
| Limiter exposure | P3 | 3 s | Rev-limit flag, on-track, unpaused |
| Handbrake | P1 | 3 s | Flag active above 30 km/h; exit below 20 |
| Off surface | P2 | 1.5 s | C interpretation enabled; at least two D/G/S/s codes |
| Pedal overlap | P3 | 4 s | Both >20%, speed >36 km/h; exit either <10% or speed <30 km/h |
| Pit speed | P1 | 1 s | Configured region and limit; entry +2 km/h |
| Tyre heat rate | P2 | 8 s | Per tyre: heating rate >= 0.15 degC/s and anomaly >= +4 degC over the track-position baseline, both sustained; exit rate < 0.05 degC/s or anomaly < +2 degC. Needs all four anomalies, two warm-up laps since session start, and no pit-out lap; v3 track lock preferred, time baseline otherwise |

All rules except tyre heat rate use a configurable global cooldown (`Settings.alert_cooldown`, default 60 seconds); tyre heat rate has its own cooldowns (120 s per tyre, 60 s across tyres) and merges front or rear pairs into one message. Its thresholds are code constants in `engineer.py` (`Settings.tyre_heat_rate_c_s` and `tyre_heat_anomaly_c` exist but are not read). Pause/off-track clears persistence. Per-rule threshold/settings coverage is incomplete: persistence values and some thresholds remain source-defined. Wheel ratios are displayed, not claimed as definitive slip/lockup diagnosis. Oil/water constants never warn. No unsupported opponent, penalty, yellow flag, wear or pressure calls exist.

Additional events: connection/restoration/stale/interrupted, completed lap timing, learned fuel deficit, box intent reminders, storage failure and low disk. Errors also remain visible in diagnostics. Driver improvement cards require repeated measured coasting, overlap or limiter exposure, and do not claim causality or a fabricated time benefit.

Priority order: P0 urgent, P1 important/requested, P2 information, P3 coaching. Candidate IDs, category, timestamp, lifetime, session, priority, evidence and confidence persist with decisions. Entry/exit/persistence descriptions accompany rule evidence. Normal unsolicited minimum gap 8 s, at most 4 messages/minute, estimated 20 s speech/minute. P0 has its own 15-second repeat gate; rules retain cooldown. Related same-category events supersede queued older evidence. Queue: 16 ordinary plus four reserved urgent slots. Requested answers bypass normal quotas but not the queue bound or hard mute.

Hard mute covers P0. Quiet for two minutes preserves P0; Quiet mode drops routine P2/P3, Critical-only drops everything unsolicited except P0. Coaching mode allows P3. Braking/yaw defers optional messages; expired advice is dropped. Stop is immediate playback cancellation plus pending-queue cancellation. PTT cancels playback and pauses engineer output while listening. Active session changes invalidate queued session events. Logs distinguish selection, subtitles, output start, successful completion, expiry, merging, suppression and mute. Estimated speech budgeting is not measured audio duration.

Not implemented: broad cross-category phrase merging, pre-synthesized phrase cache, automatic fallback after Piper failure, all requested advanced alert families, and per-corner/segment cooldown scopes. See IMPLEMENTATION_STATUS.
