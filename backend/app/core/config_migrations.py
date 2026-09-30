"""Settings schema migrations: raw JSON -> migrate -> validate.

Each migration takes the raw dict at version N and returns the dict at version N+1.
Before any migration is written back, the old file is backed up as settings.v{n}.bak.json
(last three kept). Failure handling stays in Config (invalid file preserved, safe defaults).
"""
import json
import shutil
from pathlib import Path
from typing import Callable

from .version import SETTINGS_SCHEMA_VERSION

KEEP_BACKUPS = 3


def m1_to_2(raw: dict) -> dict:
    """v2 adds units/performance/logging/feature flags/dev+safe-mode switches."""
    raw = dict(raw)
    raw.setdefault('units', {'speed': 'kmh', 'temperature': 'C', 'fuel': 'L', 'distance': 'm', 'pressure': 'bar'})
    raw.setdefault('performance_profile', 'AUTO')
    raw.setdefault('log_level', 'INFO')
    raw.setdefault('feature_flags', {})
    raw.setdefault('safe_mode_on_crash', True)
    raw.setdefault('developer_mode', False)
    raw.setdefault('demo_scenario', '')
    raw.setdefault('max_storage_gb', None)
    raw['schema_version'] = 2
    return raw


MIGRATIONS: dict[int, Callable[[dict], dict]] = {1: m1_to_2}
assert set(MIGRATIONS) == set(range(1, SETTINGS_SCHEMA_VERSION)), 'every schema version needs a migration'


class MigrationError(ValueError):
    pass


def migrate(raw: dict) -> tuple[dict, list[int]]:
    """Returns (migrated dict, versions that were applied). Files newer than this build are refused."""
    version = raw.get('schema_version', 1)
    if not isinstance(version, int) or version < 1:
        raise MigrationError(f'invalid schema_version {version!r}')
    if version > SETTINGS_SCHEMA_VERSION:
        raise MigrationError(f'settings were written by a newer version (schema {version} > {SETTINGS_SCHEMA_VERSION})')
    applied = []
    while version < SETTINGS_SCHEMA_VERSION:
        raw = MIGRATIONS[version](raw)
        applied.append(version)
        version = raw['schema_version']
    return raw, applied


def backup_before_migration(path: Path, version: int) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f'settings.v{version}.bak.json')
    shutil.copy2(path, target)
    backups = sorted(path.parent.glob('settings.v*.bak.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[KEEP_BACKUPS:]:
        old.unlink(missing_ok=True)
    return target


def load_raw(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise MigrationError('settings file must contain a JSON object')
    return data
