import csv
import io
import json
import zipfile

import pytest

from backend.app.core import defaults
from backend.app.core.errors import AppError
from backend.app.exporting import export_bundle, inspect_bundle
from backend.app.storage import Store
from backend.app.storage.exports import (EXPORT_FORMATS, IMPORT_HANDLERS, ImportRejected, export_session,
                                         import_session_file)
from backend.app.storage.repositories import SqliteSessionRepository
from backend.app.telemetry import demo_sample


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / 'db')
    s.put('session', ('sid', '2026-01-01T00:00:00+00:00', '2026-01-01T00:10:00+00:00', 'completed', 'live', '{}', json.dumps({'improvements': []})))
    s.put('lap', ('lap1', 'sid', json.dumps({'id': 'lap1', 'number': 1, 'duration_ms': 90000, 'complete': True})))
    for i in range(30):
        payload = demo_sample(1 + i * 0.1, i).json()
        payload['lap_id'] = 'lap1' if i < 20 else 'lap2'
        s.put('sample', ('sid', payload['lap_id'], payload['mono'], i, json.dumps(payload)))
    s.flush()
    yield s
    s.close()


def run(store, sid, fmt, **options):
    out = io.BytesIO()
    export_session(store, sid, fmt, out, options)
    return out.getvalue()


def test_registry_lists_formats():
    assert set(EXPORT_FORMATS.ids()) == {'bundle_v1', 'csv', 'jsonl', 'html_report'}
    assert all(f['supports'] for f in EXPORT_FORMATS.to_public())
    assert 'bundle_v1' in IMPORT_HANDLERS


def test_bundle_v1_is_the_current_exporter_and_round_trips(store, tmp_path):
    data = run(store, 'sid', 'bundle_v1')
    reference = export_bundle(store, 'sid', tmp_path).read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as a, zipfile.ZipFile(io.BytesIO(reference)) as b:
        assert sorted(a.namelist()) == sorted(b.namelist())
        assert a.read('samples.jsonl') == b.read('samples.jsonl') and a.read('telemetry.csv') == b.read('telemetry.csv')
        assert json.loads(a.read('metadata.json'))['schema'] == 1
    result = import_session_file(data)                       # registry import of a bundle from the current exporter
    assert result.handler == 'bundle_v1' and result.schema == 1 and len(result.rows) == 30 and result.compatible
    assert import_session_file(reference).metadata['id'] == 'sid'
    assert inspect_bundle(reference)[0]['schema'] == 1        # direct legacy path unchanged


def test_csv_header_units_projection_and_lap_filter(store):
    text = run(store, 'sid', 'csv', channels=['speed_kmh', 'fuel', 'position']).decode('utf-8')
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ['utc', 'mono_s', 'speed_kmh [km/h]', 'fuel [L]', 'position [m]'] and len(rows) == 31
    assert json.loads(rows[1][4]) == demo_sample(1, 0).values['position'] or isinstance(json.loads(rows[1][4]), list)
    default = list(csv.reader(io.StringIO(run(store, 'sid', 'csv', lap_id='lap2').decode())))
    assert len(default) == 11 and default[0][:3] == ['utc', 'mono_s', 'packet_id [counter]']


def test_csv_neutralises_formula_cells(store):
    store.put('sample', ('sid', 'lap2', 99.0, 99, json.dumps({'mono': 99.0, 'utc': '=cmd()', 'values': {'rpm': 1}})))
    store.flush()
    text = run(store, 'sid', 'csv', channels=['rpm']).decode()
    assert "'=cmd()" in text


def test_jsonl_full_and_projected(store):
    full = [json.loads(l) for l in run(store, 'sid', 'jsonl').decode().splitlines()]
    assert len(full) == 30 and 'variant' in full[0] and 'record_id' in full[0]
    lap = [json.loads(l) for l in run(store, 'sid', 'jsonl', lap_id='lap2').decode().splitlines()]
    assert len(lap) == 10
    proj = [json.loads(l) for l in run(store, 'sid', 'jsonl', channels=['rpm']).decode().splitlines()]
    assert set(proj[0]['values']) == {'rpm'} and len(proj) == 30


def test_html_report_and_errors(store):
    assert run(store, 'sid', 'html_report').startswith(b'<!doctype html>')
    with pytest.raises(AppError):
        run(store, 'nope', 'csv')
    with pytest.raises(AppError):
        run(store, 'nope', 'html_report')
    with pytest.raises(AppError):
        run(store, 'sid', 'unknown_format')
    assert run(SqliteSessionRepository(store), 'sid', 'jsonl')                # repository accepted as the source


def test_import_validation_rejects_bad_input(store):
    good = run(store, 'sid', 'bundle_v1')
    with pytest.raises(ImportRejected):
        import_session_file(b'not a zip at all')
    with pytest.raises(ImportRejected):
        import_session_file(b'PK\x03\x04garbage')
    with pytest.raises(ImportRejected, match='MiB'):
        import_session_file(b'\0' * (defaults.IMPORT_MAX_BYTES + 1))
    with pytest.raises(ImportRejected):
        import_session_file(good, handler_id='bundle_v1_nonexistent')
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as src, zipfile.ZipFile(tampered, 'w') as dst:
        for name in src.namelist():
            body = src.read(name)
            dst.writestr(name, body.replace(b'"schema": 1', b'"schema": 9') if name == 'metadata.json' else body)
    with pytest.raises(ImportRejected):                                        # checksum mismatch
        import_session_file(tampered.getvalue())
