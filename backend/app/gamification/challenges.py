"""Server-evaluated practice challenges from finalized, compatible lap summaries.

The coordinator calls advancement only inside its verified eligible-source transaction.
These functions never commit, read raw samples, or update a profile's XP total.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from statistics import median

from ..domain.training_defs import clean_laps, consistent_streak
from . import challenge_types
from .corner_insights import challenge_gate, corner_records, easiest_gain
from .scoring import evaluate
from .track_components import mission_component


CHALLENGES_DDL = '''
CREATE TABLE IF NOT EXISTS career_challenges(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, kind TEXT NOT NULL,
 bucket TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT, accepted_at TEXT, payload TEXT NOT NULL,
 UNIQUE(driver_id,kind,bucket));
CREATE INDEX IF NOT EXISTS career_challenges_driver ON career_challenges(driver_id,status);
CREATE TABLE IF NOT EXISTS career_challenge_sources(
 challenge_id TEXT NOT NULL, source_id TEXT NOT NULL, session_id TEXT NOT NULL,
 PRIMARY KEY(challenge_id,source_id), UNIQUE(challenge_id,session_id));
CREATE TABLE IF NOT EXISTS career_challenge_history(
 id INTEGER PRIMARY KEY, challenge_id TEXT NOT NULL, driver_id TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL);
'''
DDL = CHALLENGES_DDL


def _time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Challenge timestamps require a timezone')
    return result.astimezone(timezone.utc)


def _json(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


def _rows(cursor):
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _history(db, item, status, stamp):
    db.execute('INSERT INTO career_challenge_history(challenge_id,driver_id,status,created_at) VALUES(?,?,?,?)',
               (item['id'], item['driver_id'], status, stamp))


def _expire(db, driver_id, stamp):
    current = _time(stamp)
    for row in _rows(db.execute("SELECT * FROM career_challenges WHERE driver_id=? AND status IN ('offered','accepted')", (driver_id,))):
        if row['expires_at'] and _time(row['expires_at']) <= current:
            db.execute("UPDATE career_challenges SET status='expired' WHERE id=?", (row['id'],))
            _history(db, row, 'expired', stamp)


def _public(row, stamp=None):
    item = json.loads(row['payload'])
    item.update({key: row[key] for key in ('id', 'driver_id', 'kind', 'bucket', 'status', 'created_at', 'expires_at', 'accepted_at')})
    if stamp and item['status'] in ('offered', 'accepted') and item['expires_at'] and _time(item['expires_at']) <= _time(stamp):
        item['status'] = 'expired'
    return item


def list_challenges(store, driver_id):
    """Bounded history, with expiry projected even if no sessions have arrived."""
    stamp = datetime.now(timezone.utc).isoformat()
    rows = store.query('SELECT * FROM career_challenges WHERE driver_id=? ORDER BY created_at DESC,id LIMIT 200', (driver_id,))
    return [_public(row, stamp) for row in rows]


def transition_challenge(db, driver_id, challenge_id, action, stamp):
    """Accept a proposal or skip it; skipping accepted work records abandonment."""
    if action not in ('accept', 'skip'):
        raise ValueError('Challenge action must be accept or skip')
    _expire(db, driver_id, stamp)
    rows = _rows(db.execute('SELECT * FROM career_challenges WHERE id=? AND driver_id=?', (challenge_id, driver_id)))
    if not rows:
        raise ValueError('Unknown challenge')
    row = rows[0]
    if _time(stamp) < _time(row['created_at']):
        raise ValueError('Challenge action predates its offer')
    if action == 'accept' and row['status'] == 'accepted':
        return _public(row)
    if row['status'] not in ('offered', 'accepted'):
        raise ValueError('Challenge is no longer available')
    status = 'accepted' if action == 'accept' else ('abandoned' if row['status'] == 'accepted' else 'skipped')
    accepted = stamp if action == 'accept' else row['accepted_at']
    db.execute('UPDATE career_challenges SET status=?,accepted_at=? WHERE id=?', (status, accepted, challenge_id))
    _history(db, row, status, stamp)
    row.update(status=status, accepted_at=accepted)
    return _public(row)


def _offers(db, driver_id, source_id, evidence, laps, stamp):
    """One offer per calendar period, regardless of layout changes or skipping."""
    if len(laps) < 3:
        return
    current = _time(stamp)
    midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = midnight - timedelta(days=current.weekday())
    durations = [lap['duration_ms'] for lap in laps]
    center = median(durations)
    baseline_pct = max(abs(duration - center) / center * 100 for duration in durations)
    tolerance = round(max(.1, baseline_pct * .9), 4)
    definitions = (
        ('daily', midnight.date().isoformat(), midnight + timedelta(days=1), 'Comparable practice', 'clean_laps', 3, 15),
        ('weekly', monday.date().isoformat(), monday + timedelta(days=7), 'Your consistency target', 'consistent_streak', 3, 45),
        ('permanent', 'v1', None, 'Build a practice habit', 'cumulative_clean_laps', 20, 60),
    )
    for kind, bucket, expiry, title, evaluator, target, reward in definitions:
        challenge_id = 'challenge:v1:' + hashlib.sha256(f'{driver_id}:{kind}:{bucket}'.encode()).hexdigest()[:32]
        consistency = evaluator == 'consistent_streak'
        description = (f'Complete {target} consecutive comparable laps within {tolerance:g}% of their median time in one session.'
                       if consistency else f'Complete {target} comparable laps ' + ('across future sessions.' if kind == 'permanent' else 'in one future session.'))
        payload = dict(title=title, description=description,
                       why=f'Based on {len(laps)} comparable live laps in this layout and car.',
                       calendar_timezone='UTC',
                       requirements=dict(layout_id=evidence['layout_id'], car_id=evidence['car_id'],
                                         evaluator=evaluator, count=target, tolerance_pct=tolerance if consistency else None,
                                         future_sessions_only=True, provenance='live', comparable_only=True),
                       confidence=round(min(.9, len(laps) / 20), 3),
                       difficulty='stretch' if consistency and baseline_pct > .1 else 'steady',
                       reward_xp=reward, repeat_cap=1, progress=0, current=0, target=target,
                       evidence=dict(baseline_source_id=source_id, baseline_lap_ids=evidence['comparable_lap_ids'],
                                     baseline_max_deviation_pct=round(baseline_pct, 4), official_validity='unknown'),
                       completion_evidence=None)
        inserted = db.execute('INSERT OR IGNORE INTO career_challenges VALUES(?,?,?,?,?,?,?,?,?)',
                              (challenge_id, driver_id, kind, bucket, 'offered', stamp, expiry.isoformat() if expiry else None, None, _json(payload)))
        if inserted.rowcount:
            _history(db, dict(id=challenge_id, driver_id=driver_id), 'offered', stamp)


def _offer_track_mission(db, driver_id, source_id, evidence, laps, stamp):
    """F019: one mission per week/layout/car, targeting the weakest measurable mastery component."""
    row = db.execute('SELECT payload FROM career_track_mastery WHERE driver_id=? AND layout_id=? AND car_id=?',
                     (driver_id, evidence['layout_id'], evidence['car_id'])).fetchone()
    component = mission_component(json.loads(row[0])) if row and len(laps) >= 3 else None
    if not component:
        return
    current = _time(stamp)
    monday = current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=current.weekday())
    durations = [lap['duration_ms'] for lap in laps]
    center = median(durations)
    baseline_pct = max(abs(d - center) / center * 100 for d in durations)
    consistency = component == 'consistency'
    tolerance = round(max(.1, baseline_pct * .9), 4)
    target = 3
    bucket = f"{monday.date().isoformat()}:{evidence['layout_id']}:{evidence['car_id']}"
    challenge_id = 'challenge:v1:' + hashlib.sha256(f'{driver_id}:track_mission:{bucket}'.encode()).hexdigest()[:32]
    description = (f'Track mission (consistency): complete {target} consecutive comparable laps within {tolerance:g}% of their median time in one session.'
                   if consistency else f'Track mission (pace): complete {target} comparable laps in one future session on this layout and car.')
    payload = dict(title='Track mission: ' + component, description=description, component=component,
                   why=f'{component.capitalize()} is your weakest measurable component on this layout and car (calculated).',
                   calendar_timezone='UTC',
                   requirements=dict(layout_id=evidence['layout_id'], car_id=evidence['car_id'],
                                     evaluator='consistent_streak' if consistency else 'clean_laps', count=target,
                                     tolerance_pct=tolerance if consistency else None, future_sessions_only=True,
                                     provenance='live', comparable_only=True),
                   confidence=round(min(.9, len(laps) / 20), 3), difficulty='stretch' if consistency else 'steady',
                   reward_xp=25, repeat_cap=1, progress=0, current=0, target=target,
                   evidence=dict(baseline_source_id=source_id, baseline_lap_ids=evidence['comparable_lap_ids'],
                                 baseline_max_deviation_pct=round(baseline_pct, 4), official_validity='unknown'),
                   completion_evidence=None)
    expiry = monday + timedelta(days=7)
    inserted = db.execute('INSERT OR IGNORE INTO career_challenges VALUES(?,?,?,?,?,?,?,?,?)',
                          (challenge_id, driver_id, 'track_mission', bucket, 'offered', stamp, expiry.isoformat(), None, _json(payload)))
    if inserted.rowcount:
        _history(db, dict(id=challenge_id, driver_id=driver_id), 'offered', stamp)


def _offer_corner_practice(db, driver_id, source_id, evidence, stamp):
    """F028: one corner challenge per week/layout/car aimed at the easiest supported gain. Skipping never punishes."""
    layout, car = evidence.get('layout_id'), evidence.get('car_id')
    if not isinstance(layout, str) or not layout or not isinstance(car, int) or isinstance(car, bool) or car <= 0:
        return
    pick = easiest_gain(corner_records(db, None, driver_id, layout, car))
    if challenge_gate(pick):
        return
    current = _time(stamp)
    monday = current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=current.weekday())
    bucket = f'{monday.date().isoformat()}:{layout}:{car}'
    challenge_id = 'challenge:v1:' + hashlib.sha256(f'{driver_id}:corner_practice:{bucket}'.encode()).hexdigest()[:32]
    target_ms = round(pick['typical_segment_ms'] - pick['estimated_gain_s'] * 1000, 1)
    target = 3
    payload = dict(title=f"Corner practice: {pick['name']}",
                   description=f"Drive {pick['name']} in {round(target_ms)} ms or faster on {target} laps in one future session (segment window as measured by the application).",
                   corner_id=pick['corner_id'], why=pick['reason'], calendar_timezone='UTC',
                   requirements=dict(layout_id=layout, car_id=car, evaluator='corner_segment', corner_id=pick['corner_id'],
                                     target_segment_ms=target_ms, count=target, tolerance_pct=None, future_sessions_only=True,
                                     provenance='live', comparable_only=True),
                   confidence=pick['confidence'], difficulty='steady', reward_xp=20, repeat_cap=1, progress=0, current=0, target=target,
                   evidence=dict(baseline_source_id=source_id, baseline_lap_ids=evidence['comparable_lap_ids'],
                                 typical_segment_ms=pick['typical_segment_ms'], best_segment_ms=pick['best_segment_ms'],
                                 estimated_gain_s=pick['estimated_gain_s'], official_validity='unknown'),
                   completion_evidence=None)
    inserted = db.execute('INSERT OR IGNORE INTO career_challenges VALUES(?,?,?,?,?,?,?,?,?)',
                          (challenge_id, driver_id, 'corner_practice', bucket, 'offered', stamp, (monday + timedelta(days=7)).isoformat(), None, _json(payload)))
    if inserted.rowcount:
        _history(db, dict(id=challenge_id, driver_id=driver_id), 'offered', stamp)


def _corner_observed(context, accepted_ids, requirements):
    """Laps whose stored, calculated segment for the frozen corner met the frozen target."""
    count = 0
    for lap_id, spatial in (context.get('spatial') or {}).items():
        if lap_id not in accepted_ids or spatial.get('reference_lap_id') not in accepted_ids or spatial.get('source') != 'calculated' \
                or (spatial.get('layout_id'), spatial.get('car_id')) != (requirements['layout_id'], requirements['car_id']):
            continue
        for item in spatial.get('items', [])[:100]:
            ms, conf = item.get('segment_ms'), item.get('confidence')
            if item.get('corner_id') == requirements['corner_id'] and isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0 \
                    and isinstance(conf, (int, float)) and conf >= .5 and ms <= requirements['target_segment_ms']:
                count += 1
                break
    return count


def advance_challenges(db, driver_id, source_id, session, evidence, context, stamp):
    """Return newly awarded XP; all writes join the caller's eligible transaction.

    Independent policy re-evaluation rejects replay, mixed/unknown identities and
    caller-supplied progress. Persisted source verification belongs to the caller.
    """
    _expire(db, driver_id, stamp)
    analysis = evaluate(session, context)
    if analysis['status'] != 'eligible' or analysis['evidence'] != evidence:
        return 0
    try:
        started, ended, processed = _time(session['started']), _time(session['ended']), _time(stamp)
    except (KeyError, ValueError, TypeError, AttributeError):
        return 0
    if not started <= ended <= processed:
        return 0
    accepted_ids = set(evidence['comparable_lap_ids'])
    laps = [lap for lap in session['laps'] if lap.get('id') in accepted_ids]
    # Keep excluded laps as explicit breaks in the streak evaluator. Reject gaps
    # in lap numbering as well: the domain evaluator only sees supplied rows.
    streak_laps = []
    previous_number = None
    for lap in session['laps']:
        number = lap.get('number')
        if lap.get('id') not in accepted_ids or isinstance(number, bool) or not isinstance(number, int):
            streak_laps.append({}); previous_number = None; continue
        if previous_number is not None and number != previous_number + 1:
            streak_laps.append({})
        streak_laps.append(lap); previous_number = number
    total = 0
    type_ctx = challenge_types.make_context(driver_id, source_id, session, evidence, laps, context, stamp)
    rows = _rows(db.execute("SELECT * FROM career_challenges WHERE driver_id=? AND status='accepted'", (driver_id,)))
    for row in rows:
        payload = json.loads(row['payload']); requirements = payload['requirements']
        if started <= _time(row['accepted_at']) or source_id == payload['evidence']['baseline_source_id']:
            continue
        if (evidence['layout_id'], evidence['car_id']) != (requirements['layout_id'], requirements['car_id']):
            continue
        inserted = db.execute('INSERT OR IGNORE INTO career_challenge_sources VALUES(?,?,?)', (row['id'], source_id, session['id']))
        if not inserted.rowcount:
            continue
        evaluator = requirements['evaluator']
        if evaluator in challenge_types.EVALUATORS:
            observed = challenge_types.evaluate(payload, type_ctx)
            current = max(payload['current'], observed)
        elif evaluator == 'consistent_streak':
            observed = consistent_streak({'laps': streak_laps}, dict(count=payload['target'], tolerance_pct=requirements['tolerance_pct'])).current
            current = max(payload['current'], observed)
        elif evaluator == 'corner_segment':
            observed = _corner_observed(context, accepted_ids, requirements)
            current = max(payload['current'], observed)
        else:
            summary_laps = [dict(lap, number=lap.get('number', index)) for index, lap in enumerate(laps)]
            observed = clean_laps({'laps': summary_laps}, {'count': payload['target']}).current
            current = payload['current'] + observed if evaluator == 'cumulative_clean_laps' else max(payload['current'], observed)
        payload['current'] = min(payload['target'], current)
        payload['progress'] = round(min(100, 100 * payload['current'] / payload['target']), 2)
        payload['completion_evidence'] = dict(source_id=source_id, session_id=session['id'],
                                              lap_ids=evidence['comparable_lap_ids'], observed=observed,
                                              layout_id=evidence['layout_id'], car_id=evidence['car_id'], official_validity='unknown')
        status = 'completed' if current >= payload['target'] else 'accepted'
        if status == 'completed':
            guard = row['id'] + ':completed'
            reward = db.execute('INSERT OR IGNORE INTO career_xp_events VALUES(?,?,?,?,?,?,?,?,?)',
                                (guard, guard, driver_id, session['id'], source_id, 'challenge_' + row['kind'], payload['reward_xp'], stamp, _json(payload['completion_evidence'])))
            if reward.rowcount:
                total += payload['reward_xp']
            _history(db, row, status, stamp)
        db.execute('UPDATE career_challenges SET status=?,payload=? WHERE id=?', (status, _json(payload), row['id']))
    _offers(db, driver_id, source_id, evidence, laps, stamp)
    if context.get('features', {}).get('track_mastery', True):
        _offer_track_mission(db, driver_id, source_id, evidence, laps, stamp)
    if context.get('features', {}).get('corner_mastery', True):
        _offer_corner_practice(db, driver_id, source_id, evidence, stamp)
    challenge_types.offer_all(db, type_ctx)
    return total
