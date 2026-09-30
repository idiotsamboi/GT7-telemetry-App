# FEATURE DEPENDENCY MAP

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
