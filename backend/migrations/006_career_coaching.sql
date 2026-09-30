
CREATE TABLE IF NOT EXISTS career_engineer(
 driver_id TEXT PRIMARY KEY, focus TEXT NOT NULL DEFAULT 'consistency',
 xp INTEGER NOT NULL DEFAULT 0, memory TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS career_missions(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, challenge_id TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL, completed_at TEXT, source_id TEXT);
CREATE INDEX IF NOT EXISTS career_mission_driver ON career_missions(driver_id,created_at);
CREATE TABLE IF NOT EXISTS career_learning_sources(
 source_id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_learning_driver ON career_learning_sources(driver_id);
CREATE TABLE IF NOT EXISTS career_streaks(
 driver_id TEXT NOT NULL, kind TEXT NOT NULL, current_count INTEGER NOT NULL,
 best_count INTEGER NOT NULL, last_source_id TEXT NOT NULL, reason TEXT,
 PRIMARY KEY(driver_id,kind));
CREATE TABLE IF NOT EXISTS career_journal(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, session_id TEXT, source_id TEXT,
 created_at TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, provenance TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_journal_driver ON career_journal(driver_id,created_at);

PRAGMA user_version=6;
