"""Phase 4 of the broadcast/spatial build (docs/AI_CONTEXT.md section 6):
turning public steward decisions into timed, prioritized overlay cues.
"""
import asyncio
from types import SimpleNamespace

import pytest

from backend.app.group.service import GroupService
from backend.app.group.steward import active_cue, cue_text, enqueue_steward_cue


def identity(number="7", name="Driver"):
    return {"number": number, "display_name": name}


def item(kind="warning", status="open", public=True, value=0, reason="Track limits", entry_id="e1", id_="d1"):
    return {"id": id_, "kind": kind, "status": status, "public": public, "value": value, "reason": reason, "entry_id": entry_id}


def test_cue_text_templates_match_the_spec_table():
    assert cue_text(item(kind="investigation"), identity()) == "UNDER INVESTIGATION · #7 Driver · Track limits"
    assert cue_text(item(kind="warning"), identity()) == "WARNING · #7 Driver · Track limits"
    assert cue_text(item(kind="time", value=5), identity()) == "5 SECOND PENALTY · #7 Driver"
    assert cue_text(item(kind="laps", value=1), identity()) == "1 LAP PENALTY · #7 Driver"
    assert cue_text(item(kind="disqualification"), identity()) == "DISQUALIFIED · #7 Driver"
    assert cue_text(item(kind="time", value=5, status="resolved"), identity()) == "DECISION: 5 SECOND PENALTY · #7 Driver"
    assert cue_text(item(status="withdrawn"), identity()) == "NO FURTHER ACTION · #7 Driver"


def test_enqueue_skips_private_and_unlisted_kinds():
    cues = []
    cued = set()
    kinds = {"warning", "time", "laps", "disqualification", "investigation"}
    assert enqueue_steward_cue(cues, item(public=False), identity(), kinds, cued, 0.0) is None
    assert enqueue_steward_cue(cues, item(kind="order"), identity(), kinds, cued, 0.0) is None
    assert cues == []


def test_enqueue_dedupes_same_decision_and_status():
    cues = []
    cued = set()
    kinds = {"warning"}
    first = enqueue_steward_cue(cues, item(), identity(), kinds, cued, 0.0)
    again = enqueue_steward_cue(cues, item(), identity(), kinds, cued, 1.0)
    assert first is not None and again is None and len(cues) == 1


def test_enqueue_treats_a_status_change_as_a_new_cue():
    cues = []
    cued = set()
    kinds = {"warning"}
    enqueue_steward_cue(cues, item(status="open"), identity(), kinds, cued, 0.0)
    second = enqueue_steward_cue(cues, item(status="resolved"), identity(), kinds, cued, 5.0)
    assert second is not None and len(cues) == 2


def test_active_cue_plays_cues_back_to_back():
    cues = [
        {"id": "a", "created_t": 0.0, "duration_s": 10, "priority": 3},
        {"id": "b", "created_t": 2.0, "duration_s": 10, "priority": 3},
    ]
    assert active_cue(cues, 5.0)["id"] == "a"
    assert active_cue(cues, 12.0)["id"] == "b"  # b waits for a to finish, not its own created_t
    assert active_cue(cues, 25.0) is None


def test_higher_priority_cue_preempts_and_cuts_the_current_one_short():
    cues = [
        {"id": "warn", "created_t": 0.0, "duration_s": 10, "priority": 3},
        {"id": "dq", "created_t": 3.0, "duration_s": 10, "priority": 0},
    ]
    assert active_cue(cues, 2.0)["id"] == "warn"
    assert active_cue(cues, 3.0)["id"] == "dq"  # cut over exactly at the preempting cue's arrival
    assert active_cue(cues, 12.0)["id"] == "dq"


def test_lower_priority_cue_does_not_preempt():
    cues = [
        {"id": "dq", "created_t": 0.0, "duration_s": 10, "priority": 0},
        {"id": "warn", "created_t": 3.0, "duration_s": 10, "priority": 3},
    ]
    assert active_cue(cues, 3.0)["id"] == "dq"  # dq keeps playing
    assert active_cue(cues, 10.0)["id"] == "warn"  # warn only starts once dq's window ends


