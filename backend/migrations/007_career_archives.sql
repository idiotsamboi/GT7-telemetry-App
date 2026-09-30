CREATE TABLE IF NOT EXISTS career_import_archives(driver_id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, provenance TEXT NOT NULL, payload TEXT NOT NULL, preview TEXT NOT NULL);
PRAGMA user_version=7;
