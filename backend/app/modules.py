"""The module list: existing features registered as modules (composition metadata, not a plugin API).

A new feature is one `ModuleDef` here plus its own files. The runtime composition (`runtime_services.build_services`)
creates the services; commands come from `commands_catalog`; channels from `telemetry.frame/derived`; rules from
`engineer.RULE_SPECS`. This registry lets the shell, docs and diagnostics discover what exists.
No dynamic loading of third-party code.
"""
from . import commands_catalog  # noqa: F401  (registers the command catalogue)
from .core.commands import COMMANDS
from .core.modules import MODULES, ModuleDef


def _commands(*prefixes: str) -> tuple[str, ...]:
    return tuple(c.id for c in COMMANDS if any(c.id.startswith(p) for p in prefixes))


for _m in (
    ModuleDef('telemetry', 'Telemetry', 'UDP receiver, parser, bus, channels, sources',
              services=('telemetry_receiver', 'diagnostics'), commands=_commands('source.'),
              capabilities=('telemetry.viewOwn',), settings_fields=('ps5_ip', 'udp_bind', 'udp_port', 'remote_port', 'variant', 'heartbeat', 'stale_seconds', 'raw_capture', 'trust_c_fields'),
              feature_flag='packet_c_interpretations'),
    ModuleDef('sessions', 'Sessions & recording', 'Lap segmentation, recorder, replay, export/import, retention',
              services=('recorder',), commands=_commands('session.', 'sessions.'), capabilities=('sessions.manage', 'sessions.purge'),
              settings_fields=('retention_days', 'reserve_l', 'race_laps', 'race_minutes', 'target_ms')),
    ModuleDef('engineer', 'Race engineer', 'Alert rules, speech scheduler, intent catalogue',
              services=('engine',), commands=_commands('engineer.', 'alerts.'), capabilities=('local.admin',),
              rules=('low_fuel', 'fuel_critical', 'tyre_hot', 'tyre_imbalance', 'limiter', 'handbrake', 'off_surface', 'pedal_overlap', 'pit_speed', 'tyre_heat_rate'),
              settings_fields=('mode', 'speech_gap', 'speech_per_min', 'low_fuel_l', 'tyre_limit_c', 'alert_cooldown')),
    ModuleDef('voice', 'Voice', 'Microphone worker, speech recognition grammar, text-to-speech',
              services=('microphone',), commands=_commands('audio.'),
              settings_fields=('hands_free', 'vosk_model', 'input_device', 'output_device', 'tts', 'voice', 'voice_volume', 'retain_transcripts')),
    ModuleDef('local_ai', 'Local AI', 'llama-server evidence selection / rephrase guard', services=('local_ai',),
              feature_flag='local_ai', settings_fields=('local_ai_enabled', 'local_ai_model', 'local_ai_binary', 'local_ai_port', 'local_ai_rephrase')),
    ModuleDef('tracks', 'Tracks', 'Track identity, maps, recognition (v3 authority, legacy map store)',
              services=('track',), commands=_commands('track.'), feature_flag='v3_track_authority',
              settings_fields=('track_id', 'track', 'layout', 'direction')),
    ModuleDef('training', 'Training', 'Track-capture training laps; achievements/challenges definitions',
              commands=_commands('training.')),
    ModuleDef('group_race_control', 'Race Control', 'Groups, admission, flags, messages, steward decisions, battles',
              services=('group_host', 'group_client'), commands=_commands('group.', 'raceControl.'),
              capabilities=('raceControl.setFlag', 'raceControl.message', 'raceControl.steward', 'raceControl.session', 'raceControl.admit', 'telemetry.publishOwn', 'driver.respond'),
              feature_flag='steward_auto_cues'),
    ModuleDef('broadcast_graphics', 'Broadcast graphics', 'Workspaces, program output, overlays, league branding',
              services=('overlay_output',), commands=_commands('graphics.', 'branding.'),
              capabilities=('graphics.view', 'graphics.edit', 'graphics.take', 'graphics.issueOutput', 'branding.edit', 'overlay.read')),
    ModuleDef('strategy', 'Strategy', 'Fuel scenarios, clean-air pit advice, net-order projection',
              feature_flag='clean_air_advice', settings_fields=('max_save_percent', 'pit_loss_s', 'refuel_rate_lps', 'fuel_time_slope_s_per_l')),
    ModuleDef('coaching', 'Coaching', 'Distance-aligned corner coaching and tyre heat-rate',
              feature_flag='spatial_coaching', settings_fields=('coaching_min_loss_s', 'tyre_heat_rate_c_s', 'tyre_heat_anomaly_c')),
):
    MODULES.register(_m)
