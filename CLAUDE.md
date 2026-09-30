# GT7 Race Engineer - Claude Code guide
Local-first GT7 telemetry, coaching, training, race-control and driver-career app. Goal: turn driving data into long-term driver development.
Full invariants: @AGENTS.md is the source; this file is the short operating copy.

## Invariants
- Source code wins over docs. Symbol search first; read line ranges only.
- Never invent telemetry (no tyre wear/compound/official pressure/penalties/flags/official validity). Provenance: REPORTED, CALCULATED, EXPERIMENTAL, USER_AUTHORED, SHARED_DRIVER, UNAVAILABLE, SYNTHETIC, REPLAY. Calculated is never "official GT7".
- Raw telemetry -> calculated observations -> progression. Progression never touches raw samples.
- Telemetry reception/recording has priority. Gamification errors are logged + retried, never raised into the runtime. No DB scan per packet.
- XP/achievements/mastery/streaks idempotent (deterministic event IDs), auditable, live-only by default (replay/demo/synthetic isolated). All behind feature flags + settings. No core feature gated by progression.
- Reuse the existing store/WebSocket/shell/track identity. No second WebSocket, no parallel track system.

## Commands (Windows; run from repo root)
- Backend tests: `.venv/Scripts/python.exe -m pytest <path> -q -x 2>&1 | tail -25` (pyproject sets --basetemp=.pytest_tmp)
- Gamification subset: `... -m pytest tests/test_gamification*.py -q`
- Frontend: `npm --prefix frontend run build` (tsc+vite), `npm --prefix frontend run check:arch`
- Contracts: `.venv/Scripts/python.exe scripts/gen-contracts.py` (freshness test: tests/test_contracts_fresh.py)
- Ingest bench: `.venv/Scripts/python.exe scripts/bench_ingest.py` (baseline docs/architecture/bench_baseline.json)
- Full suite only at phase gates (~5 min).

## Architecture map
backend/app: core/ (errors, commands, permissions, features, registry; imports nothing from app), telemetry/ (parser, bus, frame, derived), storage/ (store, repositories, migrations in backend/migrations), gamification/ (repository, processor, scoring, mastery, challenges, career, bundles, api), runtime.py (composition root - hotspot), commands_catalog.py, modules.py, api.py (hotspot).
Docs: docs/architecture/*.md, docs/adr, docs/decisions (new decisions), docs/plans/phase-N.md.

## Feature IDs
F001-F100. Specs: docs/gamification/features/Fxxx.md. Digest of the master spec: .agent-state/spec-digest.md. Never re-read MASTER_SPEC.md.
State: .agent-state/{current-state,feature-matrix,dependency-map,active-work}.md. Update after every feature.
Statuses: PLANNED -> IN_PROGRESS -> IMPLEMENTED (runtime can exercise it) -> TESTED -> VERIFIED (runtime path tested).

## Workflow
One commit per feature ("F0xx: name") on branch gamification-career. Delegate via .claude/agents (architect, backend, frontend, qa, reviewer); subagents return <=150 words. Phase gate: reviewer -> fixes -> subsystem+typecheck+arch -> state files -> commit.
Hotspots (hook-guarded): telemetry/parser.py, telemetry/bus.py, storage/store.py (blocked without GT7_ALLOW_HOTSPOT=1); runtime.py, api.py, group/service.py, main.tsx (minimal edits, new modules).

@.agent-state/current-state.md
