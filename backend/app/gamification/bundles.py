"""Versioned career archive transfer. Imported archives never masquerade as live careers."""
import json
import uuid
from datetime import datetime, timezone

MAX_ROWS = 10000
MAX_BYTES = 8 * 1024 * 1024
TABLES = ('career_sources', 'career_xp_events', 'career_skills', 'career_achievements', 'career_scorecards',
          'career_track_mastery', 'career_corner_mastery', 'career_mastery_history', 'career_challenges',
          'career_engineer', 'career_missions', 'career_streaks', 'career_journal')


def export_career(store, driver_id):
    """One WAL read snapshot; no raw telemetry or recorder writer work."""
    queries = {'profile': ('SELECT * FROM career_profiles WHERE id=?', (driver_id,))}
    queries.update({name: (f'SELECT * FROM {name} WHERE driver_id=? LIMIT ?', (driver_id, MAX_ROWS + 1)) for name in TABLES})
    rows = store.read_snapshot(queries)
    if not rows['profile']:
        raise ValueError('Unknown driver')
    if any(len(values) > MAX_ROWS for values in rows.values()):
        raise ValueError('Career exceeds bundle limit; use the database backup for the full archive')
    bundle = {'format': 'gt7-driver-career', 'version': 1, 'provenance': 'local_career_export',
              'exported_at': datetime.now(timezone.utc).isoformat(), 'profile': rows.pop('profile')[0], 'records': rows,
              'telemetry_included': False, 'import_policy': 'Isolated imported archive; cannot earn live rewards'}
    if len(json.dumps(bundle, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError('Career bundle exceeds 8 MiB limit')
    return bundle


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get('format') != 'gt7-driver-career' or bundle.get('version') != 1:
        raise ValueError('Unsupported career bundle format/version')
    try:
        size = len(json.dumps(bundle, allow_nan=False).encode())
    except (TypeError, ValueError):
        raise ValueError('Career bundle must contain finite JSON values') from None
    if size > MAX_BYTES:
        raise ValueError('Career bundle exceeds 8 MiB limit')
    profile, records = bundle.get('profile'), bundle.get('records')
    if not isinstance(profile, dict) or not isinstance(records, dict) or set(records) != set(TABLES):
        raise ValueError('Incomplete career archive')
    if not isinstance(profile.get('name'), str) or not 1 <= len(profile['name'].strip()) <= 80:
        raise ValueError('Invalid archived driver name')
    for key in ('total_xp', 'eligible_sessions', 'comparable_laps'):
        value = profile.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000_000:
            raise ValueError('Invalid archived totals')
    if not isinstance(profile.get('id'), str) or not profile['id']:
        raise ValueError('Archive profile identity is missing')
    for table, items in records.items():
        if not isinstance(items, list) or len(items) > MAX_ROWS or any(not isinstance(item, dict) or item.get('driver_id') != profile['id'] for item in items):
            raise ValueError('Invalid archive record ownership or row count')
    events = records['career_xp_events']
    if any(isinstance(e.get('amount'), bool) or not isinstance(e.get('amount'), int) or not 0 <= e['amount'] <= 1000000 for e in events):
        raise ValueError('Invalid archived XP')
    if sum(e['amount'] for e in events) != profile['total_xp']:
        raise ValueError('Archived XP total does not match its ledger')
    if len({e.get('id') for e in events}) != len(events):
        raise ValueError('Duplicate archived XP identity')
    sources = {s.get('id') for s in records['career_sources']}
    if any(not e.get('source_id') or e['source_id'] not in sources for e in events):
        raise ValueError('Archived XP lacks source evidence')
    for skill in records['career_skills']:
        for key, maximum in [('score', 100), ('confidence', 1)]:
            value = skill.get(key)
            if value is None and key == 'score':
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= maximum:
                raise ValueError('Invalid archived skill')
    return bundle


def import_career(store, bundle):
    """Preserve the original archive intact; no historical events enter reward evaluation.

    The new profile is an explicitly labeled imported archive. Live sessions must
    use a local profile. This prevents edits to a JSON bundle becoming live XP.
    """
    validate_bundle(bundle)
    driver_id = uuid.uuid4().hex
    profile = bundle['profile']
    stamp = datetime.now(timezone.utc).isoformat()
    records = bundle['records']
    def parsed(table, key, limit=200):
        return [json.loads(row[key]) for row in records[table][-limit:]]
    try:
        preview = {'skills': records['career_skills'], 'achievements': [dict(r, evidence=json.loads(r['evidence'])) for r in records['career_achievements'][-200:]],
                   'recent_events': [dict(r, evidence=json.loads(r['evidence']), provenance='imported_profile') for r in records['career_xp_events'][-20:]],
                   'scorecards': [dict(r, status='imported') for r in parsed('career_scorecards', 'payload', 20)],
                   'tracks': parsed('career_track_mastery', 'payload'), 'challenges': [dict(r, status='archived') for r in parsed('career_challenges', 'payload')]}
    except (ValueError, KeyError, TypeError):
        raise ValueError('Invalid nested archive evidence') from None
    def operation(db):
        if db.execute('SELECT COUNT(*) FROM career_profiles').fetchone()[0] >= 100:
            raise ValueError('Profile limit reached')
        db.execute('INSERT INTO career_profiles(id,name,created_at,total_xp,eligible_sessions,comparable_laps) VALUES(?,?,?,?,?,?)',
                   (driver_id, profile['name'], stamp, profile['total_xp'], profile['eligible_sessions'], profile['comparable_laps']))
        db.execute('INSERT INTO career_import_archives VALUES(?,?,?,?,?)', (driver_id, stamp, 'imported_profile', json.dumps(bundle, allow_nan=False), json.dumps(preview, allow_nan=False)))
        return {'driver_id': driver_id, 'id': driver_id, 'name': profile['name'], 'provenance': 'imported_profile', 'live_rewards_enabled': False}
    return store.career_transaction(operation)
