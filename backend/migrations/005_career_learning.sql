
CREATE TABLE IF NOT EXISTS career_track_mastery(
 driver_id TEXT NOT NULL, layout_id TEXT NOT NULL, car_id INTEGER NOT NULL,
 updated_at TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(driver_id,layout_id,car_id));
CREATE INDEX IF NOT EXISTS career_track_layout ON career_track_mastery(driver_id,layout_id);
CREATE TABLE IF NOT EXISTS career_corner_mastery(
 driver_id TEXT NOT NULL, layout_id TEXT NOT NULL, car_id INTEGER NOT NULL, corner_id TEXT NOT NULL,
 updated_at TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(driver_id,layout_id,car_id,corner_id));
CREATE INDEX IF NOT EXISTS career_corner_layout ON career_corner_mastery(driver_id,layout_id);
CREATE TABLE IF NOT EXISTS career_mastery_history(
 source_id TEXT NOT NULL, driver_id TEXT NOT NULL, layout_id TEXT NOT NULL,
 car_id INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(source_id,layout_id,car_id));
CREATE INDEX IF NOT EXISTS career_mastery_history_driver ON career_mastery_history(driver_id,created_at);
CREATE TABLE IF NOT EXISTS career_spatial_evidence(
 session_id TEXT NOT NULL, lap_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(session_id,lap_id));


CREATE TABLE IF NOT EXISTS career_challenges(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, kind TEXT NOT NULL,
 bucket TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT, accepted_at TEXT, payload TEXT NOT NULL,
 UNIQUE(driver_id,kind,bucket));
CREATE INDEX IF NOT EXISTS career_challenges_driver ON career_challenges(driver_id,status);
CREATE TABLE IF NOT EXISTS career_challenge_sources(
 challenge_id TEXT NOT NULL, source_id TEXT NOT NULL, session_id TEXT NOT NULL,
 PRIMARY KEY(challenge_id,source_id), UNIQUE(challenge_id,session_id));
CREATE TABLE IF NOT EXISTS career_challenge_history(
 id INTEGER PRIMARY KEY, challenge_id TEXT NOT NULL, driver_id TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL);

PRAGMA user_version=5;
