# Engineer rules and arbitration

Implemented sustained-condition rules are defined in `backend/app/engineer.py::RULES`, exposed through `/api/capabilities`, and individually exercised with positive, negative, noisy and stale-evidence tests.

| Rule | Priority | Persistence | Gate |
|---|---|---:|---|
| Low fuel | P1 | 3 s | Positive capacity; configured L threshold; +0.5 L exit hysteresis |
| Critical fuel | P0 | 2 s | Below 0.5 L while moving; exit above 0.8 L |
| High tyre surface | P2 | 8 s | Explicit user temperature threshold; -3°C exit |
| Left/right temperature imbalance | P2 | 10 s | Four finite values; configured difference; -3°C exit |
| Limiter exposure | P3 | 3 s | Rev-limit flag, on-track, unpaused |
| Handbrake | P1 | 3 s | Flag active above 30 km/h; exit below 20 |
| Off surface | P2 | 1.5 s | C interpretation enabled; at least two D/G/S/s codes |
| Pedal overlap | P3 | 4 s | Both >20%, speed >36 km/h; exit either <10% |
| Pit speed | P1 | 1 s | Configured region and limit; entry +2 km/h |

All use a configurable global cooldown (default 60 seconds). Pause/off-track clears persistence. Per-rule threshold/settings coverage is incomplete: persistence values and some thresholds remain source-defined. Wheel ratios are displayed, not claimed as definitive slip/lockup diagnosis. Oil/water constants never warn. No unsupported opponent, penalty, yellow flag, wear or pressure calls exist.

Additional events: connection/restoration/stale/interrupted, completed lap timing, learned fuel deficit, box intent reminders, storage failure and low disk. Errors also remain visible in diagnostics. Driver improvement cards require repeated measured coasting, overlap or limiter exposure, and do not claim causality or a fabricated time benefit.

Priority order: P0 urgent, P1 important/requested, P2 information, P3 coaching. Candidate IDs, category, timestamp, lifetime, session, priority, evidence and confidence persist with decisions. Entry/exit/persistence descriptions accompany rule evidence. Normal unsolicited minimum gap 8 s, at most 4 messages/minute, estimated 20 s speech/minute. P0 has its own 15-second repeat gate; rules retain cooldown. Related same-category events supersede queued older evidence. Queue: 16 ordinary plus four reserved urgent slots. Requested answers bypass normal quotas but not the queue bound or hard mute.

Hard mute covers P0. Quiet for two minutes preserves P0; Quiet mode drops routine P2/P3, Critical-only drops everything unsolicited except P0. Coaching mode allows P3. Braking/yaw defers optional messages; expired advice is dropped. Stop is immediate playback cancellation plus pending-queue cancellation. PTT cancels playback and pauses engineer output while listening. Active session changes invalidate queued session events. Logs distinguish selection, subtitles, output start, successful completion, expiry, merging, suppression and mute. Estimated speech budgeting is not measured audio duration.

Not implemented: broad cross-category phrase merging, pre-synthesized phrase cache, automatic fallback after Piper failure, all requested advanced alert families, and per-corner/segment cooldown scopes. See IMPLEMENTATION_STATUS.
