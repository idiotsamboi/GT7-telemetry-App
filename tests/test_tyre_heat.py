"""Phase 6 of the broadcast/spatial build (docs/AI_CONTEXT.md section 7):
tyre heating-rate signal processing. Surface temperature only - never wear or
grip - so these tests also guard the module's own docstrings/language.
"""
from backend.app.tyre_heat import ANOMALY_MIN_POINTS, TyreHeatMonitor


def drive(monitor, temps_fn, *, n=200, dt=0.2, speed=150.0, locked=False, s_fn=None, layout_id="10", start_t=0.0):
    result = None
    t = start_t
    for i in range(n):
        temps = temps_fn(i)
        s = s_fn(i) if s_fn else None
        result = monitor.observe(t, temps, speed, active=True, locked=locked, s=s, layout_id=layout_id)
        t += dt
    return result


def test_no_signal_below_the_driving_speed_threshold():
    monitor = TyreHeatMonitor()
    result = drive(monitor, lambda i: [80.0] * 4, speed=30.0, n=100)
    assert result["rates"] == [None] * 4 and result["anomalies"] == [None] * 4


def test_positive_case_a_sustained_ramp_produces_a_rising_rate_and_anomaly():
    monitor = TyreHeatMonitor()
    # FL ramps steadily from 80 to 120 degrees over the run; others stay flat.
    result = drive(monitor, lambda i: [80.0 + i * 0.3, 80.0, 80.0, 80.0], n=250)
    assert result["rates"][0] is not None and result["rates"][0] > 0
    assert result["anomalies"][0] is not None and result["anomalies"][0] > 4.0
    assert result["rates"][1] is None or abs(result["rates"][1]) < 0.01


def test_negative_case_normal_cyclical_corner_heating_cancels_with_a_track_position_baseline():
    monitor = TyreHeatMonitor()
    import math

    def temps(i):
        # Every lap follows the identical temperature-vs-position curve (a normal,
        # repeatable corner-heating cycle) - a track-position baseline should see
        # no anomaly once it has learned that pattern, even though temperature
        # itself swings a lot within each lap.
        phase = (i % 50) / 50 * math.tau
        return [90.0 + 10 * math.sin(phase)] * 4

    def s_of(i):
        return (i % 50) / 50 * 5000  # a 5000m lap, position wraps every 50 samples

    # Drive enough identical laps for every bin's baseline to actually converge
    # (each visit only nudges it 30% of the way there), not just clear the
    # >=2-visit minimum to start reporting at all.
    result = drive(monitor, temps, n=50 * 20, locked=True, s_fn=s_of)
    assert result["method"] == "track-position baseline"
    assert all(a is None or abs(a) < 2.0 for a in result["anomalies"])
    assert all(r is None or abs(r) < 0.05 for r in result["rates"])


def test_noisy_case_random_jitter_does_not_produce_a_false_rate():
    monitor = TyreHeatMonitor()
    import random

    rng = random.Random(1)
    result = drive(monitor, lambda i: [90.0 + rng.uniform(-3, 3) for _ in range(4)], n=300)
    for r in result["rates"]:
        # The real question: does noise alone cross the alert rule's own entry
        # threshold (0.15 degC/s)? A tighter bound here would just be testing
        # this specific random seed's incidental autocorrelation, not the signal.
        assert r is None or abs(r) < 0.15


def test_stale_or_paused_samples_produce_no_signal():
    monitor = TyreHeatMonitor()
    result = monitor.observe(0.0, [120.0, 120.0, 120.0, 120.0], 150.0, active=False, locked=False, s=None, layout_id="10")
    assert result["rates"] == [None] * 4


# --- Wired into engineer.Rules -------------------------------------------------

def hot_result(indices=(0,)):
    rates = [0.0] * 4  # all four tyres report a reading; only `indices` are hot
    anomalies = [0.0] * 4
    for i in indices:
        rates[i] = 0.3
        anomalies[i] = 6.0
    return {"rates": rates, "anomalies": anomalies, "method": "track-position baseline"}


def cool_result():
    return {"rates": [0.0] * 4, "anomalies": [0.0] * 4, "method": "track-position baseline"}


def warmed_up_rules():
    from backend.app.config import Settings
    from backend.app.engineer import Rules
    r = Rules(Settings())
    r.laps_since_start = 5
    return r


