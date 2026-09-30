"""Career writes run as isolated jobs on the existing recorder writer.

No raw telemetry queries, external writes, or second writer connection. Each
reward transaction includes its source, XP, derived counters and scorecard.
"""
from datetime import datetime, timezone
import json
import hashlib
import uuid
from .models import DriverProfile, SessionScorecard
from .scoring import ALGORITHM_VERSION, MAX_LAPS, SKILLS, LevelCurve, evaluate, update_skill
from .mastery import update_mastery, tracks, corners
from .corner_insights import insights as corner_insights_for
from .rewards import apply_track_rewards
from .challenges import advance_challenges, list_challenges, transition_challenge
from .career import update_learning, engineer, chapters, skill_level, ensure_engineer, FOCUSES
from .bundles import export_career, import_career
from .notifications import list_notifications, mark_read
from .events import write_events_isolated
from . import badges as badges_mod, summary, titles as titles_mod


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


def rowdict(cursor):
    row = cursor.fetchone()
    return dict(zip((c[0] for c in cursor.description), row)) if row else None


class CareerRepository:
    def __init__(self, store):
        self.store = store
        self.curve = LevelCurve()

    def ensure_default_profile(self) -> DriverProfile:
        def operation(db):
            settings = db.execute('SELECT active_driver_id FROM career_settings WHERE singleton=1').fetchone()
            if settings and settings[0]:
                profile = rowdict(db.execute('SELECT *,id AS driver_id,name AS display_name FROM career_profiles WHERE id=?', (settings[0],)))
                if profile: return profile
            profile = rowdict(db.execute('SELECT *,id AS driver_id,name AS display_name FROM career_profiles ORDER BY created_at,id LIMIT 1'))
            if profile is None:
                profile_id = uuid.uuid4().hex
                db.execute('INSERT INTO career_profiles(id,name,created_at) VALUES(?,?,?)', (profile_id, 'Local driver', now()))
                profile = rowdict(db.execute('SELECT *,id AS driver_id,name AS display_name FROM career_profiles WHERE id=?', (profile_id,)))
            db.execute('INSERT INTO career_settings(singleton,active_driver_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET active_driver_id=excluded.active_driver_id', (profile['id'],))
            return profile
        return self.store.career_transaction(operation)

    def list_profiles(self) -> list[DriverProfile]:
        return self.store.query('SELECT *,id AS driver_id,name AS display_name FROM career_profiles ORDER BY created_at,id LIMIT 100')

    def active_profile(self) -> DriverProfile:
        rows = self.store.query('SELECT p.*,p.id AS driver_id,p.name AS display_name FROM career_profiles p JOIN career_settings s ON p.id=s.active_driver_id WHERE s.singleton=1')
        return rows[0] if rows else self.ensure_default_profile()

    def active_profile_id(self) -> str:
        return self.active_profile()['id']

    def _profile(self, driver_id=None):
        if driver_id is None: return self.active_profile()
        rows = self.store.query('SELECT *,id AS driver_id,name AS display_name FROM career_profiles WHERE id=?', (driver_id,))
        if not rows: raise ValueError('Unknown driver profile')
        return rows[0]

    def create_profile(self, name: str) -> DriverProfile:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80: raise ValueError('Driver name must contain 1 to 80 characters')
        profile_id = uuid.uuid4().hex
        def operation(db):
            if db.execute('SELECT COUNT(*) FROM career_profiles').fetchone()[0] >= 100: raise ValueError('Profile limit reached')
            db.execute('INSERT INTO career_profiles(id,name,created_at) VALUES(?,?,?)', (profile_id, name.strip(), now()))
            return rowdict(db.execute('SELECT *,id AS driver_id,name AS display_name FROM career_profiles WHERE id=?', (profile_id,)))
        return self.store.career_transaction(operation)

    def select_profile(self, driver_id: str) -> DriverProfile:
        def operation(db):
            profile = rowdict(db.execute('SELECT *,id AS driver_id,name AS display_name FROM career_profiles WHERE id=?', (driver_id,)))
            if not profile: raise ValueError('Unknown driver profile')
            db.execute('INSERT INTO career_settings(singleton,active_driver_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET active_driver_id=excluded.active_driver_id', (driver_id,))
            return profile
        return self.store.career_transaction(operation)

    def settings(self):
        self.active_profile()
        row = self.store.query('SELECT active_driver_id,enabled FROM career_settings WHERE singleton=1')[0]
        row['enabled'] = bool(row['enabled'])
        return row

    def update_settings(self, changes: dict):
        if set(changes) - {'enabled'} or ('enabled' in changes and not isinstance(changes['enabled'], bool)):
            raise ValueError('Only boolean enabled may be updated')
        self.active_profile()
        if 'enabled' in changes:
            self.store.career_transaction(lambda db: db.execute('UPDATE career_settings SET enabled=? WHERE singleton=1', (int(changes['enabled']),)).rowcount)
        return self.settings()

    def bind_session(self, session_id: str, driver_id: str, provenance: str, *, require_finalization=False):
        def operation(db):
            if not db.execute('SELECT 1 FROM career_profiles WHERE id=?', (driver_id,)).fetchone(): raise ValueError('Unknown driver profile')
            enabled = db.execute('SELECT enabled FROM career_settings WHERE singleton=1').fetchone()
            reason = ('awaiting_finalization' if require_finalization else None) if enabled and enabled[0] else 'career_disabled_at_start'
            if db.execute('SELECT 1 FROM career_import_archives WHERE driver_id=?', (driver_id,)).fetchone():
                reason = 'imported_profile_archive'
            db.execute('INSERT OR IGNORE INTO career_bindings VALUES(?,?,?,?,?)', (session_id, driver_id, provenance, now(), reason))
            return rowdict(db.execute('SELECT * FROM career_bindings WHERE session_id=?', (session_id,)))
        return self.store.career_transaction(operation)

    def record_lap_context(self, session_id: str, lap_id: str, context: dict):
        payload = encode(context)
        if len(payload) > 8192: raise ValueError('Lap context too large')
        def operation(db):
            if not db.execute('SELECT 1 FROM career_bindings WHERE session_id=?', (session_id,)).fetchone(): raise ValueError('Session has no driver attribution')
            if db.execute('SELECT COUNT(*) FROM career_lap_context WHERE session_id=?', (session_id,)).fetchone()[0] >= MAX_LAPS:
                db.execute("UPDATE career_bindings SET invalid_reason='lap_limit_exceeded' WHERE session_id=?", (session_id,))
                return False
            old = db.execute('SELECT evidence FROM career_lap_context WHERE session_id=? AND lap_id=?', (session_id, lap_id)).fetchone()
            if old and old[0] != payload:
                db.execute("UPDATE career_bindings SET invalid_reason='conflicting_lap_context' WHERE session_id=?", (session_id,))
                return False
            db.execute('INSERT OR IGNORE INTO career_lap_context VALUES(?,?,?)', (session_id, lap_id, payload))
            return True
        return self.store.career_transaction(operation)

    def invalidate_session(self, session_id: str, reason='incomplete_capture'):
        return self.store.career_transaction(lambda db: db.execute('UPDATE career_bindings SET invalid_reason=? WHERE session_id=?', (str(reason)[:200], session_id)).rowcount)

    def finalize_context(self, session_id: str, context: dict):
        """A durable receipt is required before background recovery can reward a session."""
        payload = encode(context)
        def operation(db):
            row = db.execute('SELECT invalid_reason FROM career_bindings WHERE session_id=?', (session_id,)).fetchone()
            if not row:
                raise ValueError('Session attribution is missing')
            old = db.execute("SELECT evidence FROM career_lap_context WHERE session_id=? AND lap_id='__session__'", (session_id,)).fetchone()
            if old and old[0] != payload:
                db.execute("UPDATE career_bindings SET invalid_reason='conflicting_finalization' WHERE session_id=?", (session_id,))
                return
            db.execute("INSERT OR IGNORE INTO career_lap_context VALUES(?,'__session__',?)", (session_id, payload))
            if not context.get('integrity'):
                db.execute("UPDATE career_bindings SET invalid_reason='incomplete_capture' WHERE session_id=?", (session_id,))
            elif row[0] == 'awaiting_finalization':
                db.execute('UPDATE career_bindings SET invalid_reason=NULL WHERE session_id=?', (session_id,))
        return self.store.career_transaction(operation)

    def record_spatial_context(self, session_id: str, spatial: dict):
        payload = encode(spatial)
        if len(payload) > 64000 or not isinstance(spatial.get('lap_id'), str):
            raise ValueError('Invalid spatial evidence')
        def operation(db):
            if not db.execute('SELECT 1 FROM career_bindings WHERE session_id=?', (session_id,)).fetchone():
                raise ValueError('Session has no driver attribution')
            if db.execute('SELECT COUNT(*) FROM career_spatial_evidence WHERE session_id=?', (session_id,)).fetchone()[0] >= MAX_LAPS:
                return False
            db.execute('INSERT OR IGNORE INTO career_spatial_evidence VALUES(?,?,?)', (session_id, spatial['lap_id'], payload))
            return True
        return self.store.career_transaction(operation)

    def pending_sessions(self, limit=100):
        return self.store.query('SELECT b.* FROM career_bindings b JOIN sessions s ON s.id=b.session_id LEFT JOIN career_sources c ON c.session_id=b.session_id WHERE s.ended IS NOT NULL AND c.id IS NULL ORDER BY b.created_at LIMIT ?', (max(1, min(int(limit), 200)),))

    def session_context(self, session_id: str):
        rows = self.store.query('SELECT lap_id,evidence FROM career_lap_context WHERE session_id=? LIMIT ?', (session_id, MAX_LAPS + 1))
        binding = self.store.query('SELECT invalid_reason FROM career_bindings WHERE session_id=?', (session_id,))
        spatial = self.store.query('SELECT lap_id,payload FROM career_spatial_evidence WHERE session_id=? LIMIT ?', (session_id, MAX_LAPS))
        contexts = {r['lap_id']: json.loads(r['evidence']) for r in rows}
        finalized = contexts.pop('__session__', {})
        return dict(laps=contexts, spatial={r['lap_id']: json.loads(r['payload']) for r in spatial},
                    features=finalized.get('features', {}),
                    integrity=bool(binding) and not binding[0]['invalid_reason'], truncated=len(contexts) > MAX_LAPS)

    def process_session(self, session: dict, driver_id: str, context: dict) -> SessionScorecard:
        session_id = session['id']
        # Bounded CPU evaluation occurs before entering the recorder transaction.
        analysis = evaluate(session, context)
        stamp = now()
        source_id = 'career:v1:' + session_id
        comparable_ids = set(analysis['evidence']['comparable_lap_ids'])
        fingerprint = hashlib.sha256(encode(dict(layout_id=analysis['evidence']['layout_id'], car_id=analysis['evidence']['car_id'],
            durations=sorted(lap['duration_ms'] for lap in session.get('laps', [])[:MAX_LAPS] if lap.get('id') in comparable_ids))).encode()).hexdigest()
        def operation(db):
            previous = db.execute('SELECT payload FROM career_scorecards WHERE session_id=?', (session_id,)).fetchone()
            if previous:
                prior = json.loads(previous[0])
                if prior['driver_id'] != driver_id: raise ValueError('Session attribution mismatched')
                return prior
            binding = rowdict(db.execute('SELECT * FROM career_bindings WHERE session_id=?', (session_id,)))
            if not binding or binding['driver_id'] != driver_id: raise ValueError('Session attribution missing or mismatched')
            # Persisted session and captured context must agree with the bounded
            # work item. This blocks caller metadata from laundering a replay.
            persisted = rowdict(db.execute('SELECT status,ended,provenance FROM sessions WHERE id=?', (session_id,)))
            if not persisted or not persisted['ended']: raise ValueError('Session is not persisted and finalized')
            exclusions = list(analysis['exclusions'])
            enabled = db.execute('SELECT enabled FROM career_settings WHERE singleton=1').fetchone()
            if not enabled or not enabled[0]: exclusions.append('career_disabled')
            if db.execute('SELECT 1 FROM career_reward_guards WHERE driver_id=? AND fingerprint=?', (driver_id, fingerprint)).fetchone(): exclusions.append('duplicate_session_evidence')
            if persisted['status'] != 'completed': exclusions.append('session_not_finalized_completed')
            if persisted['provenance'] != 'live' or binding['provenance'] != 'live': exclusions.append('non_live_source')
            if binding['invalid_reason']: exclusions.append(binding['invalid_reason'])
            if db.execute('SELECT 1 FROM career_import_archives WHERE driver_id=?', (driver_id,)).fetchone():
                exclusions.append('imported_profile_archive')
            stored_laps = {r[0]: json.loads(r[1]) for r in db.execute('SELECT id,payload FROM laps WHERE session=? LIMIT ?', (session_id, MAX_LAPS + 1))}
            input_laps = {lap.get('id'): lap for lap in session.get('laps', [])[:MAX_LAPS]}
            if len(stored_laps) != len(session.get('laps', [])): exclusions.append('incomplete_recorded_laps')
            for lap_id in analysis['evidence']['comparable_lap_ids']:
                if stored_laps.get(lap_id) != input_laps.get(lap_id): exclusions.append('unpersisted_lap_evidence'); break
                captured = db.execute('SELECT evidence FROM career_lap_context WHERE session_id=? AND lap_id=?', (session_id, lap_id)).fetchone()
                if not captured or json.loads(captured[0]) != context.get('laps', {}).get(lap_id): exclusions.append('unpersisted_lap_identity'); break
            if len(stored_laps) > MAX_LAPS: exclusions.append('lap_limit_exceeded')
            status = 'excluded' if exclusions else analysis['status']
            evidence = analysis['evidence']
            exclusions = list(dict.fromkeys(exclusions))
            db.execute('INSERT INTO career_sources VALUES(?,?,?,?,?,?,?,?)', (source_id, session_id, driver_id, stamp, persisted['provenance'], ALGORITHM_VERSION, status, encode(dict(**evidence, exclusions=exclusions))))
            total = 0
            level_before = level_after = None
            if status == 'eligible':
                xp_before = db.execute('SELECT total_xp FROM career_profiles WHERE id=?', (driver_id,)).fetchone()[0]
                db.execute('INSERT INTO career_reward_guards VALUES(?,?,?)', (driver_id, fingerprint, source_id))
                for reward in analysis['rewards']:
                    guard = source_id + ':' + reward['category']
                    db.execute('INSERT INTO career_xp_events VALUES(?,?,?,?,?,?,?,?,?)', (guard, guard, driver_id, session_id, source_id, reward['category'], reward['amount'], stamp, encode(evidence)))
                    total += reward['amount']
                # Spatial evidence is taken from durable server records, never the caller's claims.
                captured_spatial = {r[0]: json.loads(r[1]) for r in db.execute('SELECT lap_id,payload FROM career_spatial_evidence WHERE session_id=? LIMIT ?', (session_id, MAX_LAPS))}
                measured_context = {**context, 'spatial': captured_spatial if context.get('features', {}).get('corner_mastery', True) else {}}
                if context.get('features', {}).get('track_mastery', True):
                    mastered = update_mastery(db, driver_id, source_id, session, evidence, measured_context, stamp)
                    if mastered:
                        total += apply_track_rewards(db, driver_id, source_id, session_id, mastered, stamp, persisted['provenance'])
                if context.get('features', {}).get('dynamic_challenges', True):
                    total += advance_challenges(db, driver_id, source_id, session, evidence, measured_context, stamp)
                db.execute('UPDATE career_profiles SET total_xp=total_xp+?,eligible_sessions=eligible_sessions+1,comparable_laps=comparable_laps+? WHERE id=?', (total, evidence['comparable_laps'], driver_id))
                level_before = self.curve.progress(xp_before)['current']
                level_after = self.curve.progress(db.execute('SELECT total_xp FROM career_profiles WHERE id=?', (driver_id,)).fetchone()[0])['current']
                if context.get('features', {}).get('engineer_missions', True):
                    update_learning(db, driver_id, source_id, session, evidence, stamp)
                old = db.execute("SELECT score,evidence_count,xp FROM career_skills WHERE driver_id=? AND category='consistency'", (driver_id,)).fetchone()
                score, confidence, count = update_skill(old[0] if old else None, old[1] if old else 0, evidence['consistency_score'], evidence['comparable_laps'])
                skill_xp = (old[2] if old else 0) + sum(r['amount'] for r in analysis['rewards'] if r['category'] == 'consistency')
                db.execute("INSERT INTO career_skills VALUES(?,'consistency',?,?,?,?,?) ON CONFLICT(driver_id,category) DO UPDATE SET score=excluded.score,confidence=excluded.confidence,xp=excluded.xp,evidence_count=excluded.evidence_count,source_id=excluded.source_id", (driver_id, score, confidence, skill_xp, count, source_id))
                db.execute('INSERT OR IGNORE INTO career_achievements VALUES(?,?,?,?,?,?)', (driver_id, 'first_comparable_session_v1', 'First comparable session', stamp, source_id, encode(evidence)))
            if level_before is not None:
                evidence = dict(evidence, level_before=level_before, level_after=level_after)
            scorecard = dict(session_id=session_id, driver_id=driver_id, created_at=stamp, status=status, xp_awarded=total, exclusions=exclusions, evidence=evidence)
            db.execute('INSERT INTO career_scorecards VALUES(?,?,?,?,?,?)', (session_id, driver_id, stamp, status, total, encode(scorecard)))
            if status == 'eligible':   # same transaction as the XP; savepoint-isolated so XP survives an event failure
                write_events_isolated(db, scorecard, stamp)
            return scorecard
        return self.store.career_transaction(operation)

    def notifications(self, driver_id=None, limit=50):
        return list_notifications(self.store, self._profile(driver_id)['id'], limit)

    def mark_notification_read(self, notification_id: str, driver_id=None):
        return mark_read(self.store, self._profile(driver_id)['id'], notification_id, now())

    def history(self, driver_id=None, limit=50):
        driver_id = self._profile(driver_id)['id']
        rows = self.store.query('SELECT id,driver_id,session_id,source_id,category,amount,created_at,evidence FROM career_xp_events WHERE driver_id=? ORDER BY created_at DESC,id LIMIT ?', (driver_id, max(1, min(int(limit), 200))))
        for row in rows: row['evidence'] = json.loads(row['evidence'])
        return rows

    def skills(self, driver_id=None):
        driver_id = self._profile(driver_id)['id']
        rows = {r['category']: r for r in self.store.query('SELECT category,score,confidence,xp,evidence_count,source_id FROM career_skills WHERE driver_id=?', (driver_id,))}
        result = [rows.get(category, dict(category=category, score=None, confidence=0.0, xp=0, evidence_count=0, source_id=None)) for category in SKILLS]
        for skill in result:
            skill.update(skill_level(skill['xp']))
            source = self.store.query('SELECT evidence,provenance FROM career_sources WHERE id=?', (skill['source_id'],)) if skill['source_id'] else []
            skill['evidence'] = json.loads(source[0]['evidence']) if source else None
        return result

    def achievements(self, driver_id=None):
        driver_id = self._profile(driver_id)['id']
        rows = self.store.query('SELECT definition_id,title,earned_at,source_id,evidence FROM career_achievements WHERE driver_id=? ORDER BY earned_at DESC LIMIT 200', (driver_id,))
        for row in rows: row['evidence'] = json.loads(row['evidence'])
        return rows

    def tracks(self, driver_id=None):
        return tracks(self.store, self._profile(driver_id)['id'])

    def corners(self, layout_id, driver_id=None):
        return corners(self.store, self._profile(driver_id)['id'], layout_id)

    def corner_insights(self, layout_id, car_id, driver_id=None):
        """F026-F030 bundle for one layout and car; fields lacking supported evidence are null."""
        if not isinstance(layout_id, str) or not layout_id.strip() or len(layout_id) > 120:
            raise ValueError('layout_id is required')
        if isinstance(car_id, bool) or not isinstance(car_id, int) or car_id <= 0:
            raise ValueError('car_id must be a positive integer')
        return corner_insights_for(self.store, self._profile(driver_id)['id'], layout_id, car_id)

    def challenges(self, driver_id=None):
        return list_challenges(self.store, self._profile(driver_id)['id'])

    def challenge_action(self, challenge_id, action, driver_id=None):
        driver_id = self._profile(driver_id)['id']
        return self.store.career_transaction(lambda db: transition_challenge(db, driver_id, challenge_id, action, now()))

    def engineer(self, driver_id=None):
        driver_id = self._profile(driver_id)['id']
        return engineer(self.store, driver_id, self.challenges(driver_id))

    def career(self, driver_id=None):
        profile = self._profile(driver_id)
        return chapters(profile, self.challenges(profile['id']))

    def start_mission(self, challenge_id, driver_id=None):
        driver_id = self._profile(driver_id)['id']
        stamp = now()
        def operation(db):
            challenge = transition_challenge(db, driver_id, challenge_id, 'accept', stamp)
            ensure_engineer(db, driver_id)
            mission_id = 'mission:' + challenge_id
            db.execute('INSERT OR IGNORE INTO career_missions(id,driver_id,challenge_id,created_at) VALUES(?,?,?,?)', (mission_id, driver_id, challenge_id, stamp))
            return {'id': mission_id, 'challenge': challenge}
        return self.store.career_transaction(operation)

    def set_focus(self, focus, driver_id=None):
        if focus not in FOCUSES:
            raise ValueError('Unknown focus')
        driver_id = self._profile(driver_id)['id']
        def operation(db):
            ensure_engineer(db, driver_id)
            db.execute('UPDATE career_engineer SET focus=? WHERE driver_id=?', (focus, driver_id))
        self.store.career_transaction(operation)
        return self.engineer(driver_id)

    def clear_memory(self, driver_id=None):
        driver_id = self._profile(driver_id)['id']
        self.store.career_transaction(lambda db: db.execute("UPDATE career_engineer SET memory='{}' WHERE driver_id=?", (driver_id,)).rowcount)
        return {'deleted': True}

    def streaks(self, driver_id=None):
        return self.store.query('SELECT * FROM career_streaks WHERE driver_id=?', (self._profile(driver_id)['id'],))

    def _level(self, profile):
        return self.curve.progress(profile['total_xp'])

    def titles(self, driver_id=None):
        """F005: {equipped, titles:[{id,name,description,stage,unlocked,criteria,progress,evidence}]}."""
        profile = self._profile(driver_id)
        ach = {a['definition_id'] for a in self.achievements(profile['id'])}
        evaluated = titles_mod.evaluate_titles(titles_mod.build_stats(profile, self._level(profile)['current'], ach))
        return {'equipped': profile.get('current_title') or titles_mod.BY_ID[titles_mod.DEFAULT_TITLE_ID].name, 'titles': evaluated,
                'provenance': titles_mod.PROVENANCE}

    def equip_title(self, title_name: str, driver_id=None):
        profile = self._profile(driver_id)
        target = titles_mod.resolve(title_name)
        state = next(t for t in self.titles(profile['id'])['titles'] if t['id'] == target.id)
        if not state['unlocked']:
            raise ValueError('Title is locked')
        def operation(db):
            db.execute('UPDATE career_profiles SET current_title=? WHERE id=?', (target.name, profile['id']))
        self.store.career_transaction(operation)
        return {'equipped': target.name}

    def badges(self, driver_id=None):
        """F006: [{id,name,icon,description,unlocked,earned_at,progress{current,target,fraction},evidence}]."""
        profile = self._profile(driver_id)
        return badges_mod.list_badges(self.store, profile['id'], self._level(profile)['current'], profile['comparable_laps'])

    def recent_gains(self, driver_id=None):
        return summary.recent_gains(self.store, self._profile(driver_id)['id'])

    def _next_unlock(self, titles, badges):
        candidates = [dict(kind='title', id=t['id'], name=t['name'], progress=t['progress']) for t in titles['titles'] if not t['unlocked']]
        candidates += [dict(kind='badge', id=b['id'], name=b['name'], progress=b['progress']) for b in badges if not b['unlocked']]
        return max(candidates, key=lambda c: c['progress']['fraction'], default=None)

    def overview(self, driver_id=None):
        """F007 card; fields without stored data are null/empty."""
        profile = self._profile(driver_id)
        titles, badges = self.titles(profile['id']), self.badges(profile['id'])
        return summary.overview(profile, self._level(profile), titles, badges, self.recent_gains(profile['id']), self._next_unlock(titles, badges))

    def timeline(self, driver_id=None, limit=50, cursor=None):
        return summary.timeline(self.store, self._profile(driver_id)['id'], limit, cursor)

    def stats(self, driver_id=None):
        profile = self._profile(driver_id)
        return summary.stats(self.store, profile['id'], profile, self._level(profile))

    def dashboard(self, driver_id=None):
        profile = self._profile(driver_id)
        archive = self.store.query('SELECT preview,provenance FROM career_import_archives WHERE driver_id=?', (profile['id'],))
        if archive:
            preview = json.loads(archive[0]['preview'])
            return dict(**preview, profile={**profile, 'provenance': 'imported_profile'}, level=self.curve.progress(profile['total_xp']),
                        next_action={'title': 'Imported career archive', 'reason': 'This is imported history, not current live evidence. Select or create a local driver to earn live progression.'},
                        settings=self.settings(), integrity={'algorithm_version': 1, 'reward_source': 'imported archive; live rewards disabled', 'unknown_metrics': 'unavailable', 'scope': 'imported_profile'})
        cards = [json.loads(r['payload']) for r in self.store.query('SELECT payload FROM career_scorecards WHERE driver_id=? ORDER BY created_at DESC LIMIT 20', (profile['id'],))]
        challenges = self.challenges(profile['id'])
        next_challenge = next((c for c in challenges if c['status'] == 'accepted'), None) or next((c for c in challenges if c['status'] == 'offered'), None)
        next_action = dict(title=next_challenge['title'], reason=next_challenge['why']) if next_challenge else dict(title='Complete two comparable live laps', reason='Use the same recognized layout and car; complete laps with uninterrupted telemetry to build consistency evidence.')
        return dict(profile=profile, level=self.curve.progress(profile['total_xp']), skills=self.skills(profile['id']),
                    titles=self.titles(profile['id']), badges=self.badges(profile['id']), recent_gains=self.recent_gains(profile['id']),
                    tracks=self.tracks(profile['id']), challenges=challenges, career=self.career(profile['id']),
                    engineer=self.engineer(profile['id']), streaks=self.streaks(profile['id']),
                    achievements=self.achievements(profile['id']), recent_events=self.history(profile['id'], 20), scorecards=cards,
                    next_action=next_action,
                    settings=self.settings(), integrity=dict(algorithm_version=ALGORITHM_VERSION, reward_source='finalized live sessions', unknown_metrics='unavailable', scope='foundation'))

    def diagnostics(self):
        return dict(algorithm_version=ALGORITHM_VERSION, pending_sessions=len(self.pending_sessions(200)),
                    max_laps=MAX_LAPS, source='existing recorder', supported_metrics=['consistency'],
                    unsupported=['full_track_mastery', 'advanced_curriculum', 'seasons', 'racecraft_progression'])

    def export(self, driver_id=None):
        driver_id = self._profile(driver_id)['id']
        archive = self.store.query('SELECT payload FROM career_import_archives WHERE driver_id=?', (driver_id,))
        return json.loads(archive[0]['payload']) if archive else export_career(self.store, driver_id)

    def import_bundle(self, bundle):
        return import_career(self.store, bundle)

    def reset(self, driver_id: str, confirmation: str):
        if confirmation != 'RESET CAREER': raise ValueError('Confirmation must be RESET CAREER')
        self._profile(driver_id)
        def operation(db):
            if db.execute('SELECT 1 FROM career_import_archives WHERE driver_id=?', (driver_id,)).fetchone():
                raise ValueError('Imported archives are read-only; select a local profile to reset progression')
            # Keep source/scorecard tombstones and bindings: old recorded sessions
            # must never become eligible for XP again after a reset.
            for table in ('career_xp_events', 'career_skills', 'career_achievements', 'career_events', 'career_notifications'):
                db.execute(f'DELETE FROM {table} WHERE driver_id=?', (driver_id,))
            for table in ('career_track_mastery', 'career_corner_mastery', 'career_mastery_history'):
                db.execute(f'DELETE FROM {table} WHERE driver_id=?', (driver_id,))
            for table in ('career_engineer', 'career_missions', 'career_streaks', 'career_journal'):
                db.execute(f'DELETE FROM {table} WHERE driver_id=?', (driver_id,))
            db.execute("UPDATE career_challenges SET status='abandoned' WHERE driver_id=? AND status IN ('offered','accepted')", (driver_id,))
            db.execute('UPDATE career_profiles SET total_xp=0,eligible_sessions=0,comparable_laps=0 WHERE id=?', (driver_id,))
            db.execute("UPDATE career_scorecards SET xp_awarded=0,status='excluded',payload=json_set(payload,'$.xp_awarded',0,'$.status','excluded','$.exclusions',json('[\"career_reset\"]')) WHERE driver_id=?", (driver_id,))
            db.execute("UPDATE career_bindings SET invalid_reason='career_reset' WHERE driver_id=? AND session_id NOT IN (SELECT session_id FROM career_sources)", (driver_id,))
            return dict(reset=True, driver_id=driver_id, preserved_session_guards=True)
        return self.store.career_transaction(operation)
