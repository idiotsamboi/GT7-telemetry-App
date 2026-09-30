-- v3: typed annotations on events, audit log, session list index.
-- Applied inline (idempotently) by backend/app/storage/schema.py; this file mirrors it for humans/tools.
-- Old events keep kind = NULL (still valid; adapters treat NULL as an untyped engineer decision).
ALTER TABLE events ADD COLUMN kind TEXT;
CREATE INDEX IF NOT EXISTS event_kind ON events(session,kind);
CREATE INDEX IF NOT EXISTS session_started ON sessions(started);
CREATE TABLE IF NOT EXISTS audit_log(id TEXT PRIMARY KEY,utc REAL NOT NULL,actor TEXT NOT NULL,capability TEXT NOT NULL,command_id TEXT NOT NULL,target TEXT,payload_hash TEXT,result_code TEXT NOT NULL,message TEXT,session_id TEXT);
CREATE INDEX IF NOT EXISTS audit_utc ON audit_log(utc);
CREATE INDEX IF NOT EXISTS audit_session ON audit_log(session_id);
PRAGMA user_version=3;
