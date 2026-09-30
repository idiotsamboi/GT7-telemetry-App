"""Feature flags. Storage is Settings.feature_flags (plus legacy settings that already exist)."""
from dataclasses import dataclass
from typing import Literal

from .registry import Registry


@dataclass(frozen=True)
class FeatureFlag:
    id: str
    description: str
    default: bool
    stage: Literal['experimental', 'beta', 'stable']
    requires_restart: bool = False
    legacy_setting: str | None = None    # existing Settings field that already stores this flag


FEATURES: Registry[FeatureFlag] = Registry('features')
for _f in (
    FeatureFlag('gamification', 'Local evidence-backed Driver Career (foundation)', True, 'beta'),
    FeatureFlag('driver_progression', 'Persist eligible session rewards and consistency skill evidence', True, 'beta'),
    FeatureFlag('track_mastery', 'Car-specific track learning and personal reference history', True, 'beta'),
    FeatureFlag('corner_mastery', 'Evidence-backed corner repeatability and personal segment history', True, 'beta'),
    FeatureFlag('dynamic_challenges', 'Measurable local challenges from comparable session evidence', True, 'beta'),
    FeatureFlag('engineer_missions', 'Engineer missions using validated career challenge objectives', True, 'beta'),
    FeatureFlag('packet_c_interpretations', 'Interpret undocumented packet-C fields (current_ms, wheel_steering)', False, 'experimental', legacy_setting='trust_c_fields'),
    FeatureFlag('v3_track_authority', 'Use the v3 track service as the authority for track identity', True, 'beta'),
    FeatureFlag('battle_index', 'Battle index between connected drivers', True, 'beta'),
    FeatureFlag('net_order_projection', 'Projected net order after pit-loss', True, 'beta'),
    FeatureFlag('steward_auto_cues', 'Automatic steward cues for race control', True, 'beta'),
    FeatureFlag('spatial_coaching', 'Distance-aligned corner coaching', True, 'beta'),
    FeatureFlag('clean_air_advice', 'Pit-window clean-air advice from shared group traffic', True, 'beta'),
    FeatureFlag('tyre_heat_rate', 'Tyre surface heat-rate monitor', True, 'beta'),
    FeatureFlag('local_ai', 'Local llama-server engineer briefing', False, 'experimental', legacy_setting='local_ai_enabled'),
    FeatureFlag('local_ai_rephrase', 'Local model may rephrase (never invent) engineer answers', False, 'experimental', legacy_setting='local_ai_rephrase'),
    FeatureFlag('ui_redesign_shell', 'New workspace shell', True, 'beta'),
):
    FEATURES.register(_f)


def is_enabled(flag_id: str, settings, *, safe_mode: bool = False) -> bool:
    """`settings` is duck-typed (Settings). Legacy settings keep their own storage so nothing migrates silently.
    Safe mode switches every experimental flag off without touching the stored settings."""
    flag = FEATURES.require(flag_id)
    if safe_mode and flag.stage == 'experimental':
        return False
    if flag.legacy_setting and hasattr(settings, flag.legacy_setting):
        return bool(getattr(settings, flag.legacy_setting))
    overrides = getattr(settings, 'feature_flags', None) or {}
    return bool(overrides.get(flag_id, flag.default))


def snapshot(settings, *, safe_mode: bool = False) -> list[dict]:
    return [{'id': f.id, 'description': f.description, 'stage': f.stage, 'default': f.default,
             'requires_restart': f.requires_restart, 'enabled': is_enabled(f.id, settings, safe_mode=safe_mode)} for f in FEATURES]
