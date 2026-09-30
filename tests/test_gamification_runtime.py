"""F001/F002/F004/F008: recorder lifecycle -> persisted Career, with conservative provenance."""
import asyncio

import pytest

from backend.app.config import Config
from backend.app.runtime import Runtime
from backend.app.storage import Store
from backend.app.telemetry import demo_sample
from backend.app.telemetry.bus import TelemetryEvent


def make_runtime(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({'speech_enabled': False, 'hands_free': False})
    r = Runtime(cfg, Store(tmp_path / 'career.db'))
    # Deterministic authoritative identity fixture. Recognition itself has its own tests.
    r.track.locked = object()
    r.track.locked_layout_id = 'fixture-layout'
    return r


def drive(r, source='live', count=91, start=0):
    for i in range(start, start + count):
        sample = demo_sample(i / 10, i)
        sample.provenance = source
        sample.values.update(lap=i // 30 + 1, last_ms=3000, flags=1, car_id=42)
        r.sessions.consume(sample)


def test_live_recorder_events_award_once_and_reopen(tmp_path):
    async def scenario():
        r = make_runtime(tmp_path)
        await r.career.start()
        drive(r)
        sid = r.sessions.id
        r.sessions.end()
        await r.career.queue.join()
        dashboard = r.career_repository.dashboard()
        assert dashboard['profile']['total_xp'] > 0
        assert dashboard['scorecards'][0]['session_id'] == sid
        assert dashboard['scorecards'][0]['status'] == 'eligible'
        total = dashboard['profile']['total_xp']
        r.bus.emit(TelemetryEvent('session_ended', {'session_id': sid, 'status': 'completed'}))
        await r.career.queue.join()
        assert r.career_repository.dashboard()['profile']['total_xp'] == total
        assert r.store.query('SELECT COUNT(*) AS n FROM samples')[0]['n'] == 91
        await r.career.close()
        r.store.close()
        reopened = Store(tmp_path / 'career.db')
        try:
            from backend.app.gamification.repository import CareerRepository
            assert CareerRepository(reopened).dashboard()['profile']['total_xp'] == total
        finally:
            reopened.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('source', ['demo', 'replay', 'import', 'unknown'])
def test_non_live_runtime_never_earns_live_progression(tmp_path, source):
    async def scenario():
        r = make_runtime(tmp_path)
        await r.career.start()
        drive(r, source)
        r.sessions.end()
        await r.career.queue.join()
        assert r.career_repository.dashboard()['profile']['total_xp'] == 0
        assert r.career_repository.dashboard()['scorecards'][0]['status'] == 'excluded'
        await r.career.close()
        r.store.close()
    asyncio.run(scenario())


def test_identity_unlock_and_profile_switch_preserve_evidence(tmp_path):
    async def scenario():
        r = make_runtime(tmp_path)
        await r.career.start()
        original = r.career.active_driver_id
        drive(r, count=40)
        other = await asyncio.to_thread(r.career_repository.create_profile, 'Second driver')
        r.career.active_driver_id = other['id']
        r.bus.emit(TelemetryEvent('track_unlocked', {}))
        drive(r, start=40, count=51)
        sid = r.sessions.id
        r.sessions.end()
        await r.career.queue.join()
        card = r.career_repository.dashboard(original)['scorecards'][0]
        assert card['status'] == 'excluded'
        assert card['driver_id'] == original and card['session_id'] == sid
        assert r.career_repository.dashboard(other['id'])['profile']['total_xp'] == 0
        await r.career.close()
        r.store.close()
    asyncio.run(scenario())


def test_processor_failure_leaves_durable_retry_and_recording_intact(tmp_path, monkeypatch):
    async def scenario():
        r = make_runtime(tmp_path)
        await r.career.start()
        original = r.career_repository.process_session
        monkeypatch.setattr(r.career_repository, 'process_session', lambda *args: (_ for _ in ()).throw(RuntimeError('injected failure')))
        drive(r)
        r.sessions.end()
        await r.career.queue.join()
        assert r.career.health()['failed_events'] == 1
        assert len(r.career_repository.pending_sessions()) == 1
        assert r.store.query('SELECT COUNT(*) AS n FROM samples')[0]['n'] == 91
        monkeypatch.setattr(r.career_repository, 'process_session', original)
        await asyncio.to_thread(r.career._recover)
        assert r.career_repository.dashboard()['profile']['total_xp'] > 0
        assert r.career_repository.pending_sessions() == []
        await r.career.close()
        r.store.close()
    asyncio.run(scenario())


def test_disabled_feature_and_bounded_queue_do_not_block_recording(tmp_path):
    async def scenario():
        r = make_runtime(tmp_path)
        await r.career.start()
        r._flags['gamification'] = False
        drive(r)
        r.sessions.end()
        await r.career.queue.join()
        assert r.career_repository.dashboard()['profile']['total_xp'] == 0
        # Starve the consumer deliberately; event producer remains nonblocking.
        r.career.queue = asyncio.Queue(maxsize=2)
        for _ in range(r.career.queue.maxsize + 5):
            r.career.on_event(TelemetryEvent('session_ended', {'session_id': 'unknown'}))
        assert r.career.queue.qsize() == r.career.queue.maxsize
        assert r.career.dropped_events == 5
        assert r.store.query('SELECT COUNT(*) AS n FROM samples')[0]['n'] == 91
        await r.career.close()
        r.store.close()
    asyncio.run(scenario())


def test_lost_finalization_never_recovers_as_eligible(tmp_path):
    async def scenario():
        r = make_runtime(tmp_path)
        await r.career.start()
        drive(r)
        await r.career.queue.join()  # all eligible lap contexts have committed
        r.career.accepting = False  # simulate a lost end event / process crash
        r.sessions.end()
        await asyncio.to_thread(r.career._recover)
        dashboard = r.career_repository.dashboard()
        assert dashboard['profile']['total_xp'] == 0
        assert dashboard['scorecards'] == []
        assert r.career_repository.pending_sessions()[0]['invalid_reason'] == 'awaiting_finalization'
        await r.career.close()
        r.store.close()
    asyncio.run(scenario())


def test_each_session_gets_its_own_career_spatial_reference(tmp_path, monkeypatch):
    from backend.app.spatial_coaching import SpatialLap
    import backend.app.track_catalogue as catalogue
    r = make_runtime(tmp_path)
    monkeypatch.setattr(catalogue, 'bundled_document', lambda _: {'corners': [{'id': 'T1', 's_start': 200, 's_end': 500, 's_apex': 350}]})
    observed = []
    r.bus.subscribe_events('capture-test', lambda event: observed.append(event.data), kinds=['spatial_analysis_completed'])
    try:
        for sid, pace in [('first', .02), ('second', .03)]:
            r.sessions.id = sid
            for number in range(2):
                lap = SpatialLap(1000, 'fixture-layout', 42)
                for distance in range(0, 1000, 10):
                    lap.record(distance, distance*pace, 100, .2, .5)
                r.spatial_lap = lap
                r.sessions.laps = [{'id': f'{sid}:{number}', 'comparable': True, 'complete': True}]
                r.close_spatial_lap(number + 1)
        assert [o['spatial']['reference_lap_id'] for o in observed] == ['first:0', 'second:0']
    finally:
        r.store.close()
