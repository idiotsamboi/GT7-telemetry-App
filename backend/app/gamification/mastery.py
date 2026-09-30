"""F011–F025: conservative, versioned mastery from eligible stored comparisons.

Unknown components stay null. An observed component score is not full mastery.
Car-specific pace baselines are never mixed. No automatic mastery decay.
"""
import json
import math
from statistics import median, pstdev

from .corner_insights import apply_corner_progress
from .track_components import corner_coverage, discovery_level, strategy_component, training_component

DEFAULT_WEIGHTS = {'pace': .25, 'consistency': .20, 'corners': .25, 'training': .15, 'strategy': .15}

MASTERY_DDL = '''
CREATE TABLE IF NOT EXISTS career_track_mastery(
 driver_id TEXT NOT NULL, layout_id TEXT NOT NULL, car_id INTEGER NOT NULL,
 updated_at TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(driver_id,layout_id,car_id));
CREATE INDEX IF NOT EXISTS career_track_layout ON career_track_mastery(driver_id,layout_id);
CREATE TABLE IF NOT EXISTS career_corner_mastery(
 driver_id TEXT NOT NULL, layout_id TEXT NOT NULL, car_id INTEGER NOT NULL, corner_id TEXT NOT NULL,
 updated_at TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(driver_id,layout_id,car_id,corner_id));
CREATE INDEX IF NOT EXISTS career_corner_layout ON career_corner_mastery(driver_id,layout_id);
CREATE TABLE IF NOT EXISTS career_mastery_history(
 source_id TEXT NOT NULL, driver_id TEXT NOT NULL, layout_id TEXT NOT NULL,
 car_id INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(source_id,layout_id,car_id));
CREATE INDEX IF NOT EXISTS career_mastery_history_driver ON career_mastery_history(driver_id,created_at);
CREATE TABLE IF NOT EXISTS career_spatial_evidence(
 session_id TEXT NOT NULL, lap_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(session_id,lap_id));
'''


def components_score(components: dict, weights: dict | None = None) -> dict:
    weights = DEFAULT_WEIGHTS if weights is None else weights
    if set(weights) != set(DEFAULT_WEIGHTS) or any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0 for w in weights.values()):
        raise ValueError('Mastery weights must be finite positive component weights')
    known = {k: v for k, v in components.items() if k in weights and v is not None}
    if any(not math.isfinite(v) or not 0 <= v <= 100 for v in known.values()):
        raise ValueError('Mastery components must be in 0–100')
    coverage = sum(weights[k] for k in known) / sum(weights.values())
    observed = sum(v * weights[k] for k, v in known.items()) / sum(weights[k] for k in known) if known else None
    return {'overall_score': round(observed, 2) if observed is not None and len(known) == len(weights) else None,
            'observed_component_score': round(observed, 2) if observed is not None else None,
            'component_coverage': round(coverage, 3), 'weights': weights}


def capture_spatial(lap, reference, corners: list[dict], lap_id: str, reference_lap_id: str) -> dict | None:
    """Summarize existing distance-aligned traces; never store a second sample series."""
    if not reference_lap_id or lap.layout_id != reference.layout_id or lap.car_id != reference.car_id or lap.length_m != reference.length_m:
        return None
    items = []
    for corner in corners[:100]:
        a, b = (corner['s_start'] - 150) % lap.length_m, (corner['s_end'] + 100) % lap.length_m
        if a >= b or not isinstance(corner.get('id'), str):
            continue
        values = (lap.time_at(a), lap.time_at(b), reference.time_at(a), reference.time_at(b))
        if any(v is None or not math.isfinite(v) for v in values):
            continue
        start, end, ref_start, ref_end = values
        if end <= start or ref_end <= ref_start:
            continue
        items.append({'corner_id': corner['id'], 'name': corner.get('name') or corner['id'],
                      'segment_ms': round((end-start)*1000, 3), 'reference_segment_ms': round((ref_end-ref_start)*1000, 3),
                      'loss_s': round(end-start-ref_end+ref_start, 4), 'confidence': .7,
                      'comparison_window_m': [a, b]})
    return {'lap_id': lap_id, 'reference_lap_id': reference_lap_id, 'layout_id': lap.layout_id,
            'car_id': lap.car_id, 'source': 'calculated', 'method': 'existing_s_aligned_trace', 'items': items} if items else None


