import json
import sqlite3
from pathlib import Path

import pytest

from backend.app.core.version import DB_SCHEMA_VERSION
from backend.app.storage import Store, MIGRATION
from backend.app.storage.schema import SCHEMA_VERSION

MIGRATIONS = Path(__file__).resolve().parents[1] / 'backend' / 'migrations'


def schema_of(path):
    db = sqlite3.connect(path)
    try:
        tables = {r[0]: [(c[1], c[2]) for c in db.execute(f'PRAGMA table_info({r[0]})')]
                  for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        indexes = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")}
        return tables, indexes, db.execute('PRAGMA user_version').fetchone()[0]
    finally:
        db.close()


def make_old_db(path, version):
    """A real pre-upgrade database: the v1 (and optionally v2) schema plus data written by the old code."""
    db = sqlite3.connect(path)
    db.executescript(MIGRATION)                       # v1 tables, user_version=1
    if version >= 2:
        db.execute('ALTER TABLE sessions ADD COLUMN archived_at TEXT')
        db.execute('PRAGMA user_version=2')
    db.execute("INSERT INTO sessions(id,started,ended,status,provenance,meta,report,protected) VALUES('old','2025-01-01T00:00:00+00:00','2025-01-01T00:10:00+00:00','completed','live','{}','{}',1)")
    db.execute("INSERT INTO events(session,utc,payload) VALUES('old','2025-01-01T00:01:00+00:00',?)", (json.dumps({'category': 'fuel', 'message': 'old event'}),))
    db.commit()
    db.close()


@pytest.mark.parametrize('version', [1, 2])
def test_old_database_upgrades_in_place(tmp_path, version):
    path = tmp_path / 'old.db'
    make_old_db(path, version)
    store = Store(path)
    try:
        detail = store.detail('old')
        assert detail['protected'] == 1 and detail['events'][0]['message'] == 'old event'   # data untouched
        assert store.query('SELECT kind FROM events')[0]['kind'] is None                   # old events: NULL kind is valid
        assert store.annotations('old') == []                                              # untyped events are not annotations
    finally:
        store.close()
    tables, indexes, user_version = schema_of(path)
    assert user_version == 7 == SCHEMA_VERSION == DB_SCHEMA_VERSION
    assert 'kind' in [c for c, _ in tables['events']] and 'audit_log' in tables
    assert {'event_kind', 'audit_utc', 'audit_session', 'session_started'} <= indexes


def test_upgrade_is_idempotent_and_matches_fresh_schema(tmp_path):
    make_old_db(tmp_path / 'old.db', 1)
    for _ in range(2):                                # re-opening an upgraded database changes nothing
        Store(tmp_path / 'old.db').close()
    Store(tmp_path / 'fresh.db').close()
    assert schema_of(tmp_path / 'old.db') == schema_of(tmp_path / 'fresh.db')


def test_sql_files_mirror_inline_migration(tmp_path):
    db = sqlite3.connect(tmp_path / 'sql.db')
    for name in ('001_initial.sql', '002_archive.sql', '003_annotations_audit.sql', '004_driver_career.sql', '005_career_learning.sql', '006_career_coaching.sql', '007_career_archives.sql'):
        db.executescript((MIGRATIONS / name).read_text(encoding='utf-8'))
    db.close()
    Store(tmp_path / 'inline.db').close()
    assert schema_of(tmp_path / 'sql.db') == schema_of(tmp_path / 'inline.db')


def test_session_list_uses_index_not_samples(tmp_path):
    store = Store(tmp_path / 'db')
    try:
        plan = ' '.join(str(r['detail']) for r in store.query('EXPLAIN QUERY PLAN SELECT id,started,status FROM sessions ORDER BY started DESC LIMIT 200'))
        assert 'USING INDEX session_started' in plan and 'samples' not in plan and 'TEMP B-TREE' not in plan
        for sql in ('SELECT * FROM sessions WHERE (1 OR archived_at IS NULL) ORDER BY started DESC LIMIT 200',):
            plan = ' '.join(str(r['detail']) for r in store.query('EXPLAIN QUERY PLAN ' + sql))
            assert 'samples' not in plan
    finally:
        store.close()


def test_audit_and_annotation_jobs(tmp_path):
    store = Store(tmp_path / 'db')
    try:
        store.put('session', ('s1', '2026-01-01T00:00:00+00:00', None, 'driving', 'live', '{}', '{}'))
        store.put('audit', ('a1', 100.0, 'user:me', 'race_control', 'raceControl.setFlag', 'yellow', 'abc', 'ok', 'done', 's1'))
        store.put('audit', ('a2', 200.0, 'user:me', 'race_control', 'raceControl.setFlag', 'green', 'def', 'rejected', None, None))
        store.put('audit', ('a1', 999.0, 'x', 'x', 'x', None, None, 'ok', None, None))      # duplicate id ignored
        store.put('annotation', ('s1', '2026-01-01T00:00:05+00:00', json.dumps({'message': 'spin', 'severity': 'warning'}), 'incident'))
        store.put('annotation', ('s1', '2026-01-01T00:00:09+00:00', json.dumps({'message': 'box'}), 'pit'))
        store.put('event', ('s1', '2026-01-01T00:00:10+00:00', json.dumps({'category': 'fuel'})))
        store.flush()
        assert [r['id'] for r in store.audit()] == ['a2', 'a1']
        assert [r['id'] for r in store.audit(session='s1')] == ['a1']
        assert [r['id'] for r in store.audit(since=150)] == ['a2']
        assert [r['id'] for r in store.audit(limit=1)] == ['a2']
        assert [a['kind'] for a in store.annotations('s1')] == ['incident', 'pit']
        assert [a['message'] for a in store.annotations('s1', kinds=['pit'])] == ['box']
        assert len(store.annotations('s1', limit=1)) == 1
        assert len(store.detail('s1')['events']) == 3          # detail still lists every event
    finally:
        store.close()


def test_bounded_queue_semantics_unchanged(tmp_path):
    store = Store(tmp_path / 'db', capacity=1)
    try:
        import threading
        gate = threading.Event()
        store.q.put(('barrier', gate, 0))               # occupy the queue while the writer may still be idle
        results = [store.put('audit', ('x%d' % i, 1.0, 'a', 'c', 'c', None, None, 'ok', None, None)) for i in range(50)]
        assert store.drops == results.count(False)      # drop-new with explicit accounting
    finally:
        store.close()
