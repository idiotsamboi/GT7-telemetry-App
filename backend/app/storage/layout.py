"""The data directory map. One place that names every file/folder under the data root.

This mirrors what the existing modules create (Config, Store, TrackMap, TrackModelStore,
TrainingRecorder, LeagueAssets, ...); tests assert the two never drift. It changes no behaviour.
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    key: str
    rel: str
    kind: str           # 'file' | 'dir'
    contains: str
    sensitive: bool = False
    created_by: str = ''
    ensured: bool = False     # ensure() creates it (directories only; files are written by their owners)


ENTRIES: tuple[Entry, ...] = (
    Entry('settings', 'settings.json', 'file', 'User settings (validated, migrated, with .bak copies alongside)', True, 'config.Config'),
    Entry('control_token', 'control-token', 'file', 'Browser pairing token for the local control API', True, 'config.Config'),
    Entry('database', 'telemetry.sqlite3', 'file', 'Sessions, laps, samples, events, audit log, group tables (WAL files alongside)', True, 'storage.Store'),
    Entry('track_maps', 'track-maps', 'dir', 'Legacy learned track maps and candidates', False, 'tracks.TrackMap', True),
    Entry('corpus', 'track-maps/_corpus.jsonl', 'file', 'Bounded anonymous track-point corpus for offline model building', False, 'tracks.TrackMap'),
    Entry('track_models', 'track-models', 'dir', 'User track world models overlaying the bundled catalogue', False, 'track_store.TrackModelStore', True),
    Entry('track_models_user', 'track-models-user', 'dir', 'Optional locally installed schema-3 world models (read-only extension point)', False, 'track_catalogue'),
    Entry('track_training', 'track-training', 'dir', 'Track training laps recorded for model fusion', False, 'training.TrainingRecorder', True),
    Entry('league_assets', 'league-assets', 'dir', 'Uploaded league logos and graphics', False, 'group.assets', True),
    Entry('exports', 'exports', 'dir', 'Session export bundles (zip)', True, 'api', True),
    Entry('logs', 'logs', 'dir', 'Rotating JSONL application logs (redacted)', False, 'core.logging_setup', True),
    Entry('analysis_cache', 'cache/analysis', 'dir', 'Disposable analysis results; safe to delete', False, 'analysis_cache', True),
    Entry('safe_database', 'telemetry-safe.sqlite3', 'file', 'Fallback database used when the main one cannot be opened (safe mode)', True, 'api.create_app'),
    Entry('settings_backups', 'settings.v*.bak.json', 'file', 'Copies of settings.json taken before a schema migration (newest 3 kept)', True, 'core.config_migrations'),
    Entry('settings_invalid', 'settings.invalid-*.json', 'file', 'Settings files that failed validation, preserved for inspection (newest 5 kept)', True, 'config.Config'),
    Entry('running_marker', '.running', 'file', 'Present while the app runs; found at start-up = unclean shutdown', False, 'storage.layout'),
)
_BY_KEY = {e.key: e for e in ENTRIES}


class DataLayout:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path(self, key: str) -> Path:
        return self.root / _BY_KEY[key].rel

    settings = property(lambda self: self.path('settings'))
    control_token = property(lambda self: self.path('control_token'))
    database = property(lambda self: self.path('database'))
    track_maps = property(lambda self: self.path('track_maps'))
    corpus = property(lambda self: self.path('corpus'))
    track_models = property(lambda self: self.path('track_models'))
    track_models_user = property(lambda self: self.path('track_models_user'))
    track_training = property(lambda self: self.path('track_training'))
    league_assets = property(lambda self: self.path('league_assets'))
    exports = property(lambda self: self.path('exports'))
    logs = property(lambda self: self.path('logs'))
    analysis_cache = property(lambda self: self.path('analysis_cache'))
    running_marker = property(lambda self: self.path('running_marker'))

    def ensure(self) -> 'DataLayout':
        """Create the standard directories. Never creates anything outside the root, never writes files."""
        root = self.root.resolve()
        for entry in ENTRIES:
            if entry.kind == 'dir' and entry.ensured:
                target = self.path(entry.key)
                if root not in target.resolve().parents:
                    raise ValueError(f'{entry.key} would be created outside the data root')
                target.mkdir(parents=True, exist_ok=True)
        return self

    def mark_running(self) -> bool:
        """Write the marker; returns True if one was already there (the previous run did not shut down cleanly)."""
        unclean = self.running_marker.exists()
        self.root.mkdir(parents=True, exist_ok=True)
        self.running_marker.write_text('running', encoding='utf-8')
        return unclean

    def clear_running(self) -> None:
        self.running_marker.unlink(missing_ok=True)

    def describe(self) -> dict:
        """JSON-safe table for docs and /api/storage. Paths are relative to the data root (no absolute paths leak)."""
        rows = []
        for e in ENTRIES:
            target = self.path(e.key)
            rows.append({'key': e.key, 'kind': e.kind, 'path': e.rel, 'contains': e.contains, 'sensitive': e.sensitive,
                         'created_by': e.created_by, 'exists': any(self.root.glob(e.rel)) if '*' in e.rel else target.exists()})
        return {'root_name': self.root.name, 'entries': rows}
