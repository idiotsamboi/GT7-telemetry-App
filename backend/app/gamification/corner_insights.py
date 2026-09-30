"""F026-F030: corner insights, streaks and mastery badges from stored career corner records.

Everything is CALCULATED (player-relative segment timing on the application's distance-aligned traces);
none of it is official GT7 data. Corner records only exist for live, eligible sessions, so replay/demo/
synthetic sources can never produce insights, streaks or badges. Nothing here reads raw samples.
"""
from __future__ import annotations

import json
import logging
from statistics import median

from .events import ProgressionEvent, _insert

log = logging.getLogger('gamification')

PROVENANCE = 'CALCULATED'
MIN_SAMPLES = 3            # same threshold corner mastery uses for a score / coverage
MIN_LOSS_S = .005          # below this a "loss" is timing noise, not a finding
GAIN_CAPTURE = .5          # conservative share of the supported loss an easy gain may claim
CHALLENGE_MIN_SAMPLES = 5
CHALLENGE_MIN_CONFIDENCE = .1
STREAK_TARGET_SCORE = 70
STREAK_HOLD_TOLERANCE = 5  # a score within this of the previous one counts as holding
CORNER_BADGE_KINDS = ('corner_mastery',)


def streak_kind(layout_id: str, car_id: int, corner_id: str) -> str:
    return f'corner:{layout_id}:{car_id}:{corner_id}'


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float('inf')


def corner_loss(record: dict) -> dict | None:
    """Supported loss = median recent segment minus the driver's own best segment. None when unsupported."""
    history = [v for v in (record.get('recent_segment_ms') or []) if _num(v) and v > 0]
    if not record.get('corner_id') or record.get('sample_count', 0) < MIN_SAMPLES or len(history) < MIN_SAMPLES:
        return None
    best, typical = min(history), median(history)
    loss_s = round((typical - best) / 1000, 4)
    if loss_s < MIN_LOSS_S:
        return None
    return {'corner_id': record['corner_id'], 'name': record.get('name') or record['corner_id'], 'loss_s': loss_s,
            'best_segment_ms': round(best, 3), 'typical_segment_ms': round(typical, 3),
            'confidence': record.get('confidence'), 'sample_count': record['sample_count'],
            'consistency': record.get('consistency'), 'provenance': PROVENANCE,
            'evidence': {'method': 'median recent segment vs own best segment', 'window_m': record.get('comparison_window_m'),
                         'samples_used': len(history), 'source_id': record.get('source_id')}}


def biggest_loss(records: list[dict]) -> dict | None:
    """F026: ordered by loss desc, then confidence desc, then corner id (deterministic ties)."""
    losses = [x for x in map(corner_loss, records) if x]
    if not losses:
        return None
    top = min(losses, key=lambda x: (-x['loss_s'], -(x['confidence'] or 0), x['corner_id']))
    return dict(top, reason=f"{top['name']}: your typical pass is {top['loss_s']:.3f}s slower than your own best pass (calculated).")


def easiest_gain(records: list[dict]) -> dict | None:
    """F027: best (estimated gain x repeatability). The estimate never exceeds the supported loss."""
    options = []
    for loss in filter(None, map(corner_loss, records)):
        if not _num(loss['consistency']):
            continue                                   # repeatability unknown -> cannot call it easy
        gain = min(loss['loss_s'], round(loss['loss_s'] * GAIN_CAPTURE, 4))
        repeat = max(0.0, min(1.0, loss['consistency'] / 100))
        options.append(dict(loss, estimated_gain_s=gain, repeatability=round(repeat, 3), ease=round(gain * repeat, 5)))
    if not options:
        return None
    top = min(options, key=lambda x: (-x['ease'], -(x['confidence'] or 0), x['corner_id']))
    return dict(top, reason=(f"{top['name']}: about {top['estimated_gain_s']:.3f}s looks recoverable of a {top['loss_s']:.3f}s supported loss, "
                             f"and you repeat this corner reliably ({round(top['repeatability'] * 100)}%). Estimate is calculated, not official."))


def challenge_gate(record_loss: dict | None) -> str | None:
    """Reason a corner challenge may not be offered, or None when allowed."""
    if not record_loss:
        return 'no supported corner loss'
    if record_loss['sample_count'] < CHALLENGE_MIN_SAMPLES:
        return 'too few corner samples'
    if (record_loss['confidence'] or 0) < CHALLENGE_MIN_CONFIDENCE:
        return 'corner confidence too low'
    return None


def corner_records(db_or_none, store, driver_id: str, layout_id: str, car_id: int) -> list[dict]:
    sql, params = ('SELECT payload FROM career_corner_mastery WHERE driver_id=? AND layout_id=? AND car_id=? ORDER BY corner_id LIMIT 500',
                   (driver_id, layout_id, car_id))
    rows = db_or_none.execute(sql, params).fetchall() if db_or_none is not None else [(r['payload'],) for r in store.query(sql, params)]
    return [json.loads(r[0]) for r in rows]


