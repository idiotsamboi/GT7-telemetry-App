"""PyInstaller collects `backend` with --collect-submodules, so every module must import cleanly on a machine
without the optional dependencies (Vosk, sounddevice, pywebview) and without side effects."""
import importlib
import pkgutil
import subprocess
import sys
from pathlib import Path

import backend

ROOT = Path(__file__).resolve().parents[1]


def all_modules():
    return sorted(m.name for m in pkgutil.walk_packages(backend.__path__, 'backend.'))


def test_every_backend_module_imports():
    failures = {}
    for name in all_modules():
        try:
            importlib.import_module(name)
        except Exception as error:      # noqa: BLE001 - report every failure at once
            failures[name] = f'{type(error).__name__}: {error}'
    assert not failures, failures


def test_new_packages_are_discoverable_by_the_packager():
    names = set(all_modules())
    for expected in ('backend.app.core.commands', 'backend.app.telemetry.bus', 'backend.app.storage.repositories',
                     'backend.app.domain.alerts', 'backend.app.group.protocol', 'backend.app.modules'):
        assert expected in names, expected


def test_packaged_data_files_exist():
    """package-windows.py / package-linux.py --add-data these; a missing source would break the build."""
    for rel in ('backend/migrations/003_annotations_audit.sql', 'backend/app/data/track-models.bundle.json.gz', 'docs/licenses'):
        assert (ROOT / rel).exists(), rel


def test_optional_dependencies_are_not_imported_at_module_load():
    code = ("import sys\nimport backend.app.api, backend.app.runtime, backend.app.commands_catalog, backend.app.modules\n"
            "bad=[m for m in ('vosk','sounddevice','webview','llama_cpp') if m in sys.modules]\nassert not bad, bad\n")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
