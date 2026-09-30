"""Phase 3 of the broadcast/spatial build (docs/AI_CONTEXT.md section 4):
focusing a live battle into a workspace's draft (and optionally taking it).
"""
import asyncio
import math
import time
from types import SimpleNamespace

import pytest
from backend.app.core.errors import AppError

from backend.app.group.battles import BattleEngine, PairState
from backend.app.group.service import GroupService


def route():
    return [[100 * math.cos(i * math.tau / 100), 100 * math.sin(i * math.tau / 100)] for i in range(101)]


def build(tmp_path):
    return GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / "db.sqlite"), config=SimpleNamespace(root=tmp_path)))


async def make_group_with_battle(s):
    """Create a group with two admitted entries and a synthetic active battle,
    without needing the real 2Hz worker or live telemetry to produce one."""
    league = await s.league_save({"name": "Test league"})
    await s.create_group({"name": "Test", "event_name": "Test event", "league_id": league["id"], "layout_id": "10"})
    await s.set_map(route(), [])
    entries = []
    for n in range(2):
        invite = await s.invite("driver")
        j = await s.join({"credential": invite["credential"], "identity": {"display_name": f"Driver {n}", "number": str(n)}})
        await s.admit(j["participant"]["id"], "admitted")
        entries.append(j["participant"]["entry_id"])
    g = s.active()
    engine = BattleEngine()
    s.battle_engines[g["id"]] = engine
    battle = {
        "id": f"{entries[0]}:{entries[1]}:0", "epoch": 0, "state": "hot", "ahead": entries[0], "behind": entries[1],
        "position": 2, "gap_s": 0.6, "gap_uncertainty_s": 0.05, "closing_rate_s_per_s": -0.03, "closing_per_lap_s": -2.5,
        "heat": 75.0, "confidence": "ok", "same_class": True, "lapping": False, "time_within_1s": 10.0, "last_event": None,
    }
    engine.pairs[frozenset(entries)] = PairState(battle_id=battle["id"], state="hot", last_ahead=entries[0], last_behind=entries[1], last_seen=time.time())
    s.battles[g["id"]] = [battle]
    return g, entries, battle


def test_focus_sets_slots_and_adds_missing_graphics(tmp_path):
    s = build(tmp_path)

    async def check():
        g, entries, battle = await make_group_with_battle(s)
        w = await s.save_workspace({"name": "Main"})
        result = await s.focus_battle(battle["id"], w["id"], take=False, ensure_graphics=True)
        return result, entries

    result, entries = asyncio.run(check())
    draft = result["workspace"]["draft"]
    assert draft["slots"]["a"] == entries[0] and draft["slots"]["b"] == entries[1] and draft["slots"]["primary"] == entries[1]
    assert draft["selection_mode"] == "manual"
    templates = {g["template"] for g in draft["graphics"]}
    assert {"comparison", "telemetry"} <= templates
    comparison = next(x for x in draft["graphics"] if x["template"] == "comparison")
    telemetry = next(x for x in draft["graphics"] if x["template"] == "telemetry")
    assert comparison["slot"] == "a" and telemetry["slot"] == "primary" and comparison["visible"] and telemetry["visible"]
    assert result["warnings"] == []


def test_focus_does_not_take_unless_requested(tmp_path):
    s = build(tmp_path)

    async def check():
        g, entries, battle = await make_group_with_battle(s)
        w = await s.save_workspace({"name": "Main"})
        result = await s.focus_battle(battle["id"], w["id"], take=False)
        return result["workspace"], w["id"]

    workspace, wid = asyncio.run(check())
    assert workspace["program_revision"] == 0  # draft changed, program (live) untouched
    assert workspace["draft_revision"] == 2  # one bump from save_workspace's initial create + one from focus


def test_focus_with_take_publishes_the_program(tmp_path):
    s = build(tmp_path)

    async def check():
        g, entries, battle = await make_group_with_battle(s)
        w = await s.save_workspace({"name": "Main"})
        result = await s.focus_battle(battle["id"], w["id"], take=True)
        return result["workspace"]

    workspace = asyncio.run(check())
    assert workspace["program_revision"] == 1
    assert workspace["program"]["slots"]["a"]