def update_mastery(db, driver_id, source_id, session, evidence, context, stamp):
    layout, car = evidence['layout_id'], evidence['car_id']
    if session.get('provenance') != 'live' or not context.get('integrity') or not layout or car is None:
        return None
    if db.execute('SELECT 1 FROM career_mastery_history WHERE source_id=?', (source_id,)).fetchone():
        return None
    ids = set(evidence['comparable_lap_ids'])
    laps = [lap for lap in session['laps'] if lap['id'] in ids]
    durations = [lap['duration_ms'] for lap in laps]
    row = db.execute('SELECT payload FROM career_track_mastery WHERE driver_id=? AND layout_id=? AND car_id=?', (driver_id, layout, car)).fetchone()
    previous = json.loads(row[0]) if row else None
    current_pb = min(durations)
    baseline = previous['pb_ms'] if previous else None
    pb = min(baseline, current_pb) if baseline is not None else current_pb
    pace = min(100, 100 * baseline / median(durations)) if baseline is not None else None
    corners_updated = 0
    touched = {}
    for lap_id, spatial in context.get('spatial', {}).items():
        if lap_id not in ids or spatial.get('reference_lap_id') not in ids or spatial.get('layout_id') != layout or spatial.get('car_id') != car or spatial.get('source') != 'calculated':
            continue
        for item in spatial.get('items', [])[:100]:
            corner_id = item.get('corner_id')
            duration = item.get('segment_ms')
            confidence = item.get('confidence')
            if not isinstance(corner_id, str) or not corner_id or not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0 or not isinstance(confidence, (float, int)) or not .5 <= confidence <= 1:
                continue
            old = db.execute('SELECT payload FROM career_corner_mastery WHERE driver_id=? AND layout_id=? AND car_id=? AND corner_id=?', (driver_id, layout, car, corner_id)).fetchone()
            old = json.loads(old[0]) if old else {}
            touched.setdefault(corner_id, old.get('score'))
            history = (old.get('recent_segment_ms', []) + [duration])[-20:]
            count = old.get('sample_count', 0) + 1
            # Until three independent laps exist, report timing evidence only.
            consistency = max(0, 100 * (1 - pstdev(history) / median(history) / .1)) if len(history) >= 3 else None
            relative_pace = min(100, 100 * min(history) / median(history)) if len(history) >= 3 else None
            score = round((consistency + relative_pace) / 2, 2) if consistency is not None else None
            mastered = old.get('mastered', False) or (count >= 20 and score is not None and score >= 90)
            payload = {'corner_id': corner_id, 'name': item.get('name') or corner_id, 'layout_id': layout, 'car_id': car,
                       'score': score, 'confidence': round(min(.85, count/30) * confidence, 3), 'sample_count': count,
                       'current_loss_s': item.get('loss_s'), 'reference_lap_id': spatial['reference_lap_id'],
                       'reference_segment_ms': item.get('reference_segment_ms'), 'consistency': consistency,
                       'recent_segment_ms': history, 'mastered': mastered, 'updated_at': stamp,
                       'source_id': source_id, 'lap_id': lap_id, 'algorithm_version': 1,
                       'method': 'Player-relative segment pace and repeatability; application interpretation',
                       'comparison_window_m': item.get('comparison_window_m')}
            db.execute('INSERT OR REPLACE INTO career_corner_mastery VALUES(?,?,?,?,?,?,?)', (driver_id, layout, car, corner_id, stamp, source_id, json.dumps(payload)))
            corners_updated += 1

    apply_corner_progress(db, driver_id, layout, car, source_id, touched, stamp)   # F029/F030, savepoint-isolated

    # Query all corner mastery records for this layout & car to compute whole-circuit coverage (F018)
    all_corners = [json.loads(r[0]) for r in db.execute('SELECT payload FROM career_corner_mastery WHERE driver_id=? AND layout_id=? AND car_id=?', (driver_id, layout, car)).fetchall()]
    total_corners_count = len(all_corners)
    sampled_corners = [c for c in all_corners if c.get('sample_count', 0) >= 3]
    corner_scores = [c['score'] for c in sampled_corners if c.get('score') is not None]
    avg_corner_score = round(sum(corner_scores) / len(corner_scores), 2) if corner_scores else None
    coverage_pct = round(100.0 * len(sampled_corners) / total_corners_count, 1) if total_corners_count > 0 else 0.0

    corner_coverage_info = {'total_cataloged': total_corners_count, 'sampled': len(sampled_corners), 'percentage': coverage_pct} if total_corners_count > 0 else None
    catalogue = (context.get('corner_catalogue') or {}).get(layout)
    strategy = strategy_component((previous or {}).get('strategy_state', {}).get('recent_fuel_l'), laps)
    training = training_component((context.get('training') or {}).get(layout))

    components = {'pace': round(pace, 2) if pace is not None else None, 'consistency': evidence['consistency_score'],
                  'corners': avg_corner_score, 'training': training['score'], 'strategy': strategy['score']}
    payload = {'layout_id': layout, 'car_id': car, 'first_visit': previous['first_visit'] if previous else stamp,
               'last_visit': stamp, 'visit_count': (previous['visit_count'] if previous else 0) + 1,
               'lap_count': (previous['lap_count'] if previous else 0) + len(laps),
               'first_recorded_ms': previous['first_recorded_ms'] if previous else durations[0],
               'pb_ms': pb, 'previous_pb_ms': baseline if baseline is not None and pb < baseline else (previous.get('previous_pb_ms') if previous else None),
               'pb_improvement_ms': baseline - pb if baseline is not None else None,
               'largest_pb_improvement_ms': max(previous.get('largest_pb_improvement_ms') or 0, baseline - pb) if previous and baseline is not None else None,
               'components': components, **components_score(components), 'confidence': round(min(.85, len(laps)/20), 3),
               'mastery_level': 'Visited', 'mastered': False, 'source_id': source_id, 'algorithm_version': 1,
               'corner_observations_updated': corners_updated, 'corner_coverage_total': corner_coverage_info,
               'comparison': 'same authoritative layout and car; calculated application-comparable laps',
               'corner_coverage': corner_coverage(all_corners, catalogue),
               'component_details': {'strategy': {k: v for k, v in strategy.items() if k != 'recent_fuel_l'}, 'training': {**training, 'scope': 'layout-wide user training captures; not per car, not provenance-gated'}},
               'strategy_state': {'recent_fuel_l': strategy['recent_fuel_l']}}
    payload['score_confidence'] = round(payload['confidence'] * payload['component_coverage'], 3)
    payload['previous_mastery_level'] = (previous or {}).get('mastery_level')
    payload['mastery_level'] = discovery_level(payload, payload['previous_mastery_level'])
    payload['mastered'] = payload['mastery_level'] == 'Mastered'
    db.execute('INSERT OR REPLACE INTO career_track_mastery VALUES(?,?,?,?,?,?)', (driver_id, layout, car, stamp, source_id, json.dumps(payload)))
    db.execute('INSERT INTO career_mastery_history VALUES(?,?,?,?,?,?)', (source_id, driver_id, layout, car, stamp, json.dumps(payload)))
    return payload


def tracks(store, driver_id):
    return [json.loads(r['payload']) for r in store.query('SELECT payload FROM career_track_mastery WHERE driver_id=? ORDER BY updated_at DESC LIMIT 200', (driver_id,))]


def corners(store, driver_id, layout_id):
    return [json.loads(r['payload']) for r in store.query('SELECT payload FROM career_corner_mastery WHERE driver_id=? AND layout_id=? ORDER BY car_id,corner_id LIMIT 500', (driver_id, layout_id))]
