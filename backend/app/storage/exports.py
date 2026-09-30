"""Export formats and import handlers as registries.

Exports write to a binary stream from a session repository (or a bare Store). The `bundle_v1` format
wraps `exporting.export_bundle` unchanged, so existing bundles stay byte-compatible in semantics.
Imports validate size, structure, checksums and schema; nothing is ever unpickled or evaluated.
"""
import csv
import io
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable

from .. import exporting
from ..core import defaults
from ..core.errors import AppError, ResultCode
from ..core.registry import Registry
from ..telemetry import FIELDS
from .repositories import SqliteSessionRepository

SUPPORTS = ('session', 'lap', 'group')
DEFAULT_CSV_CHANNELS = ('packet_id', 'lap', 'speed_kmh', 'rpm', 'fuel', 'throttle', 'brake')
UNITS = {name: unit for name, _o, _f, unit, _v in FIELDS} | {'speed_kmh': 'km/h', 'throttle': 'ratio', 'brake': 'ratio'}


def _repo(source: Any) -> SqliteSessionRepository:
    return source if isinstance(source, SqliteSessionRepository) else SqliteSessionRepository(source)


@dataclass(frozen=True)
class ExportFormat:
    id: str
    name: str
    extension: str
    supports: tuple[str, ...]
    write: Callable[[Any, str, BinaryIO, dict], None]
    media_type: str = 'application/octet-stream'


EXPORT_FORMATS: Registry[ExportFormat] = Registry('export_formats', public=lambda f: {
    'id': f.id, 'name': f.name, 'extension': f.extension, 'supports': list(f.supports), 'media_type': f.media_type})


def export_session(source: Any, sid: str, format_id: str, stream: BinaryIO, options: dict | None = None) -> None:
    fmt = EXPORT_FORMATS.get(format_id)
    if fmt is None:
        raise AppError(ResultCode.NOT_FOUND, 404, f'Unknown export format {format_id}')
    fmt.write(source, sid, stream, dict(options or {}))


def _require_detail(repo: SqliteSessionRepository, sid: str) -> None:
    if repo.get(sid) is None:
        raise AppError(ResultCode.NOT_FOUND, 404, 'Unknown session')


def _iter_samples(repo: SqliteSessionRepository, sid: str, options: dict, channels=None):
    cursor = None
    while True:
        page = repo.samples(sid, after=cursor, lap_id=options.get('lap_id'), channels=channels)
        yield from page.items
        cursor = page.next_cursor
        if cursor is None:
            return


def _write_bundle_v1(source: Any, sid: str, stream: BinaryIO, options: dict) -> None:
    repo = _repo(source)
    with tempfile.TemporaryDirectory() as tmp:
        path = exporting.export_bundle(repo.store, sid, tmp)
        with open(path, 'rb') as f:
            shutil.copyfileobj(f, stream)


def _write_csv(source: Any, sid: str, stream: BinaryIO, options: dict) -> None:
    repo = _repo(source)
    _require_detail(repo, sid)
    channels = list(options.get('channels') or DEFAULT_CSV_CHANNELS)
    text = io.TextIOWrapper(stream, encoding='utf-8', newline='', write_through=True)
    try:
        writer = csv.writer(text)
        writer.writerow(['utc', 'mono_s'] + [f'{c} [{UNITS[c]}]' if c in UNITS else c for c in channels])
        for row in _iter_samples(repo, sid, options, channels):
            cells = [row.values.get(c) for c in channels]
            cells = [json.dumps(c) if isinstance(c, (list, dict)) else c for c in cells]
            writer.writerow([exporting.safe_cell(row.utc), row.mono] + [exporting.safe_cell(c) for c in cells])
    finally:
        text.detach()


def _write_jsonl(source: Any, sid: str, stream: BinaryIO, options: dict) -> None:
    repo = _repo(source)
    _require_detail(repo, sid)
    channels = options.get('channels')
    if channels:                                   # projection: only the requested channels
        for row in _iter_samples(repo, sid, options, list(channels)):
            stream.write((json.dumps(row.to_public()) + '\n').encode('utf-8'))
        return
    cursor, lap_id = 0, options.get('lap_id')      # full fidelity: the stored payloads, as the bundle writes them
    while True:
        rows = repo.store.samples(sid, -1e30, 10000, cursor)
        if not rows:
            return
        for r in rows:
            if lap_id is None or r.get('lap_id') == lap_id:
                stream.write((json.dumps(r) + '\n').encode('utf-8'))
        cursor = rows[-1]['record_id']


def _write_html_report(source: Any, sid: str, stream: BinaryIO, options: dict) -> None:
    detail = _repo(source).store.detail(sid)
    if detail is None:
        raise AppError(ResultCode.NOT_FOUND, 404, 'Unknown session')
    stream.write(exporting.report_html(detail).encode('utf-8'))


EXPORT_FORMATS.register(ExportFormat('bundle_v1', 'Session bundle (zip)', '.zip', ('session',), _write_bundle_v1, 'application/zip'))
EXPORT_FORMATS.register(ExportFormat('csv', 'Telemetry CSV', '.csv', ('session', 'lap'), _write_csv, 'text/csv'))
EXPORT_FORMATS.register(ExportFormat('jsonl', 'Samples JSONL', '.jsonl', ('session', 'lap'), _write_jsonl, 'application/x-ndjson'))
EXPORT_FORMATS.register(ExportFormat('html_report', 'HTML report', '.html', ('session',), _write_html_report, 'text/html'))


# ---- imports -----------------------------------------------------------------------------------------
class ImportRejected(ValueError):
    """A file failed validation. The message is safe to show the user."""


@dataclass(slots=True)
class ImportResult:
    handler: str
    schema: int
    metadata: dict
    rows: list[dict]
    compatible: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImportHandler:
    id: str
    name: str
    extensions: tuple[str, ...]
    schema_versions: tuple[int, ...]
    sniff: Callable[[bytes], bool]
    validate: Callable[[bytes], ImportResult]


IMPORT_HANDLERS: Registry[ImportHandler] = Registry('import_handlers', public=lambda h: {
    'id': h.id, 'name': h.name, 'extensions': list(h.extensions), 'schema_versions': list(h.schema_versions)})


def _validate_bundle_v1(data: bytes) -> ImportResult:
    try:
        metadata, rows = exporting.inspect_bundle(data)      # size, paths, checksums, schema, per-sample validation
    except ImportRejected:
        raise
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        raise ImportRejected(str(error) or 'Invalid bundle') from error
    return ImportResult('bundle_v1', int(metadata['schema']), metadata, rows)


IMPORT_HANDLERS.register(ImportHandler('bundle_v1', 'Session bundle (zip)', ('.zip',), (1,),
                                       lambda data: data[:4] == b'PK\x03\x04', _validate_bundle_v1))


def import_session_file(data: bytes, handler_id: str | None = None) -> ImportResult:
    """Validate `data` with the named handler, or the first handler whose sniffer accepts it."""
    if len(data) > defaults.IMPORT_MAX_BYTES:
        raise ImportRejected(f'Import exceeds {defaults.IMPORT_MAX_BYTES // (1024 * 1024)} MiB')
    handler = IMPORT_HANDLERS.get(handler_id) if handler_id else next((h for h in IMPORT_HANDLERS if h.sniff(data)), None)
    if handler is None:
        raise ImportRejected('Unrecognised import format')
    result = handler.validate(data)
    if result.schema not in handler.schema_versions:
        raise ImportRejected('Unsupported schema')
    return result
