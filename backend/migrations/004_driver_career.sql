-- Additive Driver Career foundation. Mirrored in storage/schema.py.
CREATE TABLE IF NOT EXISTS career_profiles(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
 total_xp INTEGER NOT NULL DEFAULT 0, eligible_sessions INTEGER NOT NULL DEFAULT 0,
 comparable_laps INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS career_settings(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_driver_id TEXT, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS career_bindings(
 session_id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, provenance TEXT NOT NULL,
 created_at TEXT NOT NULL, invalid_reason TEXT);
CREATE INDEX IF NOT EXISTS career_binding_driver ON career_bindings(driver_id,created_at);
CREATE TABLE IF NOT EXISTS career_lap_context(
 session_id TEXT NOT NULL, lap_id TEXT NOT NULL, evidence TEXT NOT NULL,
 PRIMARY KEY(session_id,lap_id));
CREATE TABLE IF NOT EXISTS career_sources(
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL UNIQUE, driver_id TEXT NOT NULL,
 created_at TEXT NOT NULL, provenance TEXT NOT NULL, algorithm_version INTEGER NOT NULL,
 status TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_source_driver_time ON career_sources(driver_id,created_at);
CREATE INDEX IF NOT EXISTS career_source_status ON career_sources(status);
CREATE TABLE IF NOT EXISTS career_xp_events(
 id TEXT PRIMARY KEY, guard TEXT NOT NULL UNIQUE, driver_id TEXT NOT NULL,
 session_id TEXT NOT NULL, source_id TEXT NOT NULL, category TEXT NOT NULL,
 amount INTEGER NOT NULL CHECK(amount>0), created_at TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_xp_driver_time ON career_xp_events(driver_id,created_at);
CREATE INDEX IF NOT EXISTS career_xp_session ON career_xp_events(session_id);
CREATE INDEX IF NOT EXISTS career_xp_category ON career_xp_events(driver_id,category);
CREATE TABLE IF NOT EXISTS career_skills(
 driver_id TEXT NOT NULL, category TEXT NOT NULL, score REAL, confidence REAL NOT NULL DEFAULT 0,
 xp INTEGER NOT NULL DEFAULT 0, evidence_count INTEGER NOT NULL DEFAULT 0, source_id TEXT,
 PRIMARY KEY(driver_id,category));
CREATE TABLE IF NOT EXISTS career_achievements(
 driver_id TEXT NOT NULL, definition_id TEXT NOT NULL, title TEXT NOT NULL,
 earned_at TEXT NOT NULL, source_id TEXT NOT NULL, evidence TEXT NOT NULL,
 PRIMARY KEY(driver_id,definition_id));
CREATE TABLE IF NOT EXISTS career_scorecards(
 session_id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, created_at TEXT NOT NULL,
 status TEXT NOT NULL, xp_awarded INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_scorecard_driver_time ON career_scorecards(driver_id,created_at);
CREATE TABLE IF NOT EXISTS career_reward_guards(
 driver_id TEXT NOT NULL, fingerprint TEXT NOT NULL, source_id TEXT NOT NULL,
 PRIMARY KEY(driver_id,fingerprint));
PRAGMA user_version=4;
