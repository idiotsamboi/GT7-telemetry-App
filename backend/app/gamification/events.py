"""Progression event log. Events are derived from committed career state, never from raw samples.

Deterministic ids make double processing a no-op. Only live-provenance sessions create events.
Emission failures are logged and never raised into the career processor.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .notifications import add_notification

log = logging.getLogger('gamification')

KINDS = ('PB_SET', 'LEVEL_UP', 'ACHIEVEMENT_UNLOCKED', 'CHALLENGE_COMPLETED', 'SESSION_ENDED')
_LEVELS = {'PB_SET': 'IMPORTANT', 'LEVEL_UP': 'CRITICAL', 'ACHIEVEMENT_UNLOCKED': 'IMPORTANT',
           'CHALLENGE_COMPLETED': 'IMPORTANT', 'SESSION_ENDED': 'NORMAL'}


def event_id(kind: str, driver_id: str, source: str, source_id: str) -> str:
    return hashlib.sha256('|'.join((kind, driver_id, source, source_id)).encode()).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class ProgressionEvent:
    kind: str
    driver_id: str
    source: str
    source_id: str
    provenance: str
    evidence: dict
    title: str
    body: str
    confidence: float | None = None

    @property
    def id(self) -> str:
        return event_id(self.kind, self.driver_id, self.source, self.source_id)


def _insert(db, event: ProgressionEvent, stamp: str) -> bool:
    if event.kind not in KINDS:
        raise ValueError('Unknown progression event kind')
    cur = db.execute('INSERT OR IGNORE INTO career_events VALUES(?,?,?,?,?,?,?,?,?)', (
        event.id, event.driver_id, event.kind, event.source, event.source_id, event.provenance,
        json.dumps(event.evidence, separators=(',', ':'), allow_nan=False), event.confidence, stamp))
    if not cur.rowcount:
        return False
    add_notification(db, event.id, event.driver_id, _LEVELS[event.kind], event.title, event.body, stamp)
    return True


def build_events(db, scorecard: dict, curve) -> list[ProgressionEvent]:
    """Read committed state for one processed session. Non-eligible/non-live sessions yield no events."""
    if scorecard.get('status') != 'eligible':
        return []
    driver = scorecard['driver_id']
    sid = scorecard['session_id']
    source_id = 'career:v1:' + sid
    row = db.execute('SELECT provenance FROM career_sources WHERE id=?', (source_id,)).fetchone()
    if not row or row[0] != 'live':
        return []
    xp = int(scorecard.get('xp_awarded') or 0)
    events = [ProgressionEvent('SESSION_ENDED', driver, 'session', source_id, 'CALCULATED',
                               {'session_id': sid, 'xp_awarded': xp}, 'Session complete',
                               f'Career session processed: {xp} XP (calculated).')]
    total = db.execute('SELECT total_xp FROM career_profiles WHERE id=?', (driver,)).fetchone()
    if total:
        before = curve.progress(max(0, total[0] - xp))['current']
        after = curve.progress(total[0])['current']
        if after > before:
            events.append(ProgressionEvent('LEVEL_UP', driver, 'session', f'{source_id}:L{after}', 'CALCULATED',
                                           {'session_id': sid, 'from': before, 'to': after},
                                           f'Level {after} reached', f'Career level {before} to {after} (calculated).'))
    for layout, car, payload in db.execute('SELECT layout_id,car_id,payload FROM career_mastery_history WHERE source_id=? AND driver_id=?', (source_id, driver)).fetchall():
        data = json.loads(payload)
        if (data.get('pb_improvement_ms') or 0) > 0:
            events.append(ProgressionEvent('PB_SET', driver, 'session', f'{source_id}:{layout}:{car}', 'CALCULATED',
                                           {'session_id': sid, 'layout_id': layout, 'car_id': car, 'pb_ms': data['pb_ms'],
                                            'previous_pb_ms': data.get('previous_pb_ms'), 'improvement_ms': data['pb_improvement_ms']},
                                           'New personal best', f"Application-recorded PB improved by {data['pb_improvement_ms']} ms (calculated)."))
    for definition_id, title in db.execute('SELECT definition_id,title FROM career_achievements WHERE driver_id=? AND source_id=?', (driver, source_id)).fetchall():
        events.append(ProgressionEvent('ACHIEVEMENT_UNLOCKED', driver, 'achievement', definition_id, 'CALCULATED',
                                       {'session_id': sid, 'definition_id': definition_id}, 'Achievement unlocked', title))
    for (category,) in db.execute("SELECT category FROM career_xp_events WHERE driver_id=? AND source_id=? AND category LIKE 'challenge\\_%' ESCAPE '\\'", (driver, source_id)).fetchall():
        events.append(ProgressionEvent('CHALLENGE_COMPLETED', driver, 'challenge', f'{source_id}:{category}', 'CALCULATED',
                                       {'session_id': sid, 'category': category}, 'Challenge completed', category[len('challenge_'):].replace('_', ' ')))
    return events


def emit_for_scorecard(store, scorecard: dict, curve) -> int:
    """Write events + notifications in one writer transaction. Never raises; returns events written."""
    try:
        def operation(db):
            events = build_events(db, scorecard, curve)
            if not events:
                return 0
            stamp = datetime.now(timezone.utc).isoformat()
            # SESSION_ENDED is the idempotency anchor: if it already exists, everything was emitted.
            if not _insert(db, events[0], stamp):
                return 0
            return 1 + sum(_insert(db, e, stamp) for e in events[1:])
        return store.career_transaction(operation)
    except Exception as error:
        log.warning('gamification.events_failed', extra={'event': 'gamification.events_failed',
                                                          'details': {'error_type': type(error).__name__}})
        return 0