def update_corner_streaks(db, driver_id: str, layout: str, car: int, source_id: str, touched: dict, stamp: str) -> int:
    """F029: once per session and corner. Improving/holding above target extends; otherwise resets with a note."""
    changed = 0
    for corner_id, prior in sorted(touched.items()):
        row = db.execute('SELECT payload FROM career_corner_mastery WHERE driver_id=? AND layout_id=? AND car_id=? AND corner_id=?',
                         (driver_id, layout, car, corner_id)).fetchone()
        score = json.loads(row[0]).get('score') if row else None
        if not _num(score):
            continue                                   # not yet measurable: neither extend nor reset
        kind = streak_kind(layout, car, corner_id)
        old = db.execute('SELECT current_count,best_count,last_source_id FROM career_streaks WHERE driver_id=? AND kind=?', (driver_id, kind)).fetchone()
        if old and old[2] == source_id:
            continue
        good = score >= STREAK_TARGET_SCORE and (not _num(prior) or score >= prior - STREAK_HOLD_TOLERANCE)
        count = ((old[0] if old else 0) + 1) if good else 0
        best = max(old[1] if old else 0, count)
        if good:
            reason = f'Corner score {score:g} held or improved at or above {STREAK_TARGET_SCORE} (calculated)'
        elif score < STREAK_TARGET_SCORE:
            reason = f'Analysis: corner score {score:g} was below the {STREAK_TARGET_SCORE} target this session; the streak restarts with no penalty'
        else:
            reason = f'Analysis: corner score dipped from {prior:g} to {score:g}; the streak restarts with no penalty'
        db.execute('INSERT OR REPLACE INTO career_streaks VALUES(?,?,?,?,?,?)', (driver_id, kind, count, best, source_id, reason))
        changed += 1
    return changed


def award_corner_badges(db, driver_id: str, layout: str, car: int, source_id: str, stamp: str) -> int:
    """F030: one ACHIEVEMENT_UNLOCKED event per badge and driver (deterministic id), with evidence."""
    from .badges import BADGES
    mastered = sorted(c['corner_id'] for c in corner_records(db, None, driver_id, layout, car) if c.get('mastered'))
    written = 0
    for badge in BADGES:
        if badge.kind not in CORNER_BADGE_KINDS or len(mastered) < badge.threshold:
            continue
        evidence = {'badge_id': badge.id, 'layout_id': layout, 'car_id': car, 'mastered_corner_ids': mastered[:50],
                    'mastered_count': len(mastered), 'threshold': badge.threshold, 'source_id': source_id, 'provenance': PROVENANCE}
        written += _insert(db, ProgressionEvent('ACHIEVEMENT_UNLOCKED', driver_id, 'corner_badge', badge.id, PROVENANCE, evidence,
                                                'Badge earned: ' + badge.name, badge.description + ' (calculated application progression).'), stamp)
    return written


def apply_corner_progress(db, driver_id: str, layout: str, car: int, source_id: str, touched: dict, stamp: str) -> None:
    """Savepoint-isolated: a failure here never disturbs mastery, XP or recording."""
    if not touched:
        return
    db.execute('SAVEPOINT corner_progress')
    try:
        update_corner_streaks(db, driver_id, layout, car, source_id, touched, stamp)
        award_corner_badges(db, driver_id, layout, car, source_id, stamp)
    except Exception as error:
        db.execute('ROLLBACK TO corner_progress')
        db.execute('RELEASE corner_progress')
        log.warning('gamification.corner_progress_failed', extra={'event': 'gamification.corner_progress_failed',
                                                                   'details': {'error_type': type(error).__name__}})
        return
    db.execute('RELEASE corner_progress')


def insights(store, driver_id: str, layout_id: str, car_id: int) -> dict:
    records = corner_records(None, store, driver_id, layout_id, car_id)
    prefix = f'corner:{layout_id}:{car_id}:'
    streaks = [dict(r, corner_id=r['kind'][len(prefix):]) for r in store.query(
        'SELECT kind,current_count,best_count,last_source_id,reason FROM career_streaks WHERE driver_id=? AND substr(kind,1,?)=? ORDER BY kind LIMIT 200',
        (driver_id, len(prefix), prefix))]
    challenge = None
    for row in store.query("SELECT id,status,expires_at,payload FROM career_challenges WHERE driver_id=? AND kind='corner_practice' "
                           "AND status IN ('offered','accepted') ORDER BY created_at DESC,id LIMIT 20", (driver_id,)):
        body = json.loads(row['payload'])
        req = body.get('requirements', {})
        if req.get('layout_id') == layout_id and req.get('car_id') == car_id:
            challenge = {'id': row['id'], 'status': row['status'], 'expires_at': row['expires_at'], 'title': body.get('title'),
                         'description': body.get('description'), 'corner_id': req.get('corner_id'), 'target_segment_ms': req.get('target_segment_ms'),
                         'current': body.get('current'), 'target': body.get('target'), 'confidence': body.get('confidence')}
            break
    badges = []
    from .badges import BADGES
    mastered = sum(1 for c in records if c.get('mastered'))
    for badge in BADGES:
        if badge.kind in CORNER_BADGE_KINDS:
            ev = store.query("SELECT created_at,evidence FROM career_events WHERE driver_id=? AND kind='ACHIEVEMENT_UNLOCKED' AND source='corner_badge' AND source_id=?",
                             (driver_id, badge.id))
            badges.append({'id': badge.id, 'name': badge.name, 'threshold': badge.threshold, 'mastered_on_layout': mastered,
                           'unlocked': bool(ev), 'earned_at': ev[0]['created_at'] if ev else None})
    return {'layout_id': layout_id, 'car_id': car_id, 'provenance': PROVENANCE, 'min_samples': MIN_SAMPLES,
            'corners_considered': len(records), 'biggest_loss': biggest_loss(records), 'easiest_gain': easiest_gain(records),
            'challenge': challenge, 'streaks': streaks, 'badges': badges,
            'note': 'Calculated from your own stored passes on this layout and car; not official GT7 data.'}
