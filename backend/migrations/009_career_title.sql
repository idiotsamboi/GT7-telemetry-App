ALTER TABLE career_profiles ADD COLUMN current_title TEXT;
CREATE INDEX IF NOT EXISTS career_events_source ON career_events(kind,source_id);
PRAGMA user_version=9;
