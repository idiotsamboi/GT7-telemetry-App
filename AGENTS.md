# AGENTS.md - GT7 RACE ENGINEER AGENT SPECIFICATION

## PERMANENT HIGH-LEVEL INVARIANTS

### 1. PROJECT IDENTITY
GT7 Race Engineer is a local-first Gran Turismo 7 telemetry, driver-coaching, training, race-management, and driver-progression application.
Its primary objective is: TURN DRIVING DATA INTO A LONG-TERM DRIVER DEVELOPMENT EXPERIENCE.

### 2. SOURCE-CODE-FIRST RULE
Always ground implementations in direct inspection of authoritative source files. Never assume APIs, database schemas, or symbol names.

### 3. TELEMETRY TRUTH RULES
- **Never invent telemetry**: If GT7 telemetry does not provide a packet attribute (e.g. tyre wear, compound, pressure, official penalties, official flags), do not fabricate or infer it as official data.
- **Preserve provenance**: Tag all data as `REPORTED`, `CALCULATED`, `EXPERIMENTAL`, `USER_AUTHORED`, `SHARED_DRIVER`, `UNAVAILABLE`, `SYNTHETIC`, or `REPLAY`.
- **Never present calculated data as official game data**: Always explicitly label calculated metrics (e.g., "Application Clean Lap", "Calculated Racecraft Score").

### 4. ARCHITECTURAL PRINCIPLES
- Local-first architecture: Works completely offline without cloud dependencies.
- Subsystem separation: Raw Telemetry -> Calculated Observations -> Progression / Gamification.
- Robust state persistence & idempotency: Processing events multiple times must never duplicate XP, achievements, or progression.
- Failure isolation: Gamification failures are non-fatal to telemetry recording.

### 5. TESTING & VERIFICATION EXPECTATIONS
- No feature is declared "IMPLEMENTED" until verified by unit/integration tests and runtime checks.
- Test suites must cover XP calculations, levels, skills, confidence, mastery, challenges, streaks, anti-farming, and schema migrations.

### 6. CONTEXT-EFFICIENCY & FEATURE-ID SYSTEM
- All 100 gamification features use stable IDs: F001 through F100.
- Reference features by ID rather than repeating long text specifications.
- Use targeted symbol searches and inspect `.agent-state/current-state.md` for handoffs.

### 7. STATE DOCUMENT LOCATIONS
- Current State: `.agent-state/current-state.md`
- Feature Matrix: `.agent-state/feature-matrix.md`
- Dependency Map: `.agent-state/dependency-map.md`
- Active Work: `.agent-state/active-work.md`
