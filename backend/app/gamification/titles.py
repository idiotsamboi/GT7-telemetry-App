"""Data-driven driver titles (F005).

Unlock state is a pure function of stored career stats (level, comparable laps, eligible
sessions, earned achievements). All values are CALCULATED application progression, never
official GT7 data. Evaluation has no side effects, so repeated evaluation is idempotent.
"""
from __future__ import annotations

from dataclasses import dataclass

PROVENANCE = 'CALCULATED'
DEFAULT_TITLE_ID = 'novice_driver'
# criteria kind -> stat key in the stats mapping
_KINDS = {'level': 'level', 'comparable_laps': 'comparable_laps', 'eligible_sessions': 'eligible_sessions',
          'achievement': None, 'always': None}


@dataclass(frozen=True, slots=True)
class TitleDef:
    id: str
    name: str
    description: str
    kind: str           # one of _KINDS
    threshold: int      # target value (achievement/always: 1 or 0)
    stage: int          # display ordering / progression stage
    achievement_id: str | None = None


TITLES: tuple[TitleDef, ...] = (
    TitleDef('novice_driver', 'Novice Driver', 'Started driver career', 'always', 0, 1),
    TitleDef('consistent_pacesetter', 'Consistent Pacesetter', 'Completed 5 comparable laps', 'comparable_laps', 5, 2),
    TitleDef('apex_hunter', 'Apex Hunter', 'Completed 100 comparable laps', 'comparable_laps', 100, 3),
    TitleDef('track_master', 'Track Master', 'Reached Level 10 or higher', 'level', 10, 4),
    TitleDef('veteran_racer', 'Veteran Racer', 'Completed 500 comparable laps', 'comparable_laps', 500, 5),
    TitleDef('master_driver', 'Master Driver', 'Reached Level 50 or higher', 'level', 50, 6),
)
BY_ID = {t.id: t for t in TITLES}
assert len(BY_ID) == len(TITLES) and all(t.kind in _KINDS for t in TITLES)


def build_stats(profile: dict, level: int, achievement_ids: set[str]) -> dict:
    return dict(level=int(level), comparable_laps=int(profile.get('comparable_laps') or 0),
                eligible_sessions=int(profile.get('eligible_sessions') or 0), achievements=set(achievement_ids))


def evaluate_title(title: TitleDef, stats: dict) -> dict:
    if title.kind == 'always':
        current, target = 1, 1
    elif title.kind == 'achievement':
        current, target = int(title.achievement_id in stats['achievements']), 1
    else:
        current, target = int(stats[_KINDS[title.kind]]), title.threshold
    unlocked = current >= target
    return dict(id=title.id, name=title.name, description=title.description, stage=title.stage, unlocked=unlocked,
                criteria=dict(kind=title.kind, threshold=target),
                progress=dict(current=min(current, target), target=target, fraction=round(min(1.0, current / target), 4) if target else 1.0),
                evidence=dict(provenance=PROVENANCE, source='career_profiles', criteria_kind=title.kind, observed=current, required=target) if unlocked else None)


def evaluate_titles(stats: dict) -> list[dict]:
    return [evaluate_title(t, stats) for t in TITLES]


def resolve(name_or_id: str) -> TitleDef:
    key = (name_or_id or '').strip().lower()
    match = next((t for t in TITLES if t.id == key or t.name.lower() == key), None)
    if not match:
        raise ValueError('Unknown title')
    return match


def next_title(evaluated: list[dict]) -> dict | None:
    locked = [t for t in evaluated if not t['unlocked']]
    return max(locked, key=lambda t: (t['progress']['fraction'], -t['stage']), default=None)
