# Storage

What is stored where, how it is versioned, and what can be lost. Verified against the code in `backend/app/storage/`,
`backend/app/core/config_migrations.py`, `backend/app/config.py`, `backend/app/group/` and `backend/app/analysis_cache.py`.

Not everything in `storage/` is wired into the running app yet. Each section says so where it applies (see
"What is and is not wired" at the end).

## 1. Data directory

The root is `--data <path>` (run.py, sets `GT7_DATA`), else `GT7_DATA`, else `<repo>/data`. `backend/app/storage/layout.py`
(`ENTRIES`, `DataLayout`) is the single map; `tests/test_storage_layout.py` asserts it matches what the modules create.
`GET /api/storage` returns `DataLayout.describe()` (relative paths only) plus `Store.health()`.

| key | location (under root) | kind | contents | sensitive |
|---|---|---|---|---|
| settings | `settings.json` | file | User settings (validated, migrated); `.bak` copies alongside | yes |
| control_token | `control-token` | file | Browser pairing token for the local control API | yes |
| database | `telemetry.sqlite3` (+ `-wal`, `-shm`) | file | Sessions, laps, samples, events, audit log, group tables | yes |
| track_maps | `track-maps/` | dir | Legacy learned track maps and candidates | no |
| corpus | `track-maps/_corpus.jsonl` | file | Bounded anonymous track-point corpus (cap `CORPUS_MAX_BYTES` = 40 MiB) | no |
| track_models | `track-models/` | dir | User track world models overlaying the bundled catalogue | no |
| track_models_user | `track-models-user/` | dir | Optional locally installed schema-3 world models (read-only extension point; not created by `ensure()`) | no |
| track_training | `track-training/` | dir | Track training laps recorded for model fusion | no |
| league_assets | `league-assets/` | dir | Uploaded league logos and graphics | no |
| exports | `exports/` | dir | Session export bundles (zip) | yes |
| logs | `logs/` | dir | Rotating JSONL application logs (redacted); see `LOGGING_AND_DIAGNOSTICS.md` | no |
| analysis_cache | `cache/analysis/` | dir | Disposable analysis results; safe to delete | no |
| running_marker | `.running` | file | Present while the app runs; found at start-up means unclean shutdown | no |

Files that exist but are not in `ENTRIES`: `settings.v{n}.bak.json`, `settings.invalid-<ns>.json`, `settings.tmp`
(transient), and `telemetry-safe.sqlite3` (the fallback database, section 3).

`DataLayout.ensure()` creates only the directories flagged `ensured`, refuses anything that would resolve outside the root,
and never writes files. Two classes write the `.running` marker: `DataLayout.mark_running/clear_running` and
`safe_mode.RunMarker`; `create_app` uses `RunMarker`.

## 2. Settings versioning

`Settings.schema_version` is compared with `SETTINGS_SCHEMA_VERSION` (currently 2, `core/version.py`).
`core/config_migrations.py`:

| step | function | adds |
|---|---|---|
| 1 -> 2 | `m1_to_2` | `units`, `performance_profile`, `log_level`, `feature_flags`, `safe_mode_on_crash`, `developer_mode`, `demo_scenario` (all via `setdefault`, so user values survive) |

`MIGRATIONS` is a dict `{from_version: fn}`; an `assert` at import requires one entry per version below the current one.
A file without `schema_version` counts as version 1.

Load path (`Config._load`): read raw JSON, `migrate()`, `Settings.model_validate()`. Only if a migration ran: back up the old
file as `settings.v{n}.bak.json` (`n` = first version applied), keep the newest 3 `settings.v*.bak.json` by mtime, then write the
migrated file. Validation happens before the backup and write, so a bad file is never half-migrated. Writes are atomic
(`settings.tmp`, fsync, replace).

Failure handling (`Config.__init__`): a file that is invalid JSON, not an object, fails validation, or comes from a newer schema
raises `ValueError`. The original is copied to `settings.invalid-<time_ns>.json`, `Settings(hands_free=False, speech_enabled=False)`
is loaded, and `Config.recovery_notice` carries a message the UI shows. If the copy also fails the notice says so and the
original is left untouched. `recovery_notice` also triggers safe mode (`LOGGING_AND_DIAGNOSTICS.md`).

