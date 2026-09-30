"""`GET /api/diagnostics` aggregate and the redacted "copy diagnostics" bundle.

Redaction: no tokens, invitation keys or credentials; IPv4 addresses masked to /24 unless the user opts
in; the data directory and home directory are replaced so no personal paths leak.
"""
import platform
import re
import time
from pathlib import Path

from .core import features
from .core.logging_setup import ERRORS, redact
from .core.version import versions

_IPV4 = re.compile(r'\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b')
_H = r'[0-9a-fA-F]{1,4}'
# full form, or a compressed form containing '::' (so clock times like 04:15:37 are never mistaken for addresses)
_IPV6 = re.compile(rf'(?<![0-9a-zA-Z:])(?:(?:{_H}:){{7}}{_H}|(?:{_H}:){{1,7}}:(?:{_H}(?::{_H}){{0,6}})?|::(?:{_H}:){{0,6}}{_H})(?![0-9a-zA-Z:])')


def mask_ips(text: str) -> str:
    """192.168.1.20 -> 192.168.1.x (keeps the network, drops the host); IPv6 -> <ipv6>. Loopback/unspecified stay readable."""
    def sub(m):
        a, b, c, d = m.groups()
        if a in ('127', '0'):
            return m.group(0)
        return f'{a}.{b}.{c}.x'
    text = _IPV4.sub(sub, text)
    return _IPV6.sub(lambda m: m.group(0) if m.group(0) in ('::', '::1') else '<ipv6>', text)


def path_patterns(paths: list[tuple[str, str]]) -> list[tuple[re.Pattern, str]]:
    """Case-insensitive patterns for every spelling a path takes in logs: native, forward slashes and the doubled
    backslashes that repr()/OSError text produces on Windows. Longest first so `<data>` wins over `<home>`."""
    out = []
    for path, repl in paths:
        if not path:
            continue
        for variant in {path, path.replace('\\', '/'), path.replace('\\', '\\\\'), path.replace('/', '\\')}:
            out.append((re.compile(re.escape(variant), re.I), repl))
    return sorted(out, key=lambda pr: -len(pr[0].pattern))


def _scrub(value, patterns, mask: bool):
    if isinstance(value, dict):
        return {k: _scrub(v, patterns, mask) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, patterns, mask) for v in value]
    if isinstance(value, str):
        for pattern, repl in patterns:
            value = pattern.sub(repl, value)
        return mask_ips(value) if mask else value
    return value


def collect(runtime, config) -> dict:
    """Everything the diagnostics page needs. Read-only, cheap, JSON-safe."""
    health = dict(runtime.health_cache or {})
    store = runtime.store.health()
    group = getattr(runtime, 'group', None)
    bus = getattr(runtime, 'bus', None)
    root = Path(config.root)
    return {
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'versions': versions(getattr(runtime, 'parser_version', '')),
        'platform': {'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(),
                     'performance_profile': runtime.performance_profile},
        'safe_mode': runtime.safe_mode.to_public() if runtime.safe_mode else None,
        'services': runtime.services.public() if hasattr(runtime, 'services') else [],
        'receiver': dict(runtime.receiver, port_owners=runtime.receiver.get('port_owners') or [],
                         sequence=dict(runtime.seq.counts), parse_errors=runtime.parse_errors,
                         pipeline_errors=runtime.pipeline_errors, unexpected_senders=runtime.unexpected,
                         source=runtime.source),
        'bus': bus.metrics_snapshot() if bus is not None and hasattr(bus, 'metrics_snapshot') else None,
        'recorder': {k: store[k] for k in ('queue', 'capacity_samples', 'queue_age_s', 'application_drops', 'failed_rows', 'error', 'written')},
        'storage': {'db_bytes': store['db_bytes'], 'wal_bytes': store['wal_bytes'], 'free_bytes': health.get('free_bytes')},
        'group': {'clients': getattr(group, 'running', False) and runtime.clients or 0,
                  'hosting': bool(getattr(group, 'listener', None)),
                  'recording_drops': getattr(group, 'recording_drops', 0)} if group is not None else None,
        'health': {k: health.get(k) for k in ('rate_hz', 'cpu_percent_one_core', 'peak_rss_bytes', 'thermal_c', 'loop_lag_ms', 'degraded', 'reason')},
        'last_errors': list(ERRORS.ring),
        'features': features.snapshot(config.settings, safe_mode=runtime.safe_mode is not None),
        'settings_summary': {'variant': str(config.settings.variant), 'ui_hz': config.settings.ui_hz,
                             'log_level': config.settings.log_level, 'developer_mode': config.settings.developer_mode,
                             'units': config.settings.units.model_dump()},
        'data_dir': str(root),
    }


def redacted_bundle(runtime, config, *, include_ips: bool = False) -> dict:
    data = collect(runtime, config)
    root = Path(config.root)
    paths = [(str(root.resolve()), '<data>'), (str(root), '<data>'), (str(Path.home()), '<home>')]
    data = redact(data)
    data = _scrub(data, path_patterns(paths), mask=not include_ips)
    data['redaction'] = {'tokens_removed': True, 'ips_masked_to_24': not include_ips, 'paths_replaced': True}
    return data
