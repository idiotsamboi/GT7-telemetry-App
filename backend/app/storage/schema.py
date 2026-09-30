"""Schema upgrades applied inline by the writer thread (mirrored by backend/migrations/*.sql).

Every step is idempotent, so a database created at v1, v2 or v3 (or half-upgraded) converges on
the same schema. `SCHEMA_VERSION` must equal `core.version.DB_SCHEMA_VERSION`.
"""
import sqlite3

SCHEMA_VERSION = 9

AUDIT_DDL = '''
CREATE TABLE IF NOT EXISTS audit_log(
  id TEXT PRIMARY KEY, utc REAL NOT NULL, actor TEXT NOT NULL, capability TEXT NOT NULL,
  command_id TEXT NOT NULL, target TEXT, payload_hash TEXT, result_code TEXT NOT NULL,
  message TEXT, session_id TEXT);
CREATE INDEX IF NOT EXISTS audit_utc ON audit_log(utc);
CREATE INDEX IF NOT EXISTS audit_session ON audit_log(session_id);
'''


CAREER_DDL = '''
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
'''


CAREER_LEARNING_DDL = '\nCREATE TABLE IF NOT EXISTS career_track_mastery(\n driver_id TEXT NOT NULL, layout_id TEXT NOT NULL, car_id INTEGER NOT NULL,\n updated_at TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL,\n PRIMARY KEY(driver_id,layout_id,car_id));\nCREATE INDEX IF NOT EXISTS career_track_layout ON career_track_mastery(driver_id,layout_id);\nCREATE TABLE IF NOT EXISTS career_corner_mastery(\n driver_id TEXT NOT NULL, layout_id TEXT NOT NULL, car_id INTEGER NOT NULL, corner_id TEXT NOT NULL,\n updated_at TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL,\n PRIMARY KEY(driver_id,layout_id,car_id,corner_id));\nCREATE INDEX IF NOT EXISTS career_corner_layout ON career_corner_mastery(driver_id,layout_id);\nCREATE TABLE IF NOT EXISTS career_mastery_history(\n source_id TEXT NOT NULL, driver_id TEXT NOT NULL, layout_id TEXT NOT NULL,\n car_id INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,\n PRIMARY KEY(source_id,layout_id,car_id));\nCREATE INDEX IF NOT EXISTS career_mastery_history_driver ON career_mastery_history(driver_id,created_at);\nCREATE TABLE IF NOT EXISTS career_spatial_evidence(\n session_id TEXT NOT NULL, lap_id TEXT NOT NULL, payload TEXT NOT NULL,\n PRIMARY KEY(session_id,lap_id));\n\n\nCREATE TABLE IF NOT EXISTS career_challenges(\n id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, kind TEXT NOT NULL,\n bucket TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,\n expires_at TEXT, accepted_at TEXT, payload TEXT NOT NULL,\n UNIQUE(driver_id,kind,bucket));\nCREATE INDEX IF NOT EXISTS career_challenges_driver ON career_challenges(driver_id,status);\nCREATE TABLE IF NOT EXISTS career_challenge_sources(\n challenge_id TEXT NOT NULL, source_id TEXT NOT NULL, session_id TEXT NOT NULL,\n PRIMARY KEY(challenge_id,source_id), UNIQUE(challenge_id,session_id));\nCREATE TABLE IF NOT EXISTS career_challenge_history(\n id INTEGER PRIMARY KEY, challenge_id TEXT NOT NULL, driver_id TEXT NOT NULL,\n status TEXT NOT NULL, created_at TEXT NOT NULL);\n'


CAREER_COACHING_DDL = "\nCREATE TABLE IF NOT EXISTS career_engineer(\n driver_id TEXT PRIMARY KEY, focus TEXT NOT NULL DEFAULT 'consistency',\n xp INTEGER NOT NULL DEFAULT 0, memory TEXT NOT NULL DEFAULT '{}');\nCREATE TABLE IF NOT EXISTS career_missions(\n id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, challenge_id TEXT NOT NULL UNIQUE,\n created_at TEXT NOT NULL, completed_at TEXT, source_id TEXT);\nCREATE INDEX IF NOT EXISTS career_mission_driver ON career_missions(driver_id,created_at);\nCREATE TABLE IF NOT EXISTS career_learning_sources(\n source_id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, payload TEXT NOT NULL);\nCREATE INDEX IF NOT EXISTS career_learning_driver ON career_learning_sources(driver_id);\nCREATE TABLE IF NOT EXISTS career_streaks(\n driver_id TEXT NOT NULL, kind TEXT NOT NULL, current_count INTEGER NOT NULL,\n best_count INTEGER NOT NULL, last_source_id TEXT NOT NULL, reason TEXT,\n PRIMARY KEY(driver_id,kind));\nCREATE TABLE IF NOT EXISTS career_journal(\n id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, session_id TEXT, source_id TEXT,\n created_at TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, provenance TEXT NOT NULL);\nCREATE INDEX IF NOT EXISTS career_journal_driver ON career_journal(driver_id,created_at);\n"


CAREER_ARCHIVE_DDL = 'CREATE TABLE IF NOT EXISTS career_import_archives(driver_id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, provenance TEXT NOT NULL, payload TEXT NOT NULL, preview TEXT NOT NULL);\n'


CAREER_EVENTS_DDL = '''
CREATE TABLE IF NOT EXISTS career_events(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
 source_id TEXT NOT NULL, provenance TEXT NOT NULL, evidence TEXT NOT NULL,
 confidence REAL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_events_driver_time ON career_events(driver_id,created_at);
CREATE TABLE IF NOT EXISTS career_notifications(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, level TEXT NOT NULL, title TEXT NOT NULL,
 body TEXT NOT NULL, read_at TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_notifications_driver_time ON career_notifications(driver_id,created_at);
'''


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f'PRAGMA table_info({table})')}


def migrate(db: sqlite3.Connection) -> None:
    """Bring an open database (base tables already created) to SCHEMA_VERSION."""
    if 'archived_at' not in _columns(db, 'sessions'):                      # v2
        db.execute('ALTER TABLE sessions ADD COLUMN archived_at TEXT')
    if 'kind' not in _columns(db, 'events'):                               # v3: typed annotations
        db.execute('ALTER TABLE events ADD COLUMN kind TEXT')
    db.execute('CREATE INDEX IF NOT EXISTS event_kind ON events(session,kind)')
    db.execute('CREATE INDEX IF NOT EXISTS session_started ON sessions(started)')
    db.executescript(AUDIT_DDL)
    db.executescript(CAREER_DDL)
    db.executescript(CAREER_LEARNING_DDL)
    db.executescript(CAREER_COACHING_DDL)
    db.executescript(CAREER_ARCHIVE_DDL)
    db.executescript(CAREER_EVENTS_DDL)
    if 'current_title' not in _columns(db, 'career_profiles'):             # v9: equipped title
        db.execute('ALTER TABLE career_profiles ADD COLUMN current_title TEXT')
    db.execute('CREATE INDEX IF NOT EXISTS career_events_source ON career_events(kind,source_id)')
    current = db.execute('PRAGMA user_version').fetchone()[0]
    db.execute(f'PRAGMA user_version={max(current, SCHEMA_VERSION)}')