Tests: `tests/test_core_foundation.py` (`test_migration_*`, `test_config_migrates_old_file_with_backup_and_keeps_values`,
`test_config_keeps_last_three_backups`, `test_config_newer_or_corrupt_file_falls_back_to_safe_defaults`),
`tests/test_recovery.py`.

## 3. SQLite database

Owner: `storage/store.py` `Store`. One file, WAL, opened by a single daemon thread named `sqlite-writer`.

### Schema

| table | purpose | notes |
|---|---|---|
| `sessions` | one row per session | `status`, `provenance`, `meta` (JSON), `report` (JSON), `protected`, `archived_at` (v2) |
| `samples` | recorded telemetry | `session`, `lap_id`, `mono`, `packet_id`, `payload` (JSON); index `(session, mono)`; no `(session, lap_id)` index (TECH_DEBT #17) |
| `laps` | lap records | `payload` JSON; index on `session` |
| `events` | engineer decisions and typed annotations | `kind` (v3) is NULL for old untyped decisions; index `(session, kind)` |
| `profiles` | named settings profiles | |
| `audit_log` | privileged command record (v3) | section 8 |

`PRAGMA user_version` is 3 (`DB_SCHEMA_VERSION`).

### Migrations

`Store._run` executes the base DDL (`CREATE IF NOT EXISTS`, sets `user_version=1`), then `storage/schema.migrate(db)`, which
is idempotent and inline: add `sessions.archived_at` if missing (v2); add `events.kind` if missing, `event_kind` and
`session_started` indexes, and the audit DDL (v3); then `user_version = max(current, 3)`. A database created at v1, v2, v3 or
half upgraded converges on the same schema.

`backend/migrations/001_initial.sql`, `002_archive.sql`, `003_annotations_audit.sql` mirror the inline steps for humans and
tools; `tests/test_storage_migrations.py::test_sql_files_mirror_inline_migration` keeps them in step. To add a migration:
add an idempotent step to `schema.migrate`, bump `SCHEMA_VERSION` and `core.version.DB_SCHEMA_VERSION` together, add
`004_*.sql`, extend the migration test.

At start the writer also marks any session with `ended IS NULL` as `interrupted` (`ended = now`).

### Single writer, job kinds, batching

Every write is a job on a bounded `queue.Queue` (capacity 8192, `defaults.RECORDER_QUEUE`, but `Store` hard-codes the number).
`Store.put(kind, args)` never blocks: it returns `False` and increments `drops` when the queue is full. The writer collects up
to 240 jobs or 200 ms, whichever comes first (`RECORDER_BATCH`, `RECORDER_BATCH_WINDOW_S`; also hard-coded in `Store`), and
commits them in one transaction. Pragmas: `journal_mode=WAL`, `synchronous=NORMAL`, `wal_autocheckpoint=1000`; the writer
runs `wal_checkpoint(TRUNCATE)` on clean stop. Reads use short-lived read-only connections (`Store.query`, `mode=ro`).

| job kind | effect |
|---|---|
| `sample` | insert into `samples` |
| `session` | upsert `sessions`; keeps the existing `protected` value |
| `lap` | upsert `laps` |
| `event` | insert untyped `events` row |
| `annotation` | insert `events` row with `kind` |
| `audit` | `INSERT OR IGNORE` into `audit_log` |
| `metadata` | update `meta` and `protected` |
| `archive` | set/clear `archived_at`; refused for active sessions and (when setting) protected ones |
| `correct` | update `status` and `report` of an ended session |
| `purge` | delete samples/laps/events/session, only if ended, unprotected and archived (re-checked in the transaction) |
| `profile` | upsert `profiles` |
| `barrier`, `stop` | `flush()` synchronisation and shutdown |

`Store.flush()` enqueues a barrier and waits (default 10 s); callers use it before reading their own writes.

The group service does not use this queue: `group/repository.py` `GroupRepository` opens its own short connections to the same
file (busy timeout 2 s) under a lock. "Single writer thread" therefore describes the recorder tables, not the whole file.

### Recorder queue and loss accounting

The sample path is `Sessions.consume` -> `store.put('sample', ...)`. Nothing here blocks the ingest path.

| signal | meaning | where visible |
|---|---|---|
| `application_drops` (`Store.drops`) | queue full, sample not enqueued | `Store.health()`, diagnostics `recorder`, `Sessions.report()['recording']`, service `recorder` (DEGRADED) |
| session quality flag `recording queue drop` | the session lost at least one sample | session report `quality` |
| `failed_rows` | samples in a batch whose transaction failed (`sqlite3.Error`/`OSError`); the batch is rolled back | same |
| `error` | last writer error, cleared by the next successful batch | same; service FAILED while set |
| `written`, `queue`, `queue_age_s`, `db_bytes`, `wal_bytes` | throughput and backlog | `Store.health()` |

`Store.health()` is what `/api/storage`, `/api/diagnostics` (`recorder`, `storage`) and the `recorder` service probe read. The
drop and failure counters are per process lifetime (the report says "application lifetime; includes current session").

### Durability window

On an abrupt process kill (no flush, no clean stop) the committed WAL survives and the next start marks the session
`interrupted`. What can be lost is the uncommitted tail: the batch in flight (up to 200 ms of samples, at most 240 jobs)
plus whatever is queued. Under normal load the queue is nearly empty (a 20 s, 60 Hz soak peaked at 6 to 14 queued jobs).
The test bound is queue plus one batch: `3200 - count <= 240 + 200`.

`tests/test_runtime_foundation.py::test_recorder_recovers_after_abrupt_kill_with_bounded_loss` feeds 3200 frames in a child
process, `os._exit(1)`s it, then asserts `status == 'interrupted'`, `3000 <= rows <= 3200` (the first 3000 were given one
second to commit) and the 440-row bound.

`synchronous=NORMAL` protects against process death but, in WAL mode, an OS crash or power loss can also roll back the most
recent commits (the database stays consistent). This is SQLite's documented behaviour; no test covers it.

Also covered: `tests/test_reliability.py::test_crash_recovery_and_bounded_queue`, `::test_database_full_keeps_writer_alive`,
`tests/test_storage_migrations.py::test_bounded_queue_semantics_unchanged`.

### OneDrive and WAL

The dev tree lives inside OneDrive and SQLite WAL files (`-wal`, `-shm`) on a synced folder can be locked or partially
synced. This is TECH_DEBT #6/#7: keep dev data dirs outside the tree (`--data <path>`), outside OneDrive, and exclude
`data*/`. Production installs use a local data directory.

### Fallback database

If `Store(<root>/telemetry.sqlite3)` raises at start, `create_app` logs `storage_open_failed`, opens
`<root>/telemetry-safe.sqlite3` instead and starts in safe mode (reason `storage_failed`). Recordings then go to the
temporary file; the original database is not touched.

## 4. Sessions: repository API

`storage/repositories.py`: `SessionRepository` (Protocol) and `SqliteSessionRepository(store)`. Rules: list/get never load
samples; samples are paged and channel-projected; writes go through the writer queue and raise `AppError(UNAVAILABLE)` if the
queue is full.

| method | notes |
|---|---|
| `list(SessionQuery)` | index-only; `include_archived`, `provenance`, `limit` (clamped to 200), keyset `cursor` (wins over `offset`); returns `Page[SessionSummary]` with `lap_count` |
| `get(sid)` | metadata, laps (max 10 000) and report; no samples |
| `samples(sid, after=, lap_id=, channels=, limit=)` | `after` is an exclusive `record_id` cursor; page max 10 000 |
| `lap_series(sid, lap_id, channels, points=600)` | per-channel downsample keeping min and max per bucket; reads at most 200 000 source rows (`truncated` says so) |
| `update_meta`, `protect`, `archive` | queued; flush by default |
| `purge(sid, confirm=)` | needs `confirm == 'DELETE ARCHIVED SESSION'`; refuses active, protected, non-archived sessions |
| `annotations(sid, kinds, limit)` | typed events (section 9) |

Tests: `tests/test_storage_repositories.py`.

## 5. Retention

Policy is pure (`storage/retention.py`): `RetentionPolicy(days, max_bytes, protect_favourites)` and
`select_for_archive(sessions, policy, now, db_bytes)`. It picks the oldest eligible sessions older than `days`, then, only when
the database exceeds `max_bytes`, more oldest sessions until the estimated excess is covered. Protected sessions, active
sessions (`ended` is NULL), already archived ones and (by default) `meta.favourite` sessions are never selected. It only
selects; archiving is a separate call and nothing here purges. Tests: `tests/test_storage_retention.py`.

The HTTP routes do not use it yet. `GET/POST /api/retention` run their own SQL: ended, unprotected, unarchived sessions ended
before `now - Settings.retention_days` (default 90), at most 1000; `POST` archives them (recoverable). It does not apply
the size cap or the favourites rule. Purge is `POST /api/sessions/{sid}/purge` with the confirmation string, refused while a
session is recording. See section 11.

## 6. Export and import

`storage/exports.py` holds two registries.

| export format | extension | supports | notes |
|---|---|---|---|
| `bundle_v1` | `.zip` | session | wraps `exporting.export_bundle` unchanged |
| `csv` | `.csv` | session, lap | header with units; formula-looking cells neutralised (`exporting.safe_cell`); `channels` and `lap_id` options |
| `jsonl` | `.jsonl` | session, lap | full stored payloads, or projected rows when `channels` is given |
| `html_report` | `.html` | session | `exporting.report_html` |

`GET /api/export-formats` lists them; `GET /api/sessions/{sid}/export?format=&lap_id=&channels=` exports (409 while
recording). `bundle_v1` is special-cased in `api.py` and written to `exports/`; the others are built in memory.

`ExportFormat(id, name, extension, supports, write, media_type)`: `write(source, sid, stream, options)`.
`IMPORT_HANDLERS` (`ImportHandler(id, name, extensions, schema_versions, sniff, validate)`) has one handler, `bundle_v1`.
`import_session_file(data, handler_id=None)` enforces `IMPORT_MAX_BYTES` (32 MiB), sniffs, validates and checks the schema
version; nothing is unpickled or evaluated. `POST /api/import` currently calls `exporting.inspect_bundle` directly rather than
`import_session_file`, with the same 32 MiB cap. Tests: `tests/test_storage_exports.py`.

## 7. Analysis cache

`backend/app/analysis_cache.py` `AnalysisCache(root, max_bytes=ANALYSIS_CACHE_MAX_BYTES)` (500 MiB) stores JSON under
`cache/analysis/`.

- Key: `(session_id, source_hash, analysis_version, settings_hash)`. `source_hash(store, sid)` is the max sample id, sample
  count and lap ids (SQL only); `settings_hash(settings)` is a digest of the JSON; `analysis_version` defaults to
  `core.version.ANALYSIS_VERSION`. A changed key simply misses.
- Bound and LRU: `put` refuses an entry larger than the bound (returns `False`) and then evicts oldest-mtime files until under
  the bound; `get` refreshes mtime (`os.utime`), so eviction is least recently used.
- Writes are atomic (temp file, `os.replace`). Filenames start with a digest of the session id, so `invalidate(session_id)`
  needs no reads; `clear()` removes everything; `stats()` reports entries, bytes, hits, misses, evictions.

Nothing in the app calls it yet. Tests: `tests/test_storage_cache.py`.

## 8. Audit log

`audit_log(id, utc, actor, capability, command_id, target, payload_hash, result_code, message, session_id)` with indexes on
`utc` and `session_id`. Rows are written by `storage/audit.py` `AuditSink` (the `Ctx.audit` callable) through the writer
queue; message is truncated to 200 characters, payloads are hashed, never stored. If the queue is full the sink raises,
`dispatch()` logs `audit_write_failed` and the command result has no `audit_id` (no silent loss of the log line, but the row is
gone). Purging a session does not delete audit rows. Query: `Store.audit(session, since, limit)` (newest first, limit 1 to
5000) behind `GET /api/audit` (`limit` 1 to 1000, default 200; flushes the queue first). Details: `COMMANDS_AND_PERMISSIONS.md`,
ADR 0007. Tests: `tests/test_storage_audit.py`.

## 9. Annotations

`events.kind` (migration 003) holds a typed annotation: `incident`, `flag`, `pit`, `radio`, `user_marker`,
`engineer_alert`, `system`, `race_control`, `lap_boundary`, `bookmark` (`domain/annotations.py` `KINDS`). Rows written before
v3 have `kind` NULL and are converted on read by `Annotation.from_decision_event`. `Store.annotations(session, kinds, limit)`
returns rows with `kind IS NOT NULL`. `Runtime.decision()` still writes untyped `event` jobs (TECH_DEBT #13), so most engineer
decisions do not appear in `annotations()` yet.

## 10. Group data

Group state lives in the same SQLite file, created by `GroupRepository.__init__` (`CREATE IF NOT EXISTS`, not by
`backend/migrations`).

| table | contents |
|---|---|
| `group_schema` | a single `version` row, always 1; unused as a migration chain |
| `group_documents(kind, id, parent, payload)` | leagues, league revisions, groups, group sessions, assets, workspaces as JSON |
| `group_credentials(hash, kind, subject, group_id, expires, revoked)` | SHA-256 of tokens only; the token is shown once |
| `group_events(seq, group_id, session_id, utc, actor, kind, payload)` | the domain event stream (ADR 0007) |
| `group_frames(id, session_id, utc, payload)` | recorded group frames for replay |

Document schema upgrades (`group/migrations.py`): every document may carry an integer `schema` (missing means 1).
`CURRENT_SCHEMA` = league 2, league_revision 2, group 2, group_session 2, asset 2, workspace 1. `upgrade()` runs when a
document is loaded and upgrades it in memory through `UPGRADES[(type, from)]`; `stamp()` writes the current schema on the next
`commit`, so old databases need no bulk rewrite. A document newer than the app is returned untouched and logged
`group_schema_newer`; a gap in the chain raises `MissingUpgrade`. Upgrade steps must be idempotent and never drop data; team ids
are deterministic (`uuid5`). To add one: bump `CURRENT_SCHEMA[type]`, register the step, add a case to
`tests/test_group_migrations.py`.

Assets (`group/assets.py`): the image is decoded in an isolated spawned process (5 s limit, 5 MiB upload), then files go to
`league-assets/<id>/` (`original.bin`, `512.png`, `1024.png`, `2048.png`; only variants are served) and metadata to a
`group_documents` row of kind `asset`: `bytes`, `width`, `height`, `sha256` (of the 1024 variant), `created`, `kind`
(`logo`, `sponsor`, `team`, `driver_photo`, `background`), `name`, `license_note`, `created_by`. Quotas: 50 MiB per league,
1 GiB total.

## 11. Privacy

- No raw audio is stored. There is no code path that writes microphone or speaker audio to the data directory.
- Transcripts stay in memory: `Runtime.transcript` is set only when `Settings.retain_transcripts` is on (default off) and is
  never written to the database. It is included in the `/ws` snapshot (`audio.transcript`) so the UI can show it.
- Test: `tests/test_runtime_foundation.py::test_no_audio_or_transcript_is_persisted` (no audio-suffixed files anywhere under the
  data dir, no stored event containing the transcript text) and `::test_transcript_is_only_kept_when_the_user_opts_in`.
- `Settings.raw_capture` (default off) keeps the decrypted packet hex (`raw_hex`) inside each stored sample payload. That is
  telemetry, not audio, but it enlarges the database.
- Tokens and credentials are never stored in the clear: `group_credentials` holds hashes; `control-token` is the exception
  (local pairing token, file mode 0600 where the OS honours it).

## 12. What is and is not wired

| piece | state |
|---|---|
| `Store`, schema, migrations, audit sink, annotations, layout `describe()`, export registry route | in use |
| Settings migration chain, backups, invalid-file handling | in use |
| Group document upgrades, asset metadata | in use |
| `SqliteSessionRepository` | in use by `GET /api/sessions-index` and `GET /api/sessions/{sid}/lap-series`; the legacy `/api/sessions*` routes still call `Store.sessions/detail/samples` (their JSON shape is unchanged) |
| `storage/retention.py` | in use: `/api/retention` (preview/apply) and `sessions.retention` select via `select_for_archive` (age from session end, favourites protected, optional `max_storage_gb`) |
| `AnalysisCache` | in use by `POST /api/compare` (key: both sessions' content hash + `ANALYSIS_VERSION`) |
| `import_session_file` / `IMPORT_HANDLERS` | in use by `POST /api/import` |
| `RECORDER_*` constants in `core/defaults.py` | read by `Store` (queue size, batch size, batch window) |
| `Settings.retention_days` | used by `/api/retention` |
| `sessions.manage` / `sessions.purge` capabilities | enforced for the `sessions.*` commands; the legacy session routes are gated by the local pairing token only |
