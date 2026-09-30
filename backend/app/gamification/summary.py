"""Read-only progression views: recent gains (F009), overview (F007), timeline (F008), stats (F010).

Everything is derived from stored career rows for one driver. Unknown values are None, never
invented. All results are CALCULATED application progression (live career sessions only;
replay/demo sessions never reach these tables as eligible).
"""
from __future__ import annotations

import json

PROVENANCE = 'CALCULATED'
GAINS_WINDOW = 5
MAX_TIMELINE = 100


def recent_gains(store, driver_id: str, window: int = GAINS_WINDOW) -> dict:
    """Stable shape:
    {recent_xp, sessions_evaluated, latest_grade, delta_score, provenance,
     sessions:[{session_id, created_at, xp_awarded, xp_by_category{cat:int}, grade, consistency_score,
                consistency_delta, skill_deltas (null: per-session skill snapshots are not stored), pb_events}]}
    Legacy keys (recent_xp, sessions_evaluated, latest_grade, delta_score) are preserved."""
    cards = store.query("SELECT session_id,created_at,xp_awarded,payload FROM career_scorecards WHERE driver_id=? AND status='eligible' "
                        'ORDER BY created_at DESC,session_id LIMIT ?', (driver_id, window + 1))
    shown = cards[:window]
    ids = [c['session_id'] for c in shown]
    by_cat: dict[str, dict[str, int]] = {}
    pbs: dict[str, int] = {}
    if ids:
        marks = ','.join('?' * len(ids))
        for r in store.query(f'SELECT session_id,category,SUM(amount) AS amount FROM career_xp_events WHERE driver_id=? AND session_id IN ({marks}) GROUP BY session_id,category', (driver_id, *ids)):
            by_cat.setdefault(r['session_id'], {})[r['category']] = r['amount']
        for r in store.query("SELECT json_extract(evidence,'$.session_id') AS sid,COUNT(*) AS n FROM career_events WHERE driver_id=? AND kind='PB_SET' "
                             f"AND json_extract(evidence,'$.session_id') IN ({marks}) GROUP BY sid", (driver_id, *ids)):
            pbs[r['sid']] = r['n']
    sessions = []
    for i, card in enumerate(shown):
        ev = json.loads(card['payload']).get('evidence', {})
        score = ev.get('consistency_score')
        prev = json.loads(cards[i + 1]['payload']).get('evidence', {}).get('consistency_score') if i + 1 < len(cards) else None
        sessions.append(dict(session_id=card['session_id'], created_at=card['created_at'], xp_awarded=card['xp_awarded'],
                             xp_by_category=by_cat.get(card['session_id'], {}), grade=ev.get('session_grade'), consistency_score=score,
                             consistency_delta=round(score - prev, 2) if score is not None and prev is not None else None,
                             skill_deltas=None, pb_events=pbs.get(card['session_id'], 0)))
    latest = sessions[0] if sessions else None
    return dict(recent_xp=latest['xp_awarded'] if latest else 0, sessions_evaluated=len(sessions),
                latest_grade=latest['grade'] if latest else None, delta_score=latest['consistency_delta'] if latest else None,
                provenance=PROVENANCE, sessions=sessions)


def timeline(store, driver_id: str, limit: int = 50, cursor: str | None = None) -> dict:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_TIMELINE:
        raise ValueError(f'limit must be between 1 and {MAX_TIMELINE}')
    where, args = 'e.driver_id=?', [driver_id]
    if cursor:
        stamp, sep, eid = cursor.rpartition('|')
        if not sep or not stamp or not eid:
            raise ValueError('Invalid cursor')
        where += ' AND (e.created_at<? OR (e.created_at=? AND e.id<?))'
        args += [stamp, stamp, eid]
    rows = store.query('SELECT e.id,e.kind,e.source,e.source_id,e.provenance,e.evidence,e.confidence,e.created_at,n.title,n.body '
                       f'FROM career_events e LEFT JOIN career_notifications n ON n.id=e.id WHERE {where} '
                       'ORDER BY e.created_at DESC,e.id DESC LIMIT ?', (*args, limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    for r in rows:
        r['evidence'] = json.loads(r['evidence'])
        r['title'] = r['title'] or r['kind'].replace('_', ' ').title()
    return dict(items=rows, next_cursor=f"{rows[-1]['created_at']}|{rows[-1]['id']}" if more and rows else None, provenance=PROVENANCE)


def stats(store, driver_id: str, profile: dict, level: dict) -> dict:
    """Lifetime totals. Every query is indexed by driver_id (career_* driver indexes)."""
    src = store.query("SELECT COUNT(*) AS total,COALESCE(SUM(status='eligible'),0) AS eligible FROM career_sources WHERE driver_id=?", (driver_id,))[0]
    pbs = store.query("SELECT COUNT(*) AS n FROM career_events WHERE driver_id=? AND kind='PB_SET'", (driver_id,))[0]['n']
    tracks = store.query('SELECT COUNT(DISTINCT layout_id) AS n FROM career_track_mastery WHERE driver_id=?', (driver_id,))[0]['n']
    xp = {r['category']: r['amount'] for r in store.query('SELECT category,SUM(amount) AS amount FROM career_xp_events WHERE driver_id=? GROUP BY category', (driver_id,))}
    eligible = int(src['eligible'])
    return dict(sessions_processed=src['total'], eligible_sessions=eligible, excluded_sessions=src['total'] - eligible,
                comparable_laps=profile['comparable_laps'], personal_bests=pbs, tracks_visited=tracks, total_xp=profile['total_xp'],
                level=level['current'], xp_by_category=xp, provenance=PROVENANCE, scope='live career sessions')


def overview(profile: dict, level: dict, titles: dict, badges: list[dict], gains: dict, next_unlock: dict | None) -> dict:
    earned = sorted((b for b in badges if b['unlocked']), key=lambda b: b['earned_at'] or '', reverse=True)
    equipped = next((t for t in titles['titles'] if t['name'] == titles['equipped']), None)
    return dict(profile=dict(id=profile['id'], name=profile['name'], total_xp=profile['total_xp'], eligible_sessions=profile['eligible_sessions'],
                             comparable_laps=profile['comparable_laps']),
                level=level, equipped_title=dict(id=equipped['id'], name=equipped['name']) if equipped else None,
                top_badges=[dict(id=b['id'], name=b['name'], icon=b['icon'], earned_at=b['earned_at']) for b in earned[:3]],
                next_unlock=next_unlock, recent_gains=gains if gains['sessions'] else None, provenance=PROVENANCE)
