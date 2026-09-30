# GT7 RACE ENGINEER GAMIFICATION MASTER SPECIFICATION

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