def test_tyre_heat_fires_after_sustained_entry_and_respects_persist():
    from backend.app.telemetry import demo_sample
    r = warmed_up_rules()
    s = demo_sample(0, 1)
    s.mono = 0.0
    assert not any(e.category == "tyre_heat_rate" for e in r.evaluate(s, "s", tyre_heat=hot_result((0,))))
    s.mono = 5.0  # under the 8s persist requirement
    assert not any(e.category == "tyre_heat_rate" for e in r.evaluate(s, "s", tyre_heat=hot_result((0,))))
    s.mono = 9.0  # past persist
    events = r.evaluate(s, "s", tyre_heat=hot_result((0,)))
    assert any(e.category == "tyre_heat_rate" for e in events)


def test_tyre_heat_per_tyre_and_global_cooldowns():
    from backend.app.telemetry import demo_sample
    r = warmed_up_rules()
    s = demo_sample(0, 1)
    s.mono = 0.0
    r.evaluate(s, "s", tyre_heat=hot_result((0,)))
    s.mono = 9.0
    first = r.evaluate(s, "s", tyre_heat=hot_result((0,)))
    assert any(e.category == "tyre_heat_rate" for e in first)
    s.mono = 30.0  # well within both the 120s per-tyre and 60s global cooldown
    r.tyre_active[0] = 9.0  # simulate the entry condition having stayed true throughout
    again = r.evaluate(s, "s", tyre_heat=hot_result((0,)))
    assert not any(e.category == "tyre_heat_rate" for e in again)


def test_tyre_heat_suppressed_during_warmup_laps():
    from backend.app.config import Settings
    from backend.app.engineer import Rules
    from backend.app.telemetry import demo_sample
    r = Rules(Settings())  # laps_since_start starts at 0
    s = demo_sample(0, 1)
    s.mono = 20.0
    events = r.evaluate(s, "s", tyre_heat=hot_result((0,)))
    assert not any(e.category == "tyre_heat_rate" for e in events)


def test_tyre_heat_suppressed_for_one_lap_after_a_detected_pit_exit():
    r = warmed_up_rules()
    r.settings.pit_region = [-10, -10, 10, 10]
    from backend.app.telemetry import demo_sample
    s = demo_sample(0, 1)
    s.mono = 0.0
    s.values["position"] = [0, 0, 0]  # inside the pit region
    r.evaluate(s, "s", tyre_heat=cool_result())
    s.mono = 1.0
    s.values["position"] = [500, 0, 500]  # exits the pit region on lap 1
    s.values["lap"] = 1
    r.evaluate(s, "s", tyre_heat=cool_result())
    assert r.pit_exit_lap == 1
    s.mono = 10.0
    s.values["lap"] = 2  # the lap right after the exit: still within the "1 lap after" window
    events = r.evaluate(s, "s", tyre_heat=hot_result((0,)))
    assert not any(e.category == "tyre_heat_rate" for e in events)
    s.mono = 20.0
    s.values["lap"] = 3  # one full lap after that: suppression lifts
    events = r.evaluate(s, "s", tyre_heat=hot_result((0,)))
    assert any(e.category == "tyre_heat_rate" for e in events)


def test_tyre_heat_suppressed_with_fewer_than_four_finite_tyres():
    r = warmed_up_rules()
    result = hot_result((0,))
    result["anomalies"][3] = None  # only 3 of 4 tyres have a reading
    from backend.app.telemetry import demo_sample
    s = demo_sample(0, 1)
    s.mono = 9.0
    events = r.evaluate(s, "s", tyre_heat=result)
    assert not any(e.category == "tyre_heat_rate" for e in events)


def test_tyre_heat_groups_both_fronts_into_one_message():
    from backend.app.telemetry import demo_sample
    r = warmed_up_rules()
    s = demo_sample(0, 1)
    s.mono = 0.0
    r.evaluate(s, "s", tyre_heat=hot_result((0, 1)))
    s.mono = 9.0
    events = [e for e in r.evaluate(s, "s", tyre_heat=hot_result((0, 1))) if e.category == "tyre_heat_rate"]
    assert len(events) == 1
    assert "front" in events[0].message.lower()
    assert "wear" not in events[0].message.lower() and "grip" not in events[0].message.lower()


def test_fewer_than_four_finite_tyres_is_handled_without_crashing():
    monitor = TyreHeatMonitor()
    result = drive(monitor, lambda i: [80.0 + i * 0.3, None, 80.0, 80.0], n=250)
    assert result["rates"][1] is None and result["anomalies"][1] is None


def test_requires_the_anomaly_minimum_point_count_before_reporting_a_rate():
    monitor = TyreHeatMonitor()
    result = drive(monitor, lambda i: [80.0 + i * 0.3] * 4, n=ANOMALY_MIN_POINTS - 5, dt=1 / 5)
    assert result["rates"][0] is None  # anomaly history hasn't reached the minimum point count yet
