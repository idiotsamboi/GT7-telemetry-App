"""F020: idempotent track-mastery rewards on discovery-level change.

Runs inside the caller's career transaction (live, eligible sessions only). Ids are deterministic on
driver|layout|car|level, and every call re-checks all levels up to the stored one, so a lost write self-heals
and reprocessing adds nothing. A falling score never removes a reward.
"""
from __future__ import annotations

import hashlib
import json
import logging

from .events import ProgressionEvent, _insert
from .track_components import LEVELS

log = logging.getLogger('gamification')
LEVEL_XP = {'Recognized': 10, 'Learning': 20, 'Familiar': 40, 'Strong': 80, 'Mastered': 150}
CATEGORY = 'TRACK_MASTERY'


def reward_id(driver_id: str, layout_id: str, car_id: int, level: str) -> str:
    return 'trackmastery:' + hashlib.sha256('|'.join((driver_id, layout_id, str(car_id), level)).encode()).hexdigest()[:32]


def apply_track_rewards(db, driver_id: str, source_id: str, session_id: str, payload: dict, stamp: str, provenance: str = 'live') -> int:
    """Returns newly granted XP. Non-live provenance never rewards. Failures are isolated to a savepoint."""
    if provenance != 'live' or not payload or payload.get('mastery_level') not in LEVELS:
        return 0
    layout, car = payload['layout_id'], payload['car_id']
    top = LEVELS.index(payload['mastery_level'])
    db.execute('SAVEPOINT track_rewards')
    try:
        total = 0
        for level in LEVELS[1:top + 1]:
            guard = reward_id(driver_id, layout, car, level)
            evidence = {'layout_id': layout, 'car_id': car, 'level': level, 'mastery_source_id': source_id,
                        'score_observed': payload.get('observed_component_score'), 'confidence': payload.get('confidence'),
                        'lap_count': payload.get('lap_count'), 'provenance': 'CALCULATED'}
            granted = db.execute('INSERT OR IGNORE INTO career_xp_events VALUES(?,?,?,?,?,?,?,?,?)',
                                 (guard, guard, driver_id, session_id, source_id, CATEGORY, LEVEL_XP[level], stamp,
                                  json.dumps(evidence, separators=(',', ':'), allow_nan=False))).rowcount
            if granted:
                total += LEVEL_XP[level]
                _insert(db, ProgressionEvent('MASTERY_CHANGED', driver_id, 'track_mastery', f'{driver_id}|{layout}|{car}|{level}',
                                             'CALCULATED', evidence, f'Track level: {level}',
                                             f'{level} on this layout and car (calculated application progression).',
                                             payload.get('confidence')), stamp)
        db.execute('RELEASE track_rewards')
        return total
    except Exception as error:
        db.execute('ROLLBACK TO track_rewards')
        db.execute('RELEASE track_rewards')
        log.warning('gamification.track_rewards_failed', extra={'event': 'gamification.track_rewards_failed',
                                                                 'details': {'error_type': type(error).__name__}})
        return 0
