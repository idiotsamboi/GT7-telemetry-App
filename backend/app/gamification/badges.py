"""Data-driven driver badges (F006), each earned badge backed by stored source evidence.

Sources: career_achievements (lap-count badges), career level, career_events PB_SET, and
eligible career_scorecards (session grade S). Everything is CALCULATED, live-career only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

PROVENANCE = 'CALCULATED'


@dataclass(frozen=True, slots=True)
class BadgeDef:
    id: str
    name: str
    icon: str
    kind: str        # achievement | level | first_pb | grade_s
    threshold: int
    description: str


BADGES: tuple[BadgeDef, ...] = (
    BadgeDef('FIRST_LAP', 'First Step', 'flag', 'achievement', 1, 'First comparable lap'),
    BadgeDef('TEN_LAPS', 'Getting Dialed', 'disc', 'achievement', 10, 'Ten comparable laps'),
    BadgeDef('ONE_HUNDRED_LAPS', 'Century Driver', 'award', 'achievement', 100, 'One hundred comparable laps'),
    BadgeDef('THOUSAND_LAPS', 'Marathoner', 'trophy', 'achievement', 1000, 'One thousand comparable laps'),
    BadgeDef('LEVEL_5', 'Rising Driver', 'star', 'level', 5, 'Reach career level 5'),
    BadgeDef('LEVEL_10', 'Seasoned Driver', 'star', 'level', 10, 'Reach career level 10'),
    BadgeDef('LEVEL_25', 'Veteran Driver', 'star', 'level', 25, 'Reach career level 25'),
    BadgeDef('FIRST_PB', 'Personal Best', 'zap', 'first_pb', 1, 'First application-recorded personal best'),
    BadgeDef('CONSISTENCY_S', 'Metronome', 'target', 'grade_s', 1, 'A session with application consistency grade S'),
)
assert len({b.id for b in BADGES}) == len(BADGES)


def _facts(store, driver_id: str, level: int, comparable_laps: int) -> dict:
    achievements = {r['definition_id']: r for r in store.query(
        'SELECT definition_id,earned_at,source_id,evidence FROM career_achievements WHERE driver_id=? LIMIT 200', (driver_id,))}
    pb = store.query("SELECT id,created_at,source_id,evidence FROM career_events WHERE driver_id=? AND kind='PB_SET' ORDER BY created_at,id LIMIT 1", (driver_id,))
    level_events = store.query("SELECT created_at,source_id,json_extract(evidence,'$.to') AS lvl FROM career_events WHERE driver_id=? AND kind='LEVEL_UP' ORDER BY created_at,id LIMIT 100", (driver_id,))
    grade = store.query("SELECT session_id,created_at,json_extract(payload,'$.evidence.consistency_score') AS score FROM career_scorecards "
                        "WHERE driver_id=? AND status='eligible' AND json_extract(payload,'$.evidence.session_grade')='S' ORDER BY created_at LIMIT 1", (driver_id,))
    return dict(achievements=achievements, pb=pb[0] if pb else None, level_events=level_events, grade=grade[0] if grade else None,
                level=level, comparable_laps=comparable_laps)


def evaluate_badge(b: BadgeDef, f: dict) -> dict:
    out = dict(id=b.id, name=b.name, icon=b.icon, description=b.description, unlocked=False, earned_at=None,
               progress=None, evidence=None)
    if b.kind == 'achievement':
        row = f['achievements'].get(b.id)
        out['progress'] = dict(current=min(f['comparable_laps'], b.threshold), target=b.threshold)
        if row:
            out.update(unlocked=True, earned_at=row['earned_at'],
                       evidence=dict(provenance=PROVENANCE, source='career_achievements', source_id=row['source_id'], detail=json.loads(row['evidence'])))
    elif b.kind == 'level':
        out['progress'] = dict(current=min(f['level'], b.threshold), target=b.threshold)
        if f['level'] >= b.threshold:
            ev = next((e for e in f['level_events'] if (e['lvl'] or 0) >= b.threshold), None)
            out.update(unlocked=True, earned_at=ev['created_at'] if ev else None,
                       evidence=dict(provenance=PROVENANCE, source='career_events' if ev else 'career_profiles',
                                     source_id=ev['source_id'] if ev else None, level=f['level']))
    elif b.kind == 'first_pb':
        out['progress'] = dict(current=int(bool(f['pb'])), target=1)
        if f['pb']:
            out.update(unlocked=True, earned_at=f['pb']['created_at'],
                       evidence=dict(provenance=PROVENANCE, source='career_events', source_id=f['pb']['source_id'], event_id=f['pb']['id'],
                                     detail=json.loads(f['pb']['evidence'])))
    elif b.kind == 'grade_s':
        out['progress'] = dict(current=int(bool(f['grade'])), target=1)
        if f['grade']:
            out.update(unlocked=True, earned_at=f['grade']['created_at'],
                       evidence=dict(provenance=PROVENANCE, source='career_scorecards', session_id=f['grade']['session_id'],
                                     consistency_score=f['grade']['score']))
    t = out['progress']['target']
    out['progress']['fraction'] = round(min(1.0, out['progress']['current'] / t), 4) if t else 1.0
    return out


def list_badges(store, driver_id: str, level: int, comparable_laps: int) -> list[dict]:
    f = _facts(store, driver_id, level, comparable_laps)
    return [evaluate_badge(b, f) for b in BADGES]
