"""F033/F036/F041/F043/F044/F050: registry of dynamic challenge types (batch 4a).

Each type supplies an offer generator and (optionally) progress evaluators. challenges.py owns the
lifecycle (offer/accept/skip/expiry/rewards); this module only adds new kinds, reusing its tables.

Rules shared by every type here:
- Everything is CALCULATED from stored, live, eligible career evidence; nothing is official GT7 data and
  no incident/penalty/flag is ever claimed.
- Targets are frozen into the persisted payload at offer time and never exceed what the evidence supports.
- Offers that fail a gate are skipped without punishment; the reason is persisted (career_challenge_history,
  challenge_id 'reject:<kind>:<source_id>', status 'rejected:<reason>') once per source.
- All writes join the caller's career transaction, are savepoint-isolated, deterministic and idempotent.
- No per-packet work and no raw sample reads: bounded queries over career tables only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median, pstdev, mean
from typing import Callable

from .corner_insights import CHALLENGE_MIN_SAMPLES, challenge_gate, corner_loss, corner_records
from .scoring import score_to_grade

log = logging.getLogger('gamification')

PROVENANCE = 'CALCULATED'
EXPIRY_DAYS = 14
COOLDOWN_DAYS = 7
MIN_CONFIDENCE = .1
MIN_PB_HISTORY = 5
PB_MARGIN_MS, PB_MARGIN_FRACTION = 100, .0025
PB_WINDOW_LAPS = 10
SESSION_GOAL_MIN_LAPS, SESSION_GOAL_GAIN = 5, .002
CONSISTENCY_MIN_LAPS, CONSISTENCY_FACTOR, CONSISTENCY_FLOOR = 8, .85, .002
PERFECT_MIN_LAPS = 5
FIND_SECOND_TOTAL_S, FIND_SECOND_CAPTURE, FIND_SECOND_MAX_CORNERS = 1.0, .75, 4
GRADES = ('D', 'C', 'B', 'A', 'S')


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _json(value) -> str:
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def _cid(driver_id: str, kind: str, bucket: str) -> str:
    return 'challenge:v1:' + hashlib.sha256(f'{driver_id}:{kind}:{bucket}'.encode()).hexdigest()[:32]


def _monday(stamp: str) -> datetime:
    current = _time(stamp)
    return current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=current.weekday())


def _identity(ctx: dict) -> tuple[str, int]:
    return ctx['evidence'].get('layout_id'), ctx['evidence'].get('car_id')


def _durations(ctx: dict) -> list[float]:
    return [lap['duration_ms'] for lap in ctx['laps'] if _num(lap.get('duration_ms'))]


# ---------------------------------------------------------------- persistence helpers

def reject(db, ctx: dict, kind: str, reason: str) -> None:
    """Persist why an offer was not made. One row per kind and source, so reprocessing is a no-op."""
    key = f"reject:{kind}:{ctx['source_id']}"
    if db.execute('SELECT 1 FROM career_challenge_history WHERE challenge_id=? LIMIT 1', (key,)).fetchone():
        return
    db.execute('INSERT INTO career_challenge_history(challenge_id,driver_id,status,created_at) VALUES(?,?,?,?)',
               (key, ctx['driver_id'], 'rejected:' + reason, ctx['stamp']))


def rejections(store, driver_id: str, limit: int = 50) -> list[dict]:
    rows = store.query("SELECT challenge_id,status,created_at FROM career_challenge_history WHERE driver_id=? AND status LIKE 'rejected:%' "
                       'ORDER BY id DESC LIMIT ?', (driver_id, max(1, min(limit, 200))))
    return [dict(id=r['challenge_id'], reason=r['status'][len('rejected:'):], created_at=r['created_at']) for r in rows]


def _insert(db, ctx: dict, kind: str, bucket: str, payload: dict, days: int = EXPIRY_DAYS, cid: str | None = None) -> str | None:
    cid = cid or _cid(ctx['driver_id'], kind, bucket)
    expiry = (_time(ctx['stamp']) + timedelta(days=days)).isoformat()
    inserted = db.execute('INSERT OR IGNORE INTO career_challenges VALUES(?,?,?,?,?,?,?,?,?)',
                          (cid, ctx['driver_id'], kind, bucket, 'offered', ctx['stamp'], expiry, None, _json(payload)))
    if not inserted.rowcount:
        return None
    db.execute('INSERT INTO career_challenge_history(challenge_id,driver_id,status,created_at) VALUES(?,?,?,?)',
               (cid, ctx['driver_id'], 'offered', ctx['stamp']))
    return cid


def _payload(ctx: dict, *, title: str, description: str, why: str, evaluator: str, target, reward_xp: int, difficulty: str,
             requirements: dict, evidence: dict, confidence: float | None = None, **extra) -> dict:
    layout, car = _identity(ctx)
    return dict(title=title, description=description, why=why, calendar_timezone='UTC', provenance=PROVENANCE,
                label='Application-calculated challenge; not official GT7 data.',
                requirements=dict(layout_id=layout, car_id=car, evaluator=evaluator, tolerance_pct=None,
                                  future_sessions_only=True, provenance='live', comparable_only=True, **requirements),
                confidence=round(confidence if confidence is not None else ctx['evidence'].get('confidence') or 0, 3),
                difficulty=difficulty, reward_xp=reward_xp, repeat_cap=1, progress=0, current=0, target=target,
                evidence=dict(baseline_source_id=ctx['source_id'], baseline_lap_ids=ctx['evidence'].get('comparable_lap_ids', [])[:200],
                              official_validity='unknown', **evidence),
                completion_evidence=None, **extra)


def _gate(db, ctx: dict, kind: str, min_laps: int) -> str | None:
    """Common rejection gates. Returns the reason or None."""
    layout, car = _identity(ctx)
    if ctx['session'].get('provenance') != 'live':
        return 'non_live_source'
    if not ctx['laps'] or not _durations(ctx):
        return 'telemetry_unavailable'
    if not isinstance(layout, str) or not layout or not isinstance(car, int) or isinstance(car, bool) or car <= 0:
        return 'ambiguous_track'
    if len(ctx['laps']) < min_laps:
        return 'too_few_samples'
    if (ctx['evidence'].get('confidence') or 0) < MIN_CONFIDENCE:
        return 'low_confidence'
    now = _time(ctx['stamp'])
    for row in db.execute('SELECT status,created_at,payload FROM career_challenges WHERE driver_id=? AND kind=? ORDER BY created_at DESC,id LIMIT 30',
                          (ctx['driver_id'], kind)).fetchall():
        requirements = json.loads(row[2]).get('requirements', {})
        if (requirements.get('layout_id'), requirements.get('car_id')) != (layout, car):
            continue
        if row[0] in ('offered', 'accepted'):
            return 'active_duplicate'
        if now - _time(row[1]) < timedelta(days=COOLDOWN_DAYS):
            return 'recent_repeat'
    return None


def _pb_target(db, ctx: dict) -> tuple[dict | None, str | None]:
    layout, car = _identity(ctx)
    row = db.execute('SELECT payload FROM career_track_mastery WHERE driver_id=? AND layout_id=? AND car_id=?', (ctx['driver_id'], layout, car)).fetchone()
    if not row:
        return None, 'telemetry_unavailable'
    data = json.loads(row[0])
    pb = data.get('pb_ms')
    if not _num(pb) or pb <= 1000:
        return None, 'telemetry_unavailable'
    if (data.get('layout_id'), data.get('car_id')) != (layout, car):
        return None, 'incompatible_comparison'
    history = data.get('lap_count') or 0
    if history < MIN_PB_HISTORY:
        return None, 'too_few_samples'
    margin = max(PB_MARGIN_MS, pb * PB_MARGIN_FRACTION)
    target = round(pb - margin, 1)
    if target <= 1000:
        return None, 'incompatible_comparison'
    return dict(pb_ms=pb, margin_ms=round(margin, 1), target_lap_ms=target, history_laps=history), None


# ---------------------------------------------------------------- F033 session goal

def offer_session_goal(db, ctx: dict) -> str | None:
    """Goal for the NEXT session on this layout/car: median of comparable laps at/under a frozen target."""
    reason = _gate(db, ctx, 'session_goal', SESSION_GOAL_MIN_LAPS)
    if reason:
        return reason
    durations = _durations(ctx)
    center = median(durations)
    target = round(center * (1 - SESSION_GOAL_GAIN), 1)
    need = min(len(durations), 8)
    payload = _payload(ctx, title='Next-session goal',
                       description=f'In your next session on this layout and car, complete {need} comparable laps with a median at or under {round(target)} ms.',
                       why=f'Your last session had a median of {round(center)} ms over {len(durations)} comparable laps (calculated).',
                       evaluator='session_median', target=1, reward_xp=20, difficulty='steady',
                       requirements=dict(count=1, min_laps=need, target_median_ms=target),
                       evidence=dict(baseline_median_ms=round(center, 1), baseline_laps=len(durations)))
    _insert(db, ctx, 'session_goal', ctx['source_id'], payload)
    return None


def eval_session_median(payload: dict, ctx: dict) -> float:
    req, durations = payload['requirements'], _durations(ctx)
    return 1 if len(durations) >= req['min_laps'] and median(durations) <= req['target_median_ms'] else 0


# ---------------------------------------------------------------- F041 PB boss

def offer_pb_boss(db, ctx: dict) -> str | None:
    if not ctx['features'].get('track_mastery', True):
        return 'telemetry_unavailable'
    reason = _gate(db, ctx, 'pb_boss', 3)
    if reason:
        return reason
    pb, reason = _pb_target(db, ctx)
    if reason:
        return reason
    layout, car = _identity(ctx)
    payload = _payload(ctx, title='PB boss',
                       description=f"Beat your application-recorded PB by {pb['margin_ms']:g} ms: drive {round(pb['target_lap_ms'])} ms or faster within your first {PB_WINDOW_LAPS} comparable laps of a session.",
                       why=f"Your PB is {round(pb['pb_ms'])} ms over {pb['history_laps']} comparable laps on this layout and car (calculated).",
                       evaluator='pb_beat', target=1, reward_xp=40, difficulty='stretch',
                       requirements=dict(count=1, target_lap_ms=pb['target_lap_ms'], window_laps=PB_WINDOW_LAPS), evidence=pb)
    _insert(db, ctx, 'pb_boss', f'{_monday(ctx["stamp"]).date().isoformat()}:{layout}:{car}', payload)
    return None


def eval_pb_beat(payload: dict, ctx: dict) -> float:
    req = payload['requirements']
    window = _durations(ctx)[:req['window_laps']]
    return 1 if any(d <= req['target_lap_ms'] for d in window) else 0


# ---------------------------------------------------------------- F044 consistency boss

def offer_consistency_boss(db, ctx: dict) -> str | None:
    reason = _gate(db, ctx, 'consistency_boss', CONSISTENCY_MIN_LAPS)
    if reason:
        return reason
    durations = _durations(ctx)
    spread = pstdev(durations) / mean(durations)
    threshold = round(spread * CONSISTENCY_FACTOR, 6)
    if threshold < CONSISTENCY_FLOOR:
        return 'low_confidence'                 # already below the measurable floor: nothing honest to target
    layout, car = _identity(ctx)
    payload = _payload(ctx, title='Consistency boss',
                       description=f'Across at least {CONSISTENCY_MIN_LAPS} comparable laps in one session, keep lap-time spread (standard deviation / mean) at or under {threshold * 100:.3f}%.',
                       why=f'Your last session spread was {spread * 100:.3f}% over {len(durations)} comparable laps (calculated).',
                       evaluator='spread_below', target=1, reward_xp=35, difficulty='stretch',
                       requirements=dict(count=1, min_laps=CONSISTENCY_MIN_LAPS, max_spread_fraction=threshold),
                       evidence=dict(baseline_spread_fraction=round(spread, 6), baseline_laps=len(durations)))
    _insert(db, ctx, 'consistency_boss', f'{_monday(ctx["stamp"]).date().isoformat()}:{layout}:{car}', payload)
    return None


def eval_spread_below(payload: dict, ctx: dict) -> float:
    req, durations = payload['requirements'], _durations(ctx)
    if len(durations) < req['min_laps']:
        return 0
    return 1 if pstdev(durations) / mean(durations) <= req['max_spread_fraction'] else 0


# ---------------------------------------------------------------- F050 perfect session

def offer_perfect_session(db, ctx: dict) -> str | None:
    reason = _gate(db, ctx, 'perfect_session', PERFECT_MIN_LAPS)
    if reason:
        return reason
    grade = ctx['evidence'].get('session_grade')
    if grade not in GRADES:
        return 'telemetry_unavailable'
    target = GRADES[min(GRADES.index(grade) + 1, len(GRADES) - 1)]
    layout, car = _identity(ctx)
    payload = _payload(ctx, title='Perfect session (application-calculated)',
                       description=f'Complete a session of at least {PERFECT_MIN_LAPS} comparable laps where every recorded comparable lap passes the application clean-lap check and the calculated consistency grade reaches {target}.',
                       why=f'Your last session graded {grade} (application-calculated consistency). The game reports no official incident data, so this is not an incident-free claim.',
                       evaluator='session_grade', target=1, reward_xp=40, difficulty='stretch',
                       requirements=dict(count=1, min_laps=PERFECT_MIN_LAPS, target_grade=target, require_no_excluded_laps=True),
                       evidence=dict(baseline_grade=grade, baseline_consistency_score=ctx['evidence'].get('consistency_score')))
    _insert(db, ctx, 'perfect_session', f'{_monday(ctx["stamp"]).date().isoformat()}:{layout}:{car}', payload)
    return None


def eval_session_grade(payload: dict, ctx: dict) -> float:
    req, evidence = payload['requirements'], ctx['evidence']
    grade = evidence.get('session_grade')
    if grade not in GRADES or (evidence.get('comparable_laps') or 0) < req['min_laps']:
        return 0
    if req.get('require_no_excluded_laps') and evidence.get('excluded_laps'):
        return 0
    return 1 if GRADES.index(grade) >= GRADES.index(req['target_grade']) else 0


# ---------------------------------------------------------------- F043 find one second

def offer_find_one_second(db, ctx: dict) -> str | None:
    if not ctx['features'].get('corner_mastery', True):
        return 'telemetry_unavailable'
    reason = _gate(db, ctx, 'find_one_second', 3)
    if reason:
        return reason
    layout, car = _identity(ctx)
    losses = []
    for record in corner_records(db, None, ctx['driver_id'], layout, car):
        loss = corner_loss(record)
        if loss and not challenge_gate(loss):
            losses.append(loss)
    losses.sort(key=lambda x: (-x['loss_s'], x['corner_id']))
    losses = losses[:FIND_SECOND_MAX_CORNERS]
    if len(losses) < 2:
        return 'too_few_samples'
    supported = sum(x['loss_s'] for x in losses)
    goal = min(FIND_SECOND_TOTAL_S, supported * FIND_SECOND_CAPTURE)
    steps = []
    for item in losses:
        gain = round(item['loss_s'] * goal / supported, 4)          # <= loss * capture, so never above the supported loss
        steps.append(dict(corner_id=item['corner_id'], name=item['name'], gain_s=gain, supported_loss_s=item['loss_s'],
                          target_segment_ms=round(item['typical_segment_ms'] - gain * 1000, 1),
                          best_segment_ms=item['best_segment_ms'], typical_segment_ms=item['typical_segment_ms']))
    total = round(sum(s['gain_s'] for s in steps), 4)
    payload = _payload(ctx, title=f'Find {total:g} seconds (calculated)',
                       description=f'Recover {total:g}s across {len(steps)} corners: ' + ', '.join(f"{s['name']} {s['gain_s']:.3f}s" for s in steps) + '. Each step counts once a later session drives that corner at its frozen segment time.',
                       why=f'These corners show {supported:.3f}s of supported loss against your own best passes; the goal claims at most {round(FIND_SECOND_CAPTURE * 100)}% of it (calculated, not official).',
                       evaluator='corner_set', target=total, reward_xp=50, difficulty='stretch',
                       requirements=dict(count=len(steps), steps=steps),
                       evidence=dict(supported_loss_s=round(supported, 4), goal_s=total), verified_corners=[])
    _insert(db, ctx, 'find_one_second', f'{_monday(ctx["stamp"]).date().isoformat()}:{layout}:{car}', payload)
    return None


def eval_corner_set(payload: dict, ctx: dict) -> float:
    """Progress = sum of gains of corners verified in any eligible later session (set union, so no double counting)."""
    req = payload['requirements']
    accepted = set(ctx['evidence'].get('comparable_lap_ids', []))
    verified = set(payload.get('verified_corners', []))
    for lap_id, spatial in (ctx['context'].get('spatial') or {}).items():
        if lap_id not in accepted or spatial.get('reference_lap_id') not in accepted or spatial.get('source') != 'calculated' \
                or (spatial.get('layout_id'), spatial.get('car_id')) != (req['layout_id'], req['car_id']):
            continue
        for item in spatial.get('items', [])[:100]:
            ms, conf = item.get('segment_ms'), item.get('confidence')
            if not (_num(ms) and ms > 0 and _num(conf) and conf >= .5):
                continue
            for step in req['steps']:
                if step['corner_id'] == item.get('corner_id') and ms <= step['target_segment_ms']:
                    verified.add(step['corner_id'])
    payload['verified_corners'] = sorted(verified)
    return round(sum(s['gain_s'] for s in req['steps'] if s['corner_id'] in verified), 4)


# ---------------------------------------------------------------- F036 chains

def _chain_step(db, ctx: dict, chain: dict, index: int) -> tuple[dict | None, str | None]:
    """Build the payload of step `index` (0-based). Targets are computed here and frozen."""
    step = chain['steps'][index]
    evaluator, req = step['evaluator'], dict(count=step.get('count', 1))
    evidence, reward = {}, step['reward_xp']
    if evaluator == 'consistent_streak':
        durations = _durations(ctx)
        center = median(durations)
        pct = max(abs(d - center) / center * 100 for d in durations)
        req.update(count=3, tolerance_pct=round(max(.1, pct * .9), 4))
        evidence = dict(baseline_max_deviation_pct=round(pct, 4))
    elif evaluator == 'pb_beat':
        pb, reason = _pb_target(db, ctx)
        if reason:
            return None, reason
        req.update(count=1, target_lap_ms=pb['target_lap_ms'], window_laps=PB_WINDOW_LAPS)
        evidence = pb
    tolerance = req.pop('tolerance_pct', None)
    body = _payload(ctx, title=f"{chain['title']}: step {index + 1} of {chain['length']}", description=step['description'],
                    why=f"Step {index + 1} of a {chain['length']}-step chain; each step unlocks only after the previous one is completed. Skipping ends the chain with no penalty.",
                    evaluator=evaluator, target=req['count'], reward_xp=reward, difficulty=step['difficulty'], requirements=req, evidence=evidence,
                    chain=dict(chain_id=chain['chain_id'], step=index + 1, length=chain['length'], prerequisite_id=chain.get('prerequisite_id'),
                               title=chain['title'], steps=chain['steps']))
    body['requirements']['tolerance_pct'] = tolerance
    return body, None


def _chain_definition(chain_id: str, with_pb: bool) -> dict:
    steps = [dict(evaluator='clean_laps', count=3, reward_xp=10, difficulty='steady', description='Complete 3 comparable laps in one future session.'),
             dict(evaluator='consistent_streak', count=3, reward_xp=20, difficulty='stretch', description='Complete 3 consecutive comparable laps within your tolerance of their median.')]
    if with_pb:
        steps.append(dict(evaluator='pb_beat', count=1, reward_xp=30, difficulty='stretch',
                          description='Beat your application-recorded PB by a small frozen margin within your first comparable laps.'))
    return dict(chain_id=chain_id, title='Practice chain', length=len(steps), steps=steps)


def offer_chain(db, ctx: dict) -> str | None:
    reason = _gate(db, ctx, 'chain', 3)
    if reason:
        return reason
    layout, car = _identity(ctx)
    bucket = f'{_monday(ctx["stamp"]).date().isoformat()}:{layout}:{car}'
    chain_id = hashlib.sha256(f"{ctx['driver_id']}:chain:{bucket}".encode()).hexdigest()[:16]
    with_pb = ctx['features'].get('track_mastery', True) and _pb_target(db, ctx)[1] is None
    chain = _chain_definition(chain_id, with_pb)
    body, reason = _chain_step(db, ctx, chain, 0)
    if reason:
        return reason
    _insert(db, ctx, 'chain', f'{bucket}#1', body, cid=_cid(ctx['driver_id'], 'chain', f'{bucket}#1'))
    return None


def advance_chains(db, ctx: dict) -> None:
    """Offer step k+1 only after step k is completed. A skipped/expired/abandoned step simply never unlocks the next."""
    layout, car = _identity(ctx)
    now = _time(ctx['stamp'])
    rows = db.execute("SELECT id,bucket,expires_at,payload FROM career_challenges WHERE driver_id=? AND kind='chain' AND status='completed' "
                      'ORDER BY created_at DESC,id LIMIT 50', (ctx['driver_id'],)).fetchall()
    for row_id, bucket, expires_at, raw in rows:
        payload = json.loads(raw)
        chain = payload['chain']
        if chain['step'] >= chain['length'] or (payload['requirements'].get('layout_id'), payload['requirements'].get('car_id')) != (layout, car):
            continue
        if expires_at and now > _time(expires_at) + timedelta(days=EXPIRY_DAYS):
            continue
        base = bucket.rsplit('#', 1)[0]
        next_bucket = f"{base}#{chain['step'] + 1}"
        next_id = _cid(ctx['driver_id'], 'chain', next_bucket)
        if db.execute('SELECT 1 FROM career_challenges WHERE id=?', (next_id,)).fetchone():
            continue
        if ctx['session'].get('provenance') != 'live' or not _durations(ctx):
            continue
        body, reason = _chain_step(db, ctx, dict(chain, prerequisite_id=row_id), chain['step'])
        if reason:
            reject(db, ctx, 'chain', reason)
            continue
        _insert(db, ctx, 'chain', next_bucket, body, cid=next_id)


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class ChallengeType:
    kind: str
    feature: str
    offer: Callable[[object, dict], str | None]
    evaluators: dict = field(default_factory=dict)


TYPES: dict[str, ChallengeType] = {t.kind: t for t in (
    ChallengeType('session_goal', 'F033', offer_session_goal, {'session_median': eval_session_median}),
    ChallengeType('chain', 'F036', offer_chain, {'pb_beat': eval_pb_beat}),
    ChallengeType('pb_boss', 'F041', offer_pb_boss, {'pb_beat': eval_pb_beat}),
    ChallengeType('find_one_second', 'F043', offer_find_one_second, {'corner_set': eval_corner_set}),
    ChallengeType('consistency_boss', 'F044', offer_consistency_boss, {'spread_below': eval_spread_below}),
    ChallengeType('perfect_session', 'F050', offer_perfect_session, {'session_grade': eval_session_grade}),
)}
EVALUATORS: dict[str, Callable[[dict, dict], float]] = {name: fn for t in TYPES.values() for name, fn in t.evaluators.items()}


def make_context(driver_id: str, source_id: str, session: dict, evidence: dict, laps: list, context: dict, stamp: str) -> dict:
    return dict(driver_id=driver_id, source_id=source_id, session=session, evidence=evidence, laps=laps,
                context=context, features=context.get('features', {}), stamp=stamp)


def evaluate(payload: dict, ctx: dict) -> float | None:
    """Absolute progress value for a custom evaluator, or None when the evaluator is not a registered one."""
    fn = EVALUATORS.get(payload['requirements']['evaluator'])
    return None if fn is None else fn(payload, ctx)


def offer_all(db, ctx: dict) -> None:
    """Advance chains then offer every registered type. Savepoint-isolated: never disturbs XP or recording."""
    db.execute('SAVEPOINT challenge_types')
    try:
        for kind, challenge_type in TYPES.items():
            reason = challenge_type.offer(db, ctx)
            if reason and reason != 'non_live_source':
                reject(db, ctx, kind, reason)
        advance_chains(db, ctx)
    except Exception as error:
        db.execute('ROLLBACK TO challenge_types')
        db.execute('RELEASE challenge_types')
        log.warning('gamification.challenge_types_failed', extra={'event': 'gamification.challenge_types_failed',
                                                                   'details': {'error_type': type(error).__name__}})
        return
    db.execute('RELEASE challenge_types')
