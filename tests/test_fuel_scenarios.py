"""Phase 8 of the broadcast/spatial build (docs/AI_CONTEXT.md section 9.1):
multi-branch fuel strategy scenarios (Save / Splash / Gap check).
"""
import pytest

from backend.app.analytics import fuel_scenarios


def prediction(margin_l, litres_per_lap=2.0, laps_remaining=10):
    return {"available": True, "margin_l": margin_l, "litres_per_lap": litres_per_lap, "laps_remaining": laps_remaining}


def lap(number, duration_ms, fuel_used_l, comparable=True):
    return {"number": number, "duration_ms": duration_ms, "fuel_used_l": fuel_used_l, "comparable": comparable}


def test_sufficient_fuel_reports_no_branches():
    result = fuel_scenarios(prediction(margin_l=2.0), [])
    assert result["short"] is False and result["branches"] == []
    assert "sufficient" in result["summary"].lower()


def test_unavailable_prediction_reports_unavailable():
    result = fuel_scenarios({"available": False}, [])
    assert result["short"] is False and "unavailable" in result["summary"].lower()


def test_save_branch_feasible_within_max_percent():
    # deficit 1L over 10 laps * 2L/lap = 20L needed -> save_percent = 100*1/20 = 5%
    result = fuel_scenarios(prediction(margin_l=-1.0), [], max_save_percent=8.0)
    save = next(b for b in result["branches"] if b["id"] == "save")
    assert save["feasible"] and save["save_percent"] == pytest.approx(5.0, abs=0.1)
    assert result["recommendation"] == "save"


def test_save_branch_infeasible_beyond_max_percent():
    # deficit 5L over 10 laps * 2L/lap = 20L needed -> 25%, over an 8% cap
    result = fuel_scenarios(prediction(margin_l=-5.0), [], max_save_percent=8.0, pit_loss_s=25.0)
    save = next(b for b in result["branches"] if b["id"] == "save")
    assert not save["feasible"]
    assert result["recommendation"] == "splash"  # save infeasible, splash is the only option


def test_splash_branch_requires_pit_loss_known():
    result = fuel_scenarios(prediction(margin_l=-1.0), [], pit_loss_s=None)
    splash = next(b for b in result["branches"] if b["id"] == "splash")
    assert not splash["feasible"] and splash["cost_s"] is None


def test_splash_omits_refuel_time_when_rate_unknown():
    result = fuel_scenarios(prediction(margin_l=-1.0), [], pit_loss_s=25.0, refuel_rate_lps=None)
    splash = next(b for b in result["branches"] if b["id"] == "splash")
    assert splash["cost_s"] == pytest.approx(25.0)
    assert "refuel time" in splash["text"]


def test_splash_includes_refuel_time_when_rate_known():
    result = fuel_scenarios(prediction(margin_l=-1.0), [], pit_loss_s=25.0, refuel_rate_lps=2.0)
    splash = next(b for b in result["branches"] if b["id"] == "splash")
    # add_l = deficit(1.0) + 0.5 reserve margin = 1.5L; refuel_s = 1.5/2.0 = 0.75
    assert splash["cost_s"] == pytest.approx(25.75, abs=0.06)  # rounded to 1 decimal place


def test_gap_check_prefers_save_when_splash_would_lose_a_position():
    result = fuel_scenarios(prediction(margin_l=-1.0), [], max_save_percent=8.0, pit_loss_s=25.0, refuel_rate_lps=2.0, gap_to_car_behind_s=10.0)
    splash = next(b for b in result["branches"] if b["id"] == "splash")
    assert splash["loses_position"] is True  # 10s gap - ~25.75s cost = negative
    assert result["recommendation"] == "save"  # even though splash alone would be "cheaper" in isolation


def test_gap_check_keeps_splash_when_it_holds_the_position():
    # max_save_percent=0 makes Save infeasible regardless of cost, so Splash is
    # the only feasible branch - recommended as long as it doesn't cost a position.
    result = fuel_scenarios(prediction(margin_l=-1.0), [], max_save_percent=0.0, pit_loss_s=5.0, refuel_rate_lps=10.0, gap_to_car_behind_s=30.0)
    splash = next(b for b in result["branches"] if b["id"] == "splash")
    assert splash["loses_position"] is False
    assert result["recommendation"] == "splash"


def test_cost_per_litre_uses_measured_slope_from_six_clean_laps_with_enough_spread():
    # fuel_used_l varies from 8 to 11 (>=3% spread); duration increases as fuel used decreases
    # (heavier fuel saving costs more time) - a real, learnable relationship.
    laps = [lap(i, 90_000 + (11 - fuel) * 1000, fuel) for i, fuel in enumerate([11, 10, 9, 8, 10, 9])]
    result = fuel_scenarios(prediction(margin_l=-1.0), laps)
    assert result["cost_per_l_source"] == "measured"


def test_cost_per_litre_falls_back_to_assumed_default_without_enough_laps():
    result = fuel_scenarios(prediction(margin_l=-1.0), [])
    assert result["cost_per_l_source"] == "assumed" and result["cost_per_l"] == pytest.approx(4.0)


def test_cost_per_litre_uses_configured_assumption_when_provided():
    result = fuel_scenarios(prediction(margin_l=-1.0), [], fuel_time_slope_s_per_l=6.0)
    assert result["cost_per_l_source"] == "assumed" and result["cost_per_l"] == pytest.approx(6.0)


def test_cost_per_litre_ignores_laps_with_too_little_fuel_spread():
    # All laps burn almost exactly the same fuel - no learnable relationship.
    laps = [lap(i, 90_000, 10.0 + i * 0.001) for i in range(6)]
    result = fuel_scenarios(prediction(margin_l=-1.0), laps)
    assert result["cost_per_l_source"] == "assumed"
