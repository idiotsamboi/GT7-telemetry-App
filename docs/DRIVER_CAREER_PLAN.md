# Driver Career implementation contract

## Architecture and integration map

Extend the existing SQLite database and writer, existing discrete lifecycle events, authenticated local API, feature registry, typed HTTP adapters and Driver shell. No second sample bus, socket, track identity system or cloud dependency.

New domain: `backend/app/gamification/`. Storage owns a small isolated transaction dispatch on its existing writer; domain repositories implement SQL and bounded queries. CPU work runs outside the receiver. The event callback only captures bounded context and queues work. Persist session-to-driver attribution at session start; switching profiles must not reattribute previous sessions. Failed processing remains retryable and idempotent.

| Existing integration | New component | Risk | Validation |
|---|---|---|---|
| storage/schema.py + migrations | career tables and indexes, version 4 | upgrade compatibility | old/fresh schema equivalence, reopen |
| Store writer | isolated career transaction job | rollback must not discard samples | forced failure with neighboring sample jobs |
| Sessions lifecycle / TelemetryBus.subscribe_events | background career processor | end event precedes commit; shutdown/retry | flush outside receiver; runtime lifecycle tests |
| TrackService authoritative resolution | lap-local immutable identity evidence | unlock/change mid-lap | ambiguous identity exclusion tests |
| training_defs evaluators | persistent challenge instances | definition is not completion | validated source and requirement tests |
| API middleware | /api/gamification router | local mutations and import validation | API pairing/validation tests |
| Driver shell/router | CareerDashboard and typed adapter | shell regression | typecheck, architecture, responsive browser check |

## Data model map

DriverProfile (multiple local identities, active selection, cached aggregates) -> SkillProfile (nullable score until evidence, confidence, independent XP), XPEvent (unique deterministic guard, source event, versioned evidence), Achievement (unique definition per driver).

Session attribution -> immutable source/evidence events -> atomic rewards and derived aggregates. Later: TrackMastery -> CornerMastery; ChallengeDefinition -> ChallengeInstance; EngineerProfile -> Mission; Season -> SeasonProgress. Every derived update references evidence; unknown stays null. Imported career bundles are attributed as imported and never replayed for rewards.

## API and UI map

Prefix `/api/gamification`: profile(s), skills, xp/history, achievements, dashboard, settings, diagnostics; later tracks, corners, challenges (accept/skip), streaks, career, missions, engineer and seasons. Export/import/reset require validation; destructive reset requires an explicit confirmation string and touches career tables only.

Primary route `#/driver/career`; overview, skills, tracks, corners, challenges, achievements, training, engineer, seasons and history subviews. Dashboard answers next activity, reason, evidence and reward. Missing features and unsupported metrics are visibly unavailable, never scored zero. Existing design tokens and reduced-motion behavior apply. REST refresh is low frequency; do not bloat the high-frequency live snapshot.

## Event map

Existing session_started -> persist driver attribution. lap_completed -> capture provenance and authoritative layout context, no raw samples. session_ended -> wait for recording commit off receive loop -> evaluate finalized stored laps -> record eligible/excluded evidence -> XP -> skills -> achievements -> scorecard, all idempotent. Track/corner/challenge/mission events extend this chain only when their evidence is validated. Replay/demo/import are analysis-only by default; no live achievements. Manual metadata corrections never create reward events.

## Dependency graph and migration plan

Repository map -> architecture -> migration/repository -> evidence/XP/levels/skills -> session worker -> API -> dashboard -> runtime verification.

Then F011–F030 track/corner mastery -> F031–F050 challenges -> F051–F070 scorecards/streaks -> F071–F090 engineer/career/training -> F091–F100 group/polish. P0 precedes P1/P2; registries never substitute for implementation.

Migration 004 must be additive and mirrored in inline DDL. Preserve all telemetry, profiles and group tables. Use driver/time/session/layout/status/category indexes. Do not open or migrate the user's production database merely to test; use temporary fixtures. Version algorithms and evidence; no silent historical rescoring.

## Delegation and context budget

- Narrow discovery agent: read-only architecture memo, target 4k tokens, <=8 source files.
- Foundation agent: database, domain repository and pure scoring tests, target 8–12k; exclusive ownership of gamification backend and migration files.
- Frontend agent after contract is stable: typed adapter/dashboard/navigation, target 5–8k; exclusive frontend ownership.
- Coordinator: runtime/API integration, failure/provenance tests, checkpoint and diff review.
- Subsequent focused tasks: track/mastery, challenge, engineer/training, group eligibility and UX; 4–12k each with serial handoffs where dependent.

Counts are estimates unless the runtime exposes actual accounting. Each implementation unit needs happy path, edge case, provenance and failure/recovery tests. Finish and checkpoint a coherent unit before expanding. Never claim beta readiness from unit tests alone.

## Current checkpoint

Implemented: discovery and implementation maps only. Foundation implementation next. All F001–F100 are PLANNED, not complete. Existing working changes remain untouched. Highest risks: synchronous writer cost, durable recovery, per-lap track identity, replay laundering, historical PB compatibility and profile switching.
