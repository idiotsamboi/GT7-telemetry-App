CREATE TABLE IF NOT EXISTS career_events(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
 source_id TEXT NOT NULL, provenance TEXT NOT NULL, evidence TEXT NOT NULL,
 confidence REAL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_events_driver_time ON career_events(driver_id,created_at);
CREATE TABLE IF NOT EXISTS career_notifications(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, level TEXT NOT NULL, title TEXT NOT NULL,
 body TEXT NOT NULL, read_at TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_notifications_driver_time ON career_notifications(driver_id,created_at);
PRAGMA user_version=8;
