import os
import sys

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    print(f"Bootstrapping Antigravity structure in: {root}")

    # 1. Directories to create
    dirs = [
        os.path.join(root, ".agents"),
        os.path.join(root, ".agents", "rules"),
        os.path.join(root, ".agents", "skills"),
        os.path.join(root, ".agents", "agents"),
        os.path.join(root, "docs"),
        os.path.join(root, "docs", "architecture"),
        os.path.join(root, "docs", "gamification"),
        os.path.join(root, "docs", "gamification", "features"),
        os.path.join(root, "docs", "engineering"),
        os.path.join(root, "docs", "decisions"),
        os.path.join(root, ".agent-state"),
    ]

    # Skill subdirectories
    skills = [
        "repo-discovery",
        "gamification-feature",
        "database-migration",
        "backend-feature",
        "frontend-feature",
        "telemetry-analysis",
        "track-analysis",
        "test-and-verify",
        "performance-audit",
        "release-audit"
    ]
    for sk in skills:
        dirs.append(os.path.join(root, ".agents", "skills", sk))

    # Agent subdirectories
    agents = [
        "architect", "database", "backend", "analytics",
        "track", "frontend", "qa", "performance", "reviewer"
    ]
    for ag in agents:
        dirs.append(os.path.join(root, ".agents", "agents", ag))

    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"Directory ready: {d}")

    # 2. Write AGENTS.md
    agents_md_path = os.path.join(root, "AGENTS.md")
    with open(agents_md_path, "w", encoding="utf-8") as f:
        f.write("""# AGENTS.md - GT7 RACE ENGINEER AGENT SPECIFICATION

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
""")

    # 3. Write Rules in .agents/rules/
    rules_data = {
        "project-core.md": """# Rule: Project Core Principles
- Ground all changes in verifiable requirements and direct codebase evidence.
- Maintain existing API contracts and local-first execution.
- Keep dependencies modular and decoupled.
""",
        "telemetry-truth.md": """# Rule: Telemetry Truth & Provenance
- Never invent missing GT7 telemetry data (tyres, wear, official penalties).
- Tag every data point with explicit provenance (`REPORTED`, `CALCULATED`, `EXPERIMENTAL`, `USER_AUTHORED`, `SHARED_DRIVER`, `UNAVAILABLE`, `SYNTHETIC`, `REPLAY`).
- Clearly separate application-calculated metrics from official game data.
""",
        "backend.md": """# Rule: Backend Architecture
- Fast, asynchronous Python FastAPI services.
- Keep telemetry ingestion, analysis, and gamification in decoupled services.
- Gamification processing must be async and failure-isolated.
""",
        "frontend.md": """# Rule: Frontend Architecture
- React TypeScript with Vite shell.
- Modular career components under `driver/career/`.
- Subscribe to state changes efficiently without full app re-renders.
""",
        "database.md": """# Rule: Database & Persistence
- SQLite relational persistence with explicit schemas and migrations.
- Index hot columns (driver_id, track_id, timestamp, session_id).
- Ensure idempotency keys for all XP and achievement transactions.
""",
        "gamification.md": """# Rule: Gamification Engine
- Gamification turns telemetry evidence into driver development and motivation.
- Formulae must be deterministic, auditable, and backed by confidence scoring.
- Replay and Demo modes must be strictly separated from live career rewards.
""",
        "testing.md": """# Rule: Testing & Verification
- Always execute relevant unit tests and static checks before marking tasks done.
- Include property tests for XP bounds, skill range (0-100), and idempotent event handling.
""",
        "performance.md": """# Rule: Performance & Resource Constraints
- Telemetry packet receiving loop must never block on disk or database I/O.
- Measure baseline CPU/RAM and disk latency before and after major changes.
"""
    }

    for fname, content in rules_data.items():
        with open(os.path.join(root, ".agents", "rules", fname), "w", encoding="utf-8") as f:
            f.write(content)

    # 4. Write Skills in .agents/skills/
    skill_names = [
        ("repo-discovery", "Repository Discovery & Symbol Mapping", "Instructions for efficiently locating symbols and mapping architecture without scanning entire files."),
        ("gamification-feature", "Gamification Feature Implementation", "Standard procedure for implementing F001-F100 features across backend, database, and UI."),
        ("database-migration", "Database Migration", "Instructions for adding schema tables, indexes, and idempotency constraints."),
        ("backend-feature", "Backend Feature Engineering", "Procedure for writing FastAPI endpoints, services, and domain models."),
        ("frontend-feature", "Frontend Component Engineering", "Procedure for creating React components, hooks, and views."),
        ("telemetry-analysis", "Telemetry Analysis Pipeline", "Guidelines for deriving lap stats, braking points, and sector times from raw UDP packets."),
        ("track-analysis", "Track & Corner Geometry Analysis", "Guidelines for track recognition, corner identification, and spatial coaching."),
        ("test-and-verify", "Test Execution & Runtime Verification", "Standard workflow for executing unit, integration, and property tests."),
        ("performance-audit", "Performance Auditing & Benchmarking", "Procedure for measuring latency, memory usage, and throughput."),
        ("release-audit", "Release Hardening & Audit", "Final verification checklist prior to releasing build updates.")
    ]

    for s_id, s_title, s_desc in skill_names:
        s_path = os.path.join(root, ".agents", "skills", s_id, "SKILL.md")
        with open(s_path, "w", encoding="utf-8") as f:
            f.write(f"""---
name: {s_id}
description: {s_desc}
---

# Skill: {s_title}

## Overview
{s_desc}

## Workflow
1. Inspect required target files using symbol search.
2. Formulate explicit implementation step.
3. Verify changes with focused test execution.
""")

    # 5. Write Agent Definitions in .agents/agents/
    agent_roles = [
        ("architect", "Lead Architect", "Focuses on system decomposition, API design, and cross-subsystem boundaries."),
        ("database", "Database Engineer", "Handles SQLite schemas, indexes, migrations, and idempotent queries."),
        ("backend", "Backend Engineer", "Implements FastAPI endpoints, domain services, and async events."),
        ("analytics", "Telemetry Analytics Specialist", "Calculates braking metrics, consistency scores, sector analysis, and evidence generation."),
        ("track", "Track & Corner Specialist", "Manages track recognition models, corner cataloging, and spatial telemetry mapping."),
        ("frontend", "Frontend Specialist", "Builds React UI components, career dashboards, telemetry graphs, and state management."),
        ("qa", "Quality Assurance Specialist", "Writes unit, integration, and property-based test suites."),
        ("performance", "Performance Analyst", "Measures packet loop latency, memory consumption, and DB query execution times."),
        ("reviewer", "Code & Architecture Reviewer", "Audits diffs for telemetry truth violations, provenance tagging, and performance regressions.")
    ]

    for a_id, a_title, a_desc in agent_roles:
        a_path = os.path.join(root, ".agents", "agents", a_id, "AGENT.md")
        with open(a_path, "w", encoding="utf-8") as f:
            f.write(f"""# Subagent: {a_title}

## Role
{a_desc}

## Guidelines
- Follow permanent invariants in `AGENTS.md`.
- Operate with minimal required context.
- Output clean structured summaries of work performed.
""")

    # 6. Generate 100 Feature Files in docs/gamification/features/
    features = [
        ("F001", "Driver Level", "DRIVER PROGRESSION", "Global driver progression based on total evidence-backed XP."),
        ("F002", "Driver Skill Profile", "DRIVER PROGRESSION", "0-100 radar/dashboard rating across Pace, Consistency, Braking, Cornering, Throttle, Fuel, Strategy, Track Knowledge, Racecraft, Discipline."),
        ("F003", "Skill Levels", "DRIVER PROGRESSION", "Named progression tiers for individual skills (Novice -> Master)."),
        ("F004", "Skill XP", "DRIVER PROGRESSION", "Independent XP pools and gains for each distinct driver skill category."),
        ("F005", "Driver Titles", "DRIVER PROGRESSION", "Unlockable driver titles based on achievements, level, and track mastery."),
        ("F006", "Driver Badges", "DRIVER PROGRESSION", "Visual milestone badges awarded for specific career achievements."),
        ("F007", "Driver Overview Card", "DRIVER PROGRESSION", "Compact driver profile summary card showing level, title, active focus, and top skills."),
        ("F008", "Progress Timeline", "DRIVER PROGRESSION", "Chronological audit log of driver level-ups, PBs, and major accomplishments."),
        ("F009", "Recent Gains", "DRIVER PROGRESSION", "Summary of XP and skill score changes from recent sessions."),
        ("F010", "Personal Statistics Archive", "DRIVER PROGRESSION", "Long-term driver statistics aggregate archive (total distance, laps, sessions, PBs)."),

        ("F011", "Track Mastery", "TRACK MASTERY", "0-100 layout-specific track mastery calculated from pace, consistency, corners, training, and strategy."),
        ("F012", "Track Visit Tracking", "TRACK MASTERY", "Tracks sessions, total laps, cars driven, first visit, and last visit per track layout."),
        ("F013", "Track Discovery Levels", "TRACK MASTERY", "Progression tiers: Visited -> Recognized -> Learning -> Familiar -> Strong -> Mastered."),
        ("F014", "Track PB Progression", "TRACK MASTERY", "Historical progression curve of personal best lap times per track/car combination."),
        ("F015", "Track Consistency", "TRACK MASTERY", "Long-term lap time variance and consistency measurement for a track layout."),
        ("F016", "Strategy Mastery", "TRACK MASTERY", "Track-specific fuel saving and pit strategy execution score when supported by telemetry."),
        ("F017", "Training Completion", "TRACK MASTERY", "Completion percentage and medals earned in training modules per track."),
        ("F018", "Corner Coverage", "TRACK MASTERY", "Percentage of analyzable corners on a layout with sufficient clean data samples."),
        ("F019", "Track Mastery Missions", "TRACK MASTERY", "Layout-specific objectives (e.g. Complete 10 clean laps, achieve 75% consistency)."),
        ("F020", "Track Mastery Rewards", "TRACK MASTERY", "Titles, badges, and driver profile unlocks awarded for mastering specific tracks."),

        ("F021", "Corner Identification", "CORNER MASTERY", "Stable track-local corner numbering and spatial segmentation (T1, T2, etc.)."),
        ("F022", "Corner Performance Record", "CORNER MASTERY", "Structured historical entry, apex min-speed, exit throttle, and time delta records per corner."),
        ("F023", "Corner Mastery", "CORNER MASTERY", "0-100 mastery score for individual corners based on min-speed, line, and consistency."),
        ("F024", "Corner Consistency", "CORNER MASTERY", "Repeatability score of corner entry, apex speed, and throttle application."),
        ("F025", "Corner Improvement History", "CORNER MASTERY", "Historical trend of corner time loss and min-speed improvement over time."),
        ("F026", "Biggest Corner Loss", "CORNER MASTERY", "Automatic detection of the single corner where the driver loses the most time vs reference."),
        ("F027", "Easiest Gain", "CORNER MASTERY", "Identification of highest-confidence low-hanging-fruit improvement opportunity corner."),
        ("F028", "Corner Challenge", "CORNER MASTERY", "Targeted challenge focusing on executing a specific corner (e.g. gain 0.1s in T4)."),
        ("F029", "Corner Streak", "CORNER MASTERY", "Consecutive laps executing a specific corner within target time delta window."),
        ("F030", "Corner Mastery Badges", "CORNER MASTERY", "Badges awarded for mastering technical corner sequences (e.g. Eau Rouge / Raidillon Master)."),

        ("F031", "Daily Challenge", "DYNAMIC CHALLENGES", "Daily generated objective tailored to current active track or focus."),
        ("F032", "Weekly Challenge", "DYNAMIC CHALLENGES", "Larger multi-session periodic objective with higher XP reward."),
        ("F033", "Session Challenge", "DYNAMIC CHALLENGES", "Objective dynamically generated at session start based on current track and car."),
        ("F034", "Adaptive Challenge", "DYNAMIC CHALLENGES", "Personalized challenge targeting the driver's lowest-confidence skill weakness."),
        ("F035", "Challenge Difficulty", "DYNAMIC CHALLENGES", "Dynamic difficulty calibration (Easy, Medium, Hard, Expert) based on past success rate."),
        ("F036", "Challenge Chains", "DYNAMIC CHALLENGES", "Multi-stage sequential objectives (e.g. Stage 1: 3 consistent laps -> Stage 2: Beat PB)."),
        ("F037", "Challenge Categories", "DYNAMIC CHALLENGES", "Categorization across Pace, Consistency, Braking, Throttle, Fuel, Track Learning, Training."),
        ("F038", "Challenge Rewards", "DYNAMIC CHALLENGES", "XP, title unlocks, and career score bonuses for completing challenges."),
        ("F039", "Challenge Expiration", "DYNAMIC CHALLENGES", "Time limits for daily/weekly challenges with clean cleanup on expiration."),
        ("F040", "Challenge Rejection", "DYNAMIC CHALLENGES", "Ability for driver to skip or replace an active challenge without penalty."),

        ("F041", "PB Boss", "PB / COMPETITION", "Treating the driver's personal best lap as an explicit target to beat with live delta feedback."),
        ("F042", "Sector Recovery", "PB / COMPETITION", "Challenge to recover lost time in specific sectors relative to personal best lap."),
        ("F043", "Find One Second", "PB / COMPETITION", "High-level challenge identifying major supported time loss areas totaling 1 second."),
        ("F044", "Consistency Boss", "PB / COMPETITION", "Challenge to beat personal lap-to-lap variance baseline over 5 consecutive laps."),
        ("F045", "Median Pace Target", "PB / COMPETITION", "Objective to raise overall session median pace closer to personal theoretical best."),
        ("F046", "Best-Lap Composition", "PB / COMPETITION", "Optimal theoretical lap constructed from driver's best individual sector times."),
        ("F047", "Ghost Reference", "PB / COMPETITION", "Telemetry comparison against historical reference or session best lap."),
        ("F048", "Personal Rival", "PB / COMPETITION", "Persistent historical ghost/reference lap representing driver's previous month baseline."),
        ("F049", "Comeback Challenge", "PB / COMPETITION", "Objective to recover pace and focus following a severe mistake or bad lap."),
        ("F050", "Perfect Session", "PB / COMPETITION", "Configurable multi-lap high-quality session challenge (zero mistakes, target pace)."),

        ("F051", "Session Scorecard", "SESSION GAMIFICATION", "Post-session summary matrix of pace, consistency, fuel efficiency, and progress."),
        ("F052", "Session XP Summary", "SESSION GAMIFICATION", "Categorized breakdown of all XP earned during the completed session."),
        ("F053", "Session Highlights", "SESSION GAMIFICATION", "Automatic detection and display of key session events (PBs, corner gains, streaks)."),
        ("F054", "Session Weakness Summary", "SESSION GAMIFICATION", "Top actionable weaknesses identified during the session with evidence."),
        ("F055", "Session Next Step", "SESSION GAMIFICATION", "Recommended follow-up practice action provided immediately post-session."),
        ("F056", "Session Grade", "SESSION GAMIFICATION", "Application-calculated overall session grade (S, A, B, C, D) based on objective metrics."),
        ("F057", "Session Milestones", "SESSION GAMIFICATION", "In-session lap count, distance, and duration milestone notifications."),
        ("F058", "XP Quality Protection", "SESSION GAMIFICATION", "Suppression/reduction of XP awards when telemetry sample quality is poor or incomplete."),
        ("F059", "Replay Achievement Separation", "SESSION GAMIFICATION", "Ensures historical replay playback cannot silently award live career XP or achievements."),
        ("F060", "Session Comparison", "SESSION GAMIFICATION", "Side-by-side performance comparison between two historical sessions."),

        ("F061", "Consistency Streak", "STREAKS", "Track consecutive laps driven within a tight variance threshold (e.g. 5 laps within 0.3s)."),
        ("F062", "Improvement Streak", "STREAKS", "Track consecutive sessions with measurable pace or consistency improvements."),
        ("F063", "Training Streak", "STREAKS", "Track consecutive days/weeks with completed training modules."),
        ("F064", "Track Streak", "STREAKS", "Track consecutive practice sessions dedicated to mastering a target track."),
        ("F065", "Engineer Streak", "STREAKS", "Track consecutive completed race engineer missions."),
        ("F066", "PB Streak", "STREAKS", "Track consecutive sessions setting a new personal best lap time."),
        ("F067", "Precision Streak", "STREAKS", "Track consecutive laps hitting apex speeds and braking points within precise bounds."),
        ("F068", "Streak Protection", "STREAKS", "Optional streak protection tokens earned through consistent practice."),
        ("F069", "Streak Milestones", "STREAKS", "Milestone notifications and rewards for reaching 3, 7, 14, 30, 50, 100 streak counts."),
        ("F070", "Streak Break Analysis", "STREAKS", "Constructive debrief explaining why a streak ended without shaming the driver."),

        ("F071", "Engineer Relationship", "ENGINEER / CAREER", "Race engineer progression level deepening coaching insights as trust builds."),
        ("F072", "Engineer Missions", "ENGINEER / CAREER", "Structured evidence-backed missions assigned by the race engineer."),
        ("F073", "Engineer Coaching Tree", "ENGINEER / CAREER", "Progressively unlocked deeper telemetry analysis routines and voice feedback."),
        ("F074", "Engineer Memory", "ENGINEER / CAREER", "Inspectable and deletable structured memory of driver habits and weaknesses."),
        ("F075", "Engineer Debrief", "ENGINEER / CAREER", "Structured post-session voice and text debrief by the race engineer."),
        ("F076", "Engineer Briefing", "ENGINEER / CAREER", "Pre-session tactical briefing outlining target objectives and focus areas."),
        ("F077", "Engineer Confidence", "ENGINEER / CAREER", "Explicit confidence rating attached to every engineer advice and recommendation."),
        ("F078", "Engineer Unlocks", "ENGINEER / CAREER", "Unlockable specialized analysis experiences (e.g. Advanced Brake Trace Overlay)."),
        ("F079", "Engineer Why", "ENGINEER / CAREER", "Explainability view showing exact telemetry evidence supporting engineer recommendations."),
        ("F080", "Engineer Focus Mode", "ENGINEER / CAREER", "Driver-controlled setting directing engineer coaching toward specific skills."),

        ("F081", "Career Chapters", "CAREER / TRAINING", "Long-term progression chapters (1. Foundations, 2. Consistency, 3. Cornering, 4. Pace, 5. Strategy, 6. Racecraft, 7. Mastery)."),
        ("F082", "Training Curriculum", "CAREER / TRAINING", "Sequenced training exercise modules guiding driver skill development."),
        ("F083", "Training Medals", "CAREER / TRAINING", "Bronze, Silver, Gold, and Master medals awarded for training exercise performance."),
        ("F084", "Training Replay", "CAREER / TRAINING", "Ability to review telemetry traces from completed training attempts."),
        ("F085", "Training Personalization", "CAREER / TRAINING", "Dynamic recommendation of training exercises tailored to current weaknesses."),
        ("F086", "Skill Unlock Tree", "CAREER / TRAINING", "Visual progression tree detailing unlocked tools, titles, and capabilities."),
        ("F087", "Milestone Missions", "CAREER / TRAINING", "Major long-term career milestones (e.g. Drive 1,000 km, Master 10 tracks)."),
        ("F088", "Exploration Missions", "CAREER / TRAINING", "Missions encouraging driving different track categories and car layouts."),
        ("F089", "Collection System", "CAREER / TRAINING", "Driver collection gallery showcasing unlocked badges, titles, and track trophies."),
        ("F090", "Seasons", "CAREER / TRAINING", "Optional local progression seasons with periodic milestone challenges."),

        ("F091", "Racecraft Score", "GROUP / POLISH", "Application-calculated group driver interaction and clean racing observation score."),
        ("F092", "Battle Achievements", "GROUP / POLISH", "Achievements awarded for clean wheel-to-wheel multi-driver battle sessions."),
        ("F093", "Team/League Progress", "GROUP / POLISH", "Optional aggregate telemetry and milestone tracking for multi-driver groups."),
        ("F094", "Event Missions", "GROUP / POLISH", "Custom event objectives set by group/league hosts."),
        ("F095", "Steward Evidence Achievement", "GROUP / POLISH", "Rewards drivers for providing complete telemetry evidence logs for incident review."),
        ("F096", "Achievement Journal", "GROUP / POLISH", "Searchable historical log of all unlocked achievements and evidence metadata."),
        ("F097", "Notification Center", "GROUP / POLISH", "Centralized feed for career notifications, challenge updates, and milestones."),
        ("F098", "Anti-Farming System", "GROUP / POLISH", "Algorithmic detection of duplicate sessions or low-information telemetry to prevent XP exploitation."),
        ("F099", "Reduced Gamification Mode", "GROUP / POLISH", "Comprehensive settings toggle to suppress gamification elements for pure telemetry focus."),
        ("F100", "Full Career Dashboard", "GROUP / POLISH", "Unified driver development hub integrating levels, skills, tracks, challenges, and next actions.")
    ]

    for fid, title, cat, desc in features:
        f_path = os.path.join(root, "docs", "gamification", "features", f"{fid}.md")
        with open(f_path, "w", encoding="utf-8") as f:
            f.write(f"""# Feature Specification: {fid} - {title}

## GENERAL METADATA
- **ID**: {fid}
- **TITLE**: {title}
- **CATEGORY**: {cat}
- **PRIORITY**: P1
- **STATUS**: PLANNED

## PURPOSE & USER VALUE
{desc}

## REQUIRED DATA
- Telemetry source provenance (`REPORTED`, `CALCULATED`)
- Driver ID & Session ID
- Relevant metric samples (lap times, sector deltas, speeds, inputs)

## ARCHITECTURAL BOUNDARIES
- **BACKEND**: Services in `backend/app/gamification/` or `backend/app/analytics.py`
- **DATABASE**: Relational storage in `backend/app/storage.py` or dedicated SQLite tables
- **FRONTEND**: UI components under `frontend/src/`

## TRUTH CONSTRAINTS
- Never invent missing telemetry.
- All rewards must be idempotent and verifiable via stored evidence logs.
- Never present calculated values as official game data.

## ACCEPTANCE CRITERIA
1. Runtime engine evaluates criteria deterministically.
2. XP / state updates execute idempotently.
3. Relevant unit tests pass cleanly.
""")

    print(f"Successfully generated 100 feature specification files in docs/gamification/features/")

    # 7. Write docs/gamification/MASTER_SPEC.md
    master_spec_path = os.path.join(root, "docs", "gamification", "MASTER_SPEC.md")
    with open(master_spec_path, "w", encoding="utf-8") as f:
        f.write("""# GT7 RACE ENGINEER GAMIFICATION MASTER SPECIFICATION

## 1. PRODUCT VISION
Turn driving data into a long-term driver development experience.
Answer: What did I improve? What am I learning? What am I weak at? What should I practice next? Why does the system believe that?

## 2. ABSOLUTE TRUTH & PROVENANCE RULES
- Never invent telemetry missing from GT7 packets (wear, compound, official penalties, official flags).
- Tag every metric with explicit provenance (`REPORTED`, `CALCULATED`, `EXPERIMENTAL`, `USER_AUTHORED`, `SHARED_DRIVER`, `UNAVAILABLE`, `SYNTHETIC`, `REPLAY`).
- Never present calculated application data as official GT7 game telemetry.

## 3. CORE DOMAIN MODEL & PERSISTENCE
- Driver Level curve: `required_total_xp(level) = round(100 * (level - 1)^1.65)` up to Level 100.
- Skill Radar (0-100 score + confidence rating): Pace, Consistency, Braking, Cornering, Throttle, Fuel, Strategy, Track Knowledge, Racecraft, Discipline.
- Track Mastery (0-100 score): Pace (25%), Consistency (20%), Corners (25%), Training (15%), Strategy (15%).
- Idempotent Event Layer: Every XP event, achievement, or streak update carries a unique event ID and auditable evidence record.

## 4. 100 FEATURE ARCHITECTURE (F001 - F100)
- Features F001 through F100 are defined in individual files under `docs/gamification/features/`.
- Full matrix tracked in `.agent-state/feature-matrix.md`.
- Dependency map tracked in `.agent-state/dependency-map.md`.

## 5. LOCAL-FIRST & USER CONTROL
- Complete local offline functionality without mandatory cloud services.
- Reduced Gamification Mode allows toggling off UI notifications while preserving telemetry recording.
""")

    # 8. Write .agent-state files
    # current-state.md
    with open(os.path.join(root, ".agent-state", "current-state.md"), "w", encoding="utf-8") as f:
        f.write("""# PROJECT CURRENT STATE

## CURRENT PHASE
PHASE 0: Antigravity Bootstrap & Infrastructure Setup

## CURRENT TASK
Bootstrap Antigravity OS infrastructure, build feature specification matrix, inspect existing codebase, and create Phase 1 Implementation Plan.

## COMPLETED INFRASTRUCTURE
- [x] AGENTS.md permanent invariants
- [x] Scoped rules in `.agents/rules/`
- [x] Reusable skills in `.agents/skills/`
- [x] Specialized subagent definitions in `.agents/agents/`
- [x] Project state documents in `.agent-state/`
- [x] Master specification in `docs/gamification/MASTER_SPEC.md`
- [x] 100 individual feature spec files in `docs/gamification/features/F001.md` - `F100.md`
- [x] Feature Matrix and Dependency Map

## RECENT FILE CHANGES
- Created `.agents/` structure and files
- Created `docs/gamification/` spec files
- Created `.agent-state/` state trackers

## EXISTING CODEBASE ARCHITECTURE
- Backend: Python 3.12, FastAPI, asyncio, SQLite, UDP socket telemetry receiver (`backend/app/`)
- Telemetry Engine: `backend/app/telemetry/` (parser, frame, derived, bus)
- Analytics & Tracks: `backend/app/analytics.py`, `backend/app/tracks.py`, `backend/app/spatial_coaching.py`
- Engineer & Voice: `backend/app/engineer.py`, `backend/app/voice.py`, `backend/app/local_ai.py`
- Storage: SQLite database with sessions, laps, telemetry samples in `backend/app/storage.py`
- Frontend: React TypeScript Vite application in `frontend/`

## NEXT ACTION
Formulate Phase 1 Implementation Plan artifact covering Core Telemetry, Persistence, Driver Profile, XP Foundation, Skill Profile, and Career Dashboard.

## DO NOT TOUCH / HOTSPOT AREAS
- `backend/app/telemetry/parser.py`: GT7 UDP decrypt/parse logic is working and tested.
""")

    # feature-matrix.md
    with open(os.path.join(root, ".agent-state", "feature-matrix.md"), "w", encoding="utf-8") as f:
        f.write("""# FEATURE MATRIX

| ID | Name | Category | Priority | Status | Backend | Database | Frontend | Tests | Dependencies | Last Verified |
|---|---|---|---|---|---|---|---|---|---|---|
""")
        for fid, title, cat, _ in features:
            f.write(f"| {fid} | {title} | {cat} | P1 | PLANNED | NO | NO | NO | NO | None | Unverified |\n")

    # dependency-map.md
    with open(os.path.join(root, ".agent-state", "dependency-map.md"), "w", encoding="utf-8") as f:
        f.write("""# FEATURE DEPENDENCY MAP

## FOUNDATION (PHASE 1)
- F001 (Driver Level) -> Base XP Engine
- F002 (Driver Skill Profile) -> Analytics Metrics
- F003 (Skill Levels) -> F002
- F004 (Skill XP) -> F001, F002
- F005 (Driver Titles) -> F001, F002
- F006 (Driver Badges) -> F001
- F007 (Driver Overview Card) -> F001, F002
- F008 (Progress Timeline) -> Idempotent Event Log
- F009 (Recent Gains) -> F004, F052
- F010 (Personal Statistics Archive) -> Storage Core

## TRACK & CORNER MASTERY (PHASE 2 & 3)
- F011-F020 -> Track Recognition & Storage
- F021-F030 -> Spatial Coaching & Corner Identification

## DYNAMIC CHALLENGES (PHASE 4)
- F031-F040 -> Skill Profile, Weakness Engine

## PB & SESSION GAMIFICATION (PHASE 4 & 5)
- F041-F070 -> Telemetry Analytics, Lap Processing

## ENGINEER & CAREER (PHASE 5 & 6)
- F071-F090 -> Engineer Service, Speech Arbitration

## GROUP & POLISH (PHASE 7 & 8)
- F091-F100 -> Multi-driver telemetry, UI Shell
""")

    # active-work.md
    with open(os.path.join(root, ".agent-state", "active-work.md"), "w", encoding="utf-8") as f:
        f.write("""# ACTIVE WORK TRACKER

## CURRENT WORKSTREAM
Phase 0 Bootstrap Completion & Phase 1 Planning

## IN-PROGRESS TASK
Phase 1 Implementation Plan creation and architectural alignment.

## ASSIGNED SUBAGENTS
None active currently.
""")

    print("Antigravity OS Bootstrap files created successfully.")

if __name__ == "__main__":
    main()
