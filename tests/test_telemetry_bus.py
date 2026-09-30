import logging

import pytest

from backend.app.telemetry import TelemetryBus, TelemetryEvent, TelemetryFrame, demo_sample
from backend.app.telemetry import bus as busmod


def frame_at(mono, index=0):
    return TelemetryFrame.from_sample(demo_sample(mono, index))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_every_mode_and_order_and_critical_first():
    bus, calls = TelemetryBus(), []
    bus.subscribe('normal1', lambda f: calls.append('n1'), mode='every')
    bus.subscribe('normal2', lambda f: calls.append('n2'), mode='every')
    bus.subscribe('crit', lambda f: calls.append('c'), mode='every', critical=True)
    bus.subscribe('crit2', lambda f: calls.append('c2'), mode='every', critical=True)
    bus.publish(frame_at(0.0))
    assert calls == ['c', 'c2', 'n1', 'n2']            # critical first, otherwise subscription order


def test_rate_mode_decimates_by_frame_time():
    bus, got = TelemetryBus(), []
    bus.subscribe('ui', lambda f: got.append(f.meta.mono), mode='rate', hz=10)
    for i in range(121):                                  # 2 s at 60 Hz
        bus.publish(frame_at(i / 60, i))
    assert got[0] == 0.0                                  # first frame always passes
    assert 19 <= len(got) <= 21
    assert all(b - a >= 0.1 - 1e-9 for a, b in zip(got, got[1:]))


def test_rate_mode_restarts_when_clock_goes_backwards():
    bus, got = TelemetryBus(), []
    bus.subscribe('ui', lambda f: got.append(f.meta.mono), mode='rate', hz=1)
    bus.publish(frame_at(100.0))
    bus.publish(frame_at(100.2))
    bus.publish(frame_at(5.0))                            # new session with a smaller mono
    assert got == [100.0, 5.0]


def test_latest_mode_slot_and_freshness():
    bus = TelemetryBus()
    calls = []
    sub = bus.subscribe('push', lambda f: calls.append(f), mode='latest')
    assert sub.latest() is None and not sub.fresh
    bus.publish(frame_at(1.0, 1))
    bus.publish(frame_at(2.0, 2))
    assert sub.fresh
    assert sub.latest().meta.packet_id == 2               # only the newest survives
    assert not sub.fresh
    assert sub.latest(only_fresh=True) is None            # nothing new since the last read
    assert sub.latest().meta.packet_id == 2               # the slot still holds it
    bus.publish(frame_at(3.0, 3))
    assert sub.latest(only_fresh=True).meta.packet_id == 3
    assert calls == []                                    # latest mode never calls the handler


def test_subscription_validation_and_cancel():
    bus, calls = TelemetryBus(), []
    with pytest.raises(ValueError):
        bus.subscribe('bad', lambda f: None, mode='sometimes')
    with pytest.raises(ValueError):
        bus.subscribe('bad', lambda f: None, mode='rate')
    with pytest.raises(ValueError):
        bus.subscribe('bad', None, mode='every')
    sub = bus.subscribe('a', lambda f: calls.append(1))
    with pytest.raises(ValueError):
        bus.subscribe('a', lambda f: None)                # duplicate name
    bus.publish(frame_at(0.0))
    sub.cancel()
    sub.cancel()                                          # idempotent
    bus.publish(frame_at(0.1))
    assert calls == [1] and 'a' not in bus.metrics
    bus.subscribe('a', lambda f: None)                    # name reusable after cancel


def test_handler_exception_never_breaks_others():
    bus, seen = TelemetryBus(), []

    def broken(frame):
        raise RuntimeError('boom')

    bus.subscribe('broken', broken, critical=True)
    bus.subscribe('ok', lambda f: seen.append(f.meta.mono))
    for i in range(5):
        bus.publish(frame_at(i))
    assert seen == [0, 1, 2, 3, 4]
    m = bus.metrics['broken']
    assert m.calls == 5 and m.errors == 5 and m.last_error == 'RuntimeError: boom'
    assert bus.metrics['ok'].errors == 0


def test_error_logging_rate_limited(caplog):
    clock = Clock()
    bus = TelemetryBus(clock=clock)
    bus.subscribe('broken', lambda f: 1 / 0)
    with caplog.at_level(logging.WARNING, logger='telemetry'):
        for _ in range(100):
            bus.publish(frame_at(0.0))
        assert len([r for r in caplog.records if r.name == 'telemetry']) == 1
        clock.now += 59
        bus.publish(frame_at(0.0))
        assert len(caplog.records) == 1
        clock.now += 2                                     # 61 s after the first log
        bus.publish(frame_at(0.0))
        assert len(caplog.records) == 2
        assert '100 similar errors suppressed' in caplog.records[1].getMessage()
    assert bus.metrics['broken'].errors == 102


def test_errors_logged_per_subscriber(caplog):
    bus = TelemetryBus(clock=Clock())
    bus.subscribe('a', lambda f: 1 / 0)
    bus.subscribe('b', lambda f: 1 / 0)
    with caplog.at_level(logging.WARNING, logger='telemetry'):
        bus.publish(frame_at(0.0))
        bus.publish(frame_at(0.1))
    assert len(caplog.records) == 2                         # one per subscriber name


def test_events_delivery_filter_and_isolation():
    bus, got = TelemetryBus(), []
    bus.subscribe_events('all', lambda e: got.append(('all', e.kind)))
    bus.subscribe_events('laps', lambda e: got.append(('laps', e.kind)), kinds=[busmod.LAP_COMPLETED])
    bus.subscribe_events('broken', lambda e: 1 / 0, critical=True)
    bus.emit(TelemetryEvent(busmod.LAP_COMPLETED, {'lap': 2}, 1.0))
    bus.emit(TelemetryEvent(busmod.PIT_DETECTED, {}, 2.0))
    assert got == [('all', 'lap_completed'), ('laps', 'lap_completed'), ('all', 'pit_detected')]
    assert bus.metrics['event:broken'].errors == 2
    assert bus.events_emitted == 2


def test_event_kind_constants():
    assert set(busmod.EVENT_KINDS) == {'lap_completed', 'session_started', 'session_ended', 'source_changed',
                                       'connection_changed', 'track_locked', 'track_unlocked', 'pit_detected'}


def test_metrics_and_timing_sampling():
    bus = TelemetryBus()
    bus.subscribe('fast', lambda f: None)
    for i in range(160):
        bus.publish(frame_at(i))
    m = bus.metrics['fast']
    assert m.calls == 160
    assert len(m.durations) == 160 // busmod.TIMING_SAMPLE_EVERY      # timed one in N
    assert m.durations.maxlen == 256
    snapshot = bus.metrics_snapshot()
    import json
    json.dumps(snapshot)
    row = snapshot['subscribers']['fast']
    assert row['calls'] == 160 and row['errors'] == 0 and row['p95_ms'] is not None
    assert snapshot['frames_published'] == 160


def test_duration_window_is_bounded():
    bus = TelemetryBus()
    bus.subscribe('x', lambda f: None)
    f = frame_at(0)
    for _ in range(busmod.TIMING_SAMPLE_EVERY * 400):
        bus.publish(f)
    assert len(bus.metrics['x'].durations) == 256


def test_subscribing_during_publish_is_safe():
    bus, calls = TelemetryBus(), []

    def first(frame):
        calls.append('first')
        bus.subscribe('late', lambda f: calls.append('late'))

    bus.subscribe('first', first)
    bus.publish(frame_at(0))
    assert calls == ['first']                                # the new subscriber only sees later frames
    assert 'late' in bus.metrics
