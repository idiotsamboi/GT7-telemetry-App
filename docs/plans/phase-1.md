# Phase 1 - progression foundation gaps
Scope: only what F001-F100 need that is missing. Reuse processor.py queue, career_transaction, feature flags.
F-IDs: foundation for F009, F014, F066 (PB_SET), F097 (notifications), F098 (anti-farming), F052 (xp audit).
Files (new): backend/app/gamification/events.py (typed ProgressionEvent + deterministic ids), notifications.py (repo + levels CRITICAL/IMPORTANT/NORMAL/SILENT, bounded), antifarm.py (pure functions: duplicate/loop/low-information detectors returning reduction factor + reason), migration 008_career_events_notifications.sql (career_events, career_notifications; additive).
Changes: processor.py emits PB_SET/LEVEL_UP/ACHIEVEMENT_UNLOCKED via events.py after the transaction commits; repository.py exposes notifications(); api.py GET /notifications, POST /notifications/{id}/read.
Data model: career_events(id PK deterministic, driver_id, kind, source, source_id, provenance, evidence, confidence, created_at); career_notifications(id PK = event id, driver_id, level, title, body, read_at, created_at).
Tests: tests/test_gamification_events.py (id determinism, double-process no-op, non-live no notification, bounded retention, migration from 007, processor failure non-fatal).
Risks: queue overflow (cap 128) -> already recovery every 30s; migration safety -> additive only.
Rollback: flag driver_progression off; tables unused.
Perf: no per-packet work; events only at session/lap finalize.