def build(tmp_path):
    return GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / "db.sqlite"), config=SimpleNamespace(root=tmp_path)))


def test_group_service_public_decision_produces_an_overlay_cue(tmp_path):
    s = build(tmp_path)

    async def check():
        league = await s.league_save({"name": "L"})
        await s.create_group({"name": "T", "event_name": "T", "league_id": league["id"]})
        invite = await s.invite("driver")
        j = await s.join({"credential": invite["credential"], "identity": {"display_name": "Driver", "number": "9"}})
        await s.admit(j["participant"]["id"], "admitted")
        await s.decision({"entry_id": j["participant"]["entry_id"], "kind": "warning", "reason": "Track limits", "value": 0, "public": True})
        return s.active()

    g = asyncio.run(check())
    assert len(g["steward_cues"]) == 1
    snap = s.raw_snapshot(g)
    assert snap["steward_cue_active"] is not None
    assert "WARNING" in snap["steward_cue_active"]["text"]


def test_group_service_private_decision_produces_no_cue(tmp_path):
    s = build(tmp_path)

    async def check():
        league = await s.league_save({"name": "L"})
        await s.create_group({"name": "T", "event_name": "T", "league_id": league["id"]})
        invite = await s.invite("driver")
        j = await s.join({"credential": invite["credential"], "identity": {"display_name": "Driver", "number": "9"}})
        await s.admit(j["participant"]["id"], "admitted")
        await s.decision({"entry_id": j["participant"]["entry_id"], "kind": "warning", "reason": "x", "value": 0, "public": False})
        return s.active()

    g = asyncio.run(check())
    assert g["steward_cues"] == []


def test_group_service_cancel_removes_a_cue(tmp_path):
    s = build(tmp_path)

    async def check():
        league = await s.league_save({"name": "L"})
        await s.create_group({"name": "T", "event_name": "T", "league_id": league["id"]})
        invite = await s.invite("driver")
        j = await s.join({"credential": invite["credential"], "identity": {"display_name": "Driver", "number": "9"}})
        await s.admit(j["participant"]["id"], "admitted")
        await s.decision({"entry_id": j["participant"]["entry_id"], "kind": "warning", "reason": "x", "value": 0, "public": True})
        cue_id = s.active()["steward_cues"][0]["id"]
        await s.cancel_steward_cue(cue_id)
        return s.active()

    g = asyncio.run(check())
    assert g["steward_cues"] == []


def test_group_service_pausing_auto_steward_suppresses_new_cues(tmp_path):
    s = build(tmp_path)

    async def check():
        league = await s.league_save({"name": "L"})
        await s.create_group({"name": "T", "event_name": "T", "league_id": league["id"]})
        invite = await s.invite("driver")
        j = await s.join({"credential": invite["credential"], "identity": {"display_name": "Driver", "number": "9"}})
        await s.admit(j["participant"]["id"], "admitted")
        await s.set_steward_paused(True)
        await s.decision({"entry_id": j["participant"]["entry_id"], "kind": "warning", "reason": "x", "value": 0, "public": True})
        return s.active()

    g = asyncio.run(check())
    assert g["steward_cues"] == []


def test_group_service_queue_priority_end_to_end(tmp_path):
    s = build(tmp_path)

    async def check():
        league = await s.league_save({"name": "L"})
        await s.create_group({"name": "T", "event_name": "T", "league_id": league["id"]})
        invite = await s.invite("driver")
        j = await s.join({"credential": invite["credential"], "identity": {"display_name": "Driver", "number": "9"}})
        await s.admit(j["participant"]["id"], "admitted")
        await s.decision({"entry_id": j["participant"]["entry_id"], "kind": "warning", "reason": "x", "value": 0, "public": True})
        await s.decision({"entry_id": j["participant"]["entry_id"], "kind": "disqualification", "reason": "y", "value": 0, "public": True})
        return s.active()

    g = asyncio.run(check())
    assert len(g["steward_cues"]) == 2
    assert active_cue(g["steward_cues"], g["steward_cues"][0]["created_t"])["kind"] == "warning"
    assert active_cue(g["steward_cues"], g["steward_cues"][1]["created_t"])["kind"] == "disqualification"
