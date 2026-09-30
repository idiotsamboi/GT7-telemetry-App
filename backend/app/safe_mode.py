"""Safe mode and crash detection.

Safe mode starts when: `--safe-mode` / GT7_SAFE_MODE=1; the previous run did not shut down cleanly and
`safe_mode_on_crash` is on; or startup stage 2-4 (settings, logging, storage) failed.

In safe mode: experimental feature flags are off; the microphone and local AI are not started; the
receiver binds its port but sends no heartbeat until the user confirms (`leave_safe_mode`).
Group hosting / the group client never auto-start (they are user-initiated), so nothing to suppress there.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

REASONS = {
    'forced': 'Started with --safe-mode.',
    'unclean_shutdown': 'The previous session did not shut down cleanly.',
    'settings_invalid': 'The settings file was invalid; safe defaults were loaded.',
    'storage_failed': 'The recordings database could not be opened; a temporary database is in use.',
}


@dataclass(slots=True)
class SafeMode:
    reason: str
    since: float = field(default_factory=time.time)
    detail: str = ''

    def to_public(self) -> dict:
        return {'active': True, 'reason': self.reason, 'message': REASONS.get(self.reason, self.reason),
                'detail': self.detail, 'since': self.since}


class RunMarker:
    """`data/.running`: written at start, removed at clean stop. Present at boot => the last run crashed."""

    def __init__(self, root: Path):
        self.path = Path(root) / '.running'

    def dirty(self) -> bool:
        return self.path.exists()

    def write(self) -> None:
        try:
            self.path.write_text(str(time.time()), encoding='utf-8')
        except OSError:
            pass                        # a read-only data dir must not stop the app

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


class SafeModeSettings:
    """Read-only view of Settings with the experimental behaviours off. Consumers that read `trust_c_fields` /
    `local_ai_*` (sessions, rules) get this view while safe mode is on; `Runtime.settings` and settings.json keep the
    user's real choices, so saving settings in safe mode never persists the overrides."""
    OVERRIDES = {'trust_c_fields': False, 'local_ai_enabled': False, 'local_ai_rephrase': False}

    def __init__(self, base):
        object.__setattr__(self, '_base', base)

    def __getattr__(self, name):
        return self.OVERRIDES[name] if name in self.OVERRIDES else getattr(self._base, name)

    def __setattr__(self, name, value):
        raise AttributeError('safe-mode settings view is read-only')

    def model_dump(self, *args, **kwargs):
        data = self._base.model_dump(*args, **kwargs)
        data.update(self.OVERRIDES)
        return data


def decide(*, forced: bool, marker_dirty: bool, safe_mode_on_crash: bool, settings_invalid: bool = False,
           storage_failed: bool = False, detail: str = '') -> SafeMode | None:
    """Priority: explicit request, then startup failures, then crash detection."""
    if forced:
        return SafeMode('forced', detail=detail)
    if storage_failed:
        return SafeMode('storage_failed', detail=detail)
    if settings_invalid:
        return SafeMode('settings_invalid', detail=detail)
    if marker_dirty and safe_mode_on_crash:
        return SafeMode('unclean_shutdown', detail=detail)
    return None
