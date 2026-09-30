"""Phase 8 of the broadcast/spatial build (docs/AI_CONTEXT.md section 12):
Runtime.clean_air_advice() wires clean_air.pit_advice() into the driver's own
runtime from its group connection's last-published state, and Runtime.command()
appends its text to the 'pit' voice answer. Never fabricates a result when a
prerequisite (group connection, sharing opt-in, track length, fuel data,
lap pace) is missing.
"""
from types import SimpleNamespace

import pytest

from backend.app.config import Config
from backend.app.storage import Store
from backend.app.runtime import Runtime
from backend.app.tracks import LAYOUTS


@pytest.fixture
def runtime(tmp_path):
    config = Config(tmp_path); config.save({"speech_enabled": False})
    store = Store(tmp_path / "test.db"); runtime = Runtime(config, store)
    yield runtime
    store.close()


def connect_group(runtime, *, traffic, pit_loss_s, own_d=0.0):
    state = {
        "entries": [{"entry_id": "me", "D": own_d}, {"entry_id": "other", "D": 500.0}],
        "traffic": traffic,
        "projection": {"pit_loss_s": pit_loss_s},
    }
    client = SimpleNamespace(state=state, joined={"participant": {"entry_id": "me"}})
    runtime.group = SimpleNamespace(client=client)


def prime_fuel_and_pace(runtime, monkeypatch, *, fuel=40.0, capacity=60.0, litres_per_lap=2.0, laps_remaining=10.0):
    runtime.sample = SimpleNamespace(values={"fuel": fuel, "fuel_capacity": capacity})
    monkeypatch.setattr(runtime.sessions, "fuel", lambda: {"available": True, "litres_per_lap": litres_per_lap, "laps_remaining": laps_remaining})
    runtime.sessions.laps = [{"duration_ms": 90000, "comparable": True} for _ in range(3)]


def test_none_without_a_group_connection(runtime):
    assert runtime.clean_air_advice() is None


def test_none_when_connected_but_not_sharing_traffic(runtime, monkeypatch):
    connect_group(runtime, traffic=None, pit_loss_s=25.0)
    prime_fuel_and_pace(runtime, monkeypatch)
    runtime.track_map.select("10", manual=True)
    assert runtime.clean_air_advice() is None


def test_none_without_a_bound_track_length(runtime, monkeypatch):
    connect_group(runtime, traffic=[{"entry_id": "other", "number": "9", "name": "Car", "D": 500.0, "median_lap_s": 110.0, "in_pit": False, "battle_state": None}], pit_loss_s=25.0)
    prime_fuel_and_pace(runtime, monkeypatch)
    assert not runtime.track_map.bound
    assert runtime.clean_air_advice() is None


def test_computes_advice_when_everything_is_available(runtime, monkeypatch):
    connect_group(runtime, traffic=[{"entry_id": "other", "number": "9", "name": "Car", "D": 500.0, "median_lap_s": 110.0, "in_pit": False, "battle_state": None}], pit_loss_s=25.0)
    prime_fuel_and_pace(runtime, monkeypatch)
    runtime.track_map.select("10", manual=True)
    result = runtime.clean_air_advice()
    assert result is not None and result["available"]
    assert isinstance(result["text"], str) and result["text"]


def test_pit_command_appends_clean_air_text(runtime, monkeypatch):
    connect_group(runtime, traffic=[{"entry_id": "other", "number": "9", "name": "Car", "D": 500.0, "median_lap_s": 110.0, "in_pit": False, "battle_state": None}], pit_loss_s=25.0)
    prime_fuel_and_pace(runtime, monkeypatch)
    runtime.track_map.select("10", manual=True)
    monkeypatch.setattr(runtime, "received_at", __import__("time").monotonic())
    response = runtime.command("when should i pit")
    assert response["intent"] == "pit"
    advice = runtime.clean_air_advice()
    assert advice["text"] in response["answer"]
