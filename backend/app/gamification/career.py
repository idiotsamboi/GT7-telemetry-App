"""F061/F071/F074/F076/F081/F087: structured, inspectable local learning state.

Engineer missions reference the existing persistent challenge/evaluator. They do
not invent another completion path or confer a second challenge XP reward.
"""
import json
import math

CAREER_LEARNING_DDL = '''
CREATE TABLE IF NOT EXISTS career_engineer(
 driver_id TEXT PRIMARY KEY, focus TEXT NOT NULL DEFAULT 'consistency',
 xp INTEGER NOT NULL DEFAULT 0, memory TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS career_missions(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, challenge_id TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL, completed_at TEXT, source_id TEXT);
CREATE INDEX IF NOT EXISTS career_mission_driver ON career_missions(driver_id,created_at);
CREATE TABLE IF NOT EXISTS career_learning_sources(
 source_id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_learning_driver ON career_learning_sources(driver_id);
CREATE TABLE IF NOT EXISTS career_streaks(
 driver_id TEXT NOT NULL, kind TEXT NOT NULL, current_count INTEGER NOT NULL,
 best_count INTEGER NOT NULL, last_source_id TEXT NOT NULL, reason TEXT,
 PRIMARY KEY(driver_id,kind));
CREATE TABLE IF NOT EXISTS career_journal(
 id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, session_id TEXT, source_id TEXT,
 created_at TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, provenance TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS career_journal_driver ON career_journal(driver_id,created_at);
'''

FOCUSES = ('pace', 'consistency', 'braking', 'cornering', 'fuel', 'strategy', 'track_learning')
SKILL_NAMES = ('Novice', 'Developing', 'Learning', 'Capable', 'Competent', 'Advanced', 'Expert', 'Specialist', 'Elite', 'Master')


def skill_level(xp):
    level = min(10, 1 + int(math.sqrt(max(0, xp) / 100)))
    return {'level': level, 'level_name': SKILL_NAMES[level-1], 'scope': 'application progression category'}


def ensure_engineer(db, driver_id):
    db.execute('INSERT OR IGNORE INTO career_engineer(driver_id) VALUES(?)', (driver_id,))


def update_learning(db, driver_id, source_id, session, evidence, stamp):
    if db.execute('SELECT 1 FROM career_learning_sources WHERE source_id=?', (source_id,)).fetchone():
        return
    ensure_engineer(db, driver_id)
    for mission_id, challenge_id in db.execute('SELECT id,challenge_id FROM career_missions WHERE driver_id=? AND completed_at IS NULL LIMIT 100', (driver_id,)).fetchall():
        row = db.execute("SELECT payload FROM career_challenges WHERE id=? AND driver_id=? AND status='completed'", (challenge_id, driver_id)).fetchone()
        result = json.loads(row[0]).get('completion_evidence') if row else None
        if result and result.get('source_id') == source_id:
            db.execute('UPDATE career_missions SET completed_at=?,source_id=? WHERE id=?', (stamp, source_id, mission_id))
            db.execute('UPDATE career_engineer SET xp=xp+25 WHERE driver_id=?', (driver_id,))
    row = db.execute('SELECT memory FROM career_engineer WHERE driver_id=?', (driver_id,)).fetchone()
    memory = json.loads(row[0])
    memory['last_comparable_session'] = {'session_id': session['id'], 'source_id': source_id, 'layout_id': evidence['layout_id'],
                                         'car_id': evidence['car_id'], 'confidence': min(.85, evidence['comparable_laps']/20)}
    db.execute('UPDATE career_engineer SET memory=? WHERE driver_id=?', (json.dumps(memory), driver_id))
    good = evidence['comparable_laps'] >= 5 and evidence['spread_fraction'] <= .02
    old = db.execute("SELECT current_count,best_count FROM career_streaks WHERE driver_id=? AND kind='consistency_sessions'", (driver_id,)).fetchone()
    count = ((old[0] if old else 0) + 1) if good else 0
    best = max(old[1] if old else 0, count)
    reason = 'Five comparable laps within the application consistency target' if good else 'Session did not meet the five-lap consistency target'
    db.execute("INSERT OR REPLACE INTO career_streaks VALUES(?,'consistency_sessions',?,?,?,?)", (driver_id, count, best, source_id, reason))
    totals = db.execute('SELECT comparable_laps,eligible_sessions,total_xp FROM career_profiles WHERE id=?', (driver_id,)).fetchone()
    # Read after aggregate update in the enclosing atomic transaction.
    definitions = [('FIRST_LAP', 1, 'First comparable lap'), ('TEN_LAPS', 10, 'Ten comparable laps'),
                   ('ONE_HUNDRED_LAPS', 100, 'One hundred comparable laps'), ('THOUSAND_LAPS', 1000, 'One thousand comparable laps')]
    for definition_id, threshold, title in definitions:
        if totals[0] >= threshold:
            db.execute('INSERT OR IGNORE INTO career_achievements VALUES(?,?,?,?,?,?)', (driver_id, definition_id, title, stamp, source_id,
                       json.dumps({'source': 'calculated', 'provenance': 'live', 'source_id': source_id, 'comparable_laps': totals[0], 'threshold': threshold, 'official_validity': 'unknown'})))
    db.execute('INSERT INTO career_learning_sources VALUES(?,?,?)', (source_id, driver_id, json.dumps({'confidence': min(.85, evidence['comparable_laps']/20), 'consistency_streak': count})))


def engineer(store, driver_id, challenges):
    rows = store.query('SELECT * FROM career_engineer WHERE driver_id=?', (driver_id,))
    row = rows[0] if rows else {'focus': 'consistency', 'xp': 0, 'memory': '{}'}
    missions = store.query('SELECT * FROM career_missions WHERE driver_id=? ORDER BY created_at DESC LIMIT 100', (driver_id,))
    by_id = {c['id']: c for c in challenges}
    for mission in missions:
        challenge = by_id.get(mission['challenge_id'])
        mission['challenge'] = challenge
        mission['status'] = 'completed' if mission['completed_at'] else (challenge['status'] if challenge else 'unavailable')
    target = next((c for c in challenges if c['status'] == 'accepted'), None) or next((c for c in challenges if c['status'] == 'offered'), None)
    return {'focus': row['focus'], 'xp': row['xp'], 'level': min(100, 1 + row['xp']//100), 'memory': json.loads(row['memory']),
            'missions': missions, 'briefing': {'title': target['title'] if target else 'Establish comparable lap evidence',
            'why': target['why'] if target else 'A reliable reference needs complete live laps with stable layout and car identity.',
            'challenge_id': target['id'] if target else None, 'confidence': target['confidence'] if target else None,
            'source': 'deterministic_stored_evidence',
            'focus_note': 'Only measurable lap practice and consistency missions are currently available.'}}


def chapters(profile, challenges):
    completed = sum(c['status'] == 'completed' for c in challenges)
    definitions = [('foundations', 'Foundations', 2, 0), ('consistency', 'Consistency', 10, 1),
                   ('deliberate_practice', 'Deliberate practice', 25, 3)]
    items = [{'id': key, 'title': title, 'required_laps': laps, 'required_challenges': count,
              'completed': profile['comparable_laps'] >= laps and completed >= count}
             for key, title, laps, count in definitions]
    return {'chapters': items, 'current': next((i['id'] for i in items if not i['completed']), 'foundation_curriculum_complete'),
            'completed_challenges': completed, 'scope': 'Initial measurable lap-practice curriculum; advanced strategy and racecraft chapters unavailable'}