def test_focus_warns_when_a_graphic_slot_is_locked_to_an_entry(tmp_path):
    s = build(tmp_path)

    async def check():
        g, entries, battle = await make_group_with_battle(s)
        w = await s.save_workspace({"name": "Main", "graphics": [{"id": "x1", "template": "comparison", "entry_id": entries[0], "x": 0, "y": 0, "width": 1000, "height": 300}]})
        result = await s.focus_battle(battle["id"], w["id"], take=False)
        return result, entries

    result, entries = asyncio.run(check())
    assert any("comparison" in warning for warning in result["warnings"])
    comparison = next(g for g in result["workspace"]["draft"]["graphics"] if g["template"] == "comparison")
    assert comparison["entry_id"] == entries[0]  # left unchanged, still locked to its own entry


def test_focus_rejects_a_battle_that_does_not_exist(tmp_path):
    s = build(tmp_path)

    async def check():
        await make_group_with_battle(s)
        w = await s.save_workspace({"name": "Main"})
        with pytest.raises(AppError) as info:
            await s.focus_battle("nonexistent:battle:0", w["id"], take=False)
        return info.value.status_code

    assert asyncio.run(check()) == 404


def test_focus_within_grace_period_of_a_just_ended_battle_still_works(tmp_path):
    s = build(tmp_path)

    async def check():
        g, entries, battle = await make_group_with_battle(s)
        engine = s.battle_engines[g["id"]]
        st = engine.find(battle["id"])
        st.state = "ended"
        st.last_seen = time.time() - 10  # ended 10s ago, within the 30s grace window
        s.battles[g["id"]] = []  # no longer actively reported
        w = await s.save_workspace({"name": "Main"})
        result = await s.focus_battle(battle["id"], w["id"], take=False)
        return result, entries

    result, entries = asyncio.run(check())
    assert result["workspace"]["draft"]["slots"]["a"] == entries[0]


def test_focus_refuses_a_battle_ended_too_long_ago(tmp_path):
    s = build(tmp_path)

    async def check():
        g, entries, battle = await make_group_with_battle(s)
        engine = s.battle_engines[g["id"]]
        st = engine.find(battle["id"])
        st.state = "ended"
        st.last_seen = time.time() - 45  # beyond the 30s grace window
        s.battles[g["id"]] = []
        w = await s.save_workspace({"name": "Main"})
        with pytest.raises(AppError) as info:
            await s.focus_battle(battle["id"], w["id"], take=False)
        return info.value.status_code

    assert asyncio.run(check()) == 404


def test_spectator_cannot_focus_into_someone_elses_workspace(tmp_path):
    s = build(tmp_path)

    async def check():
        g, entries, battle = await make_group_with_battle(s)
        w = await s.save_workspace({"name": "Main"})  # host-owned workspace
        invite = await s.invite("spectator")
        joined = await s.join({"credential": invite["credential"], "identity": {"display_name": "Spectator"}})
        await s.admit(joined["participant"]["id"], "admitted")
        principal = await s.authenticate(joined["token"], ("spectator",))
        with pytest.raises(AppError) as info:
            await s.focus_battle(battle["id"], w["id"], take=False, principal=principal)
        return info.value.status_code

    assert asyncio.run(check()) == 403


def test_spectator_can_focus_into_their_own_shared_workspace(tmp_path):
    s = build(tmp_path)

    async def check():
        g, entries, battle = await make_group_with_battle(s)
        invite = await s.invite("spectator")
        joined = await s.join({"credential": invite["credential"], "identity": {"display_name": "Spectator"}})
        await s.admit(joined["participant"]["id"], "admitted")
        principal = await s.authenticate(joined["token"], ("spectator",))
        w = await s.save_workspace({"name": "Mine"}, principal=principal)
        result = await s.focus_battle(battle["id"], w["id"], take=False, principal=principal)
        return result, entries

    result, entries = asyncio.run(check())
    assert result["workspace"]["draft"]["slots"]["b"] == entries[1]
