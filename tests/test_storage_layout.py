import json
from pathlib import Path

import pytest

from backend.app.config import Config
from backend.app.storage import Store
from backend.app.storage.layout import DataLayout, ENTRIES
from backend.app.track_store import TrackModelStore
from backend.app.tracks import TrackMap
from backend.app.training import TrainingRecorder

APP = Path(__file__).resolve().parents[1] / 'backend' / 'app'


def test_layout_matches_what_modules_create(tmp_path):
    layout = DataLayout(tmp_path)
    config = Config(tmp_path)
    assert config.path == layout.settings          # written on first save, not at construction
    store = Store(layout.database)
    store.close()
    TrackMap(tmp_path)
    TrainingRecorder(tmp_path)
    TrackModelStore(tmp_path, set())
    for key in ('control_token', 'database', 'track_maps', 'track_models', 'track_training'):
        assert layout.path(key).exists(), key
    assert layout.corpus.parent == layout.track_maps and layout.corpus.name == '_corpus.jsonl'
    # names the modules use as string literals (kept in sync with the map)
    assert "'league-assets'" in (APP / 'group' / 'assets.py').read_text(encoding='utf-8')
    assert "'exports'" in (APP / 'api.py').read_text(encoding='utf-8')
    assert 'track-models-user' in (APP / 'track_catalogue.py').read_text(encoding='utf-8')
    assert 'track-maps' in (APP / 'track_store.py').read_text(encoding='utf-8')     # legacy root is the same folder


def test_ensure_creates_only_dirs_inside_root(tmp_path):
    root = tmp_path / 'data'
    layout = DataLayout(root).ensure()
    for key in ('track_maps', 'track_models', 'track_training', 'league_assets', 'exports', 'logs', 'analysis_cache'):
        assert layout.path(key).is_dir()
    assert not layout.settings.exists() and not layout.database.exists() and not layout.control_token.exists()
    assert not layout.track_models_user.exists()            # read-only extension point is never created
    assert {p.name for p in tmp_path.iterdir()} == {'data'}
    DataLayout(root).ensure()                                # idempotent


def test_describe_is_json_safe_and_relative(tmp_path):
    table = DataLayout(tmp_path).ensure().describe()
    text = json.dumps(table)
    assert str(tmp_path) not in text
    by_key = {e['key']: e for e in table['entries']}
    assert len(by_key) == len(ENTRIES)
    assert by_key['control_token']['sensitive'] and by_key['control_token']['kind'] == 'file'
    assert by_key['analysis_cache']['path'] == 'cache/analysis' and by_key['analysis_cache']['exists']
    assert not by_key['track_maps']['sensitive']


def test_running_marker(tmp_path):
    layout = DataLayout(tmp_path)
    assert layout.mark_running() is False
    assert layout.mark_running() is True                     # previous run never cleared it
    layout.clear_running()
    assert layout.mark_running() is False
