# CURRENT STATE
Branch: gamification-career (baseline commit edabce1). Spec digest: .agent-state/spec-digest.md
## PHASE
Phase 0 done (infra: CLAUDE.md, .claude/{rules,skills,agents,hooks,settings.json}). Next: Phase 1 plan -> docs/plans/phase-1.md.
## REAL STATE (Phase 0 discovery)
- Wiring: runtime.py bus -> career.on_event (session_started/lap_completed/session_ended/spatial_analysis_completed/track_locked). processor.py bounded queue(128), off-thread career_transaction, recovery every 30s. Flags enforced in processor.
- Real output is consistency-only (1 of 10 skills). Scorecard/grade consistency-only. Streaks: 1 kind. Titles/badges/chapters hardcoded thresholds. Mastery training/strategy components None.
- ABSENT: notifications F097, seasons F090, medals F083, racecraft, PB event hook, live-lap career feed, dedicated anti-farming module.
- Frontend: CareerDashboard.tsx + domain/api/gamification.ts; poll-based, no live store.
- Matrix VERIFIED claims were unsupported -> downgraded to IMPLEMENTED.
## FIXED
- Added GET /api/gamification/xp/history (test_gamification_api now passes). That test takes ~90s (slow; investigate TestClient teardown).
## REUSE
training_defs.py evaluators, track_service, spatial_coaching, engineer_service.career_brief, group/battles+steward, voice.Speaker (numeric priority only).
## RISKS
Queue overflow invalidates session rewards; flags default True; perf unproven; PS5 live unverified.
## DO-NOT-TOUCH
telemetry/parser.py, telemetry/bus.py, storage/store.py (hook-blocked); runtime.py/api.py minimal edits.
## PHASE 1 DONE (events.py, notifications.py, antifarm.py, migration 008, /notifications API; 38+17 tests pass)
## NEXT
Write docs/plans/phase-1.md; fix slow test; then F005/F006/F009 (titles/badges/recent gains), F016/F017 real components.
