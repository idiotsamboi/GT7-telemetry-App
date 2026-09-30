"""Phase 8 of the broadcast/spatial build (docs/AI_CONTEXT.md section 12):
clean-air pit advice from shared group traffic data.
"""
import pytest

from backend.app.clean_air import pit_advice

LENGTH = 4000.0


def traffic(entry_id, d, median_lap_s, in_pit=False, battle_state=None, number="9"):
    return {"entry_id": entry_id, "number": number, "name": "Car", "D": d, "median_lap_s": median_lap_s, "in_pit": in_pit, "battle_state": battle_state}


def test_unavailable_without_any_shared_traffic():
    result = pit_advice(my_d=0, my_lap_s=90, fuel_l=20, capacity_l=60, burn_l_per_lap=2, reserve_l=2, pit_loss_s=25, laps_left=10, length_m=LENGTH, traffic=[])
    assert result["available"] is False


def test_unavailable_without_known_pit_loss():
    result = pit_advice(my_d=0, my_lap_s=90, fuel_l=20, capacity_l=60, burn_l_per_lap=2, reserve_l=2, pit_loss_s=None, laps_left=10, length_m=LENGTH, traffic=[traffic("a", 0, 90)])
    assert result["available"] is False and "pit loss" in result["reason"].lower()


def test_no_fuel_margin_recommends_boxing_this_lap():
    # burn 5L/lap, only 6L fuel with a 2L reserve -> max_k = floor((6-2)/5)-1 = -1 <= 0
    result = pit_advice(my_d=0, my_lap_s=90, fuel_l=6, capacity_l=60, burn_l_per_lap=5, reserve_l=2, pit_loss_s=25, laps_left=10, length_m=LENGTH, traffic=[traffic("a", 0, 90)])
    assert result["available"] and result["max_k"] == 0 and result["recommended_k"] == 0
    assert "no fuel margin" in result["text"].lower()


def test_clear_air_when_nobody_rejoins_nearby():
    # Only other car is far behind, will never be within the 2s rejoin window.
    result = pit_advice(my_d=1000, my_lap_s=90, fuel_l=40, capacity_l=60, burn_l_per_lap=2, reserve_l=2, pit_loss_s=25, laps_left=10, length_m=LENGTH, traffic=[traffic("a", 0, 90)])
    assert result["available"] and result["recommended_k"] == 0
    assert "clear air" in result["text"].lower()


def test_recommends_staying_out_behind_slow_battling_traffic():
    # Two slower, battling cars land just ahead of my rejoin point at k=0 (a real
    # cost: I'd be stuck behind slower traffic); since they're slower than me,
    # each extra lap I stay out closes the gap until I'd rejoin ahead of them
    # instead, clearing the cost - so recommended_k should move off 0.
    my_lap_s = 90.0
    pit_loss = 25.0
    my_d = 0.0

    def d_for(median_lap_s, rejoin_gap_s_at_k0):
        v_j = LENGTH / median_lap_s
        return v_j * rejoin_gap_s_at_k0 - v_j * pit_loss  # so (D_j + v_j*pit_loss - my_d)/v_j == rejoin_gap_s_at_k0

    cars = [
        traffic("slow1", d_for(110.0, 0.5), 110.0, battle_state="hot", number="12"),
        traffic("slow2", d_for(108.0, 0.3), 108.0, battle_state="hot", number="7"),
    ]
    result = pit_advice(my_d=my_d, my_lap_s=my_lap_s, fuel_l=40, capacity_l=60, burn_l_per_lap=2, reserve_l=2, pit_loss_s=pit_loss, laps_left=10, length_m=LENGTH, traffic=cars)
    assert result["available"]
    assert result["options"][0]["ahead"]  # at k=0, both slow cars are in the way
    assert result["recommended_k"] >= 1
    assert "battling" in result["text"].lower()
    assert "#12" in result["text"] or "#7" in result["text"]


def test_options_never_extend_past_laps_actually_left_in_the_race():
    # Regression: `stuck_laps = min(MAX_STUCK_LAPS, laps_left - k)` was never
    # floored at 0, so once a candidate k exceeded laps_left the "stuck behind
    # traffic" cost went NEGATIVE (increasingly so for larger k), making the
    # recommender pick the largest available k - e.g. "stay out 5 laps" with
    # only 2 laps left in the race. Fixed by capping the k range itself at
    # laps_left (when known) as well as clamping the per-option multiplier.
    my_lap_s = 90.0
    pit_loss = 25.0

    def d_for(median_lap_s, rejoin_gap_s_at_k0):
        v_j = LENGTH / median_lap_s
        return v_j * rejoin_gap_s_at_k0 - v_j * pit_loss

    slow_car = traffic("slow", d_for(130.0, 0.5), 130.0, battle_state="hot", number="5")
    result = pit_advice(my_d=0.0, my_lap_s=my_lap_s, fuel_l=40, capacity_l=60, burn_l_per_lap=2, reserve_l=2, pit_loss_s=pit_loss, laps_left=2, length_m=LENGTH, traffic=[slow_car])
    assert result["available"]
    assert all(o["k"] <= 2 for o in result["options"])
    assert all(o["cost_s"] >= 0 for o in result["options"])
    assert result["recommended_k"] <= 2


def test_unknown_laps_left_does_not_zero_the_stuck_traffic_penalty():
    # laps_left=None (e.g. a timed/unknown-length race) used to make
    # (laps_left or 0) - k == -k for every k>=1, again a negative multiplier -
    # it should instead fall back to a real assumed stuck-lap count.
    my_lap_s = 90.0
    pit_loss = 25.0

    def d_for(median_lap_s, rejoin_gap_s_at_k0):
        v_j = LENGTH / median_lap_s
        return v_j * rejoin_gap_s_at_k0 - v_j * pit_loss

    slow_car = traffic("slow", d_for(130.0, 0.5), 130.0, battle_state="hot", number="5")
    result = pit_advice(my_d=0.0, my_lap_s=my_lap_s, fuel_l=40, capacity_l=60, burn_l_per_lap=2, reserve_l=2, pit_loss_s=pit_loss, laps_left=None, length_m=LENGTH, traffic=[slow_car])
    assert result["available"]
    assert all(o["cost_s"] >= 0 for o in result["options"])
    assert result["options"][0]["cost_s"] > 0


def test_small_improvement_does_not_override_staying_at_k_zero():
    # A marginal cost difference between k=0 and a later k shouldn't trigger the
    # recommendation to change - only a >=1.0s real improvement does.
    result = pit_advice(my_d=1000, my_lap_s=90, fuel_l=40, capacity_l=60, burn_l_per_lap=2, reserve_l=2, pit_loss_s=25, laps_left=10, length_m=LENGTH, traffic=[traffic("a", 0, 90)])
    # (already clear air at k=0 in this setup, so recommended_k stays 0 - this
    # also exercises that a tie/no-improvement case doesn't wander to a later k)
    assert result["recommended_k"] == 0
