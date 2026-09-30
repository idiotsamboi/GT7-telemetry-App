"""Phase 8 of the broadcast/spatial build (docs/AI_CONTEXT.md section 12):
GroupService.filter_snapshot only exposes 'traffic' to a driver principal when
the host opted in via GroupConfig.share_traffic_with_drivers, and never leaks
battle data (drivers never see battles) beyond a per-entry battle_state tag.
"""
import asyncio
import math
import time
from types import SimpleNamespace

import pytest

from backend.app.group.service import GroupService


def route():
    return [[100 * math.cos(i * math.tau / 100), 100 * math.sin(i * math.tau / 100)] for i in range(101)]


def build_group(tmp_path):
    s = GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / "db.sqlite"), config=SimpleNamespace(root=tmp_path)))
    s.running = True

    async def check():
        league = await s.league_save({"name": "Test league"})
        await s.create_group({"name": "Test", "event_name": "Test event", "league_id": league["id"], "layout_id": "10"})
        await s.set_map(route(), [])
        joined = []
        for n in range(2):
            invite = await s.invite("driver")
            j = await s.join({"credential": invite["credential"], "identity": {"display_name": f"Driver {n}", "number": str(n)}})
            await s.admit(j["participant"]["id"], "admitted")
            joined.append(j)
        principals = [await s.authenticate(j["token"], ("driver",)) for j in joined]

        def pos_at(t):
            angle = (t / 40.0) * math.tau
            return [100 * math.cos(angle), 0, 100 * math.sin(angle)]

        def send(n, t):
            body = {
                "group_id": s.active()["id"], "session_id": s.active()["session_id"], "participant_id": joined[n]["participant"]["id"],
                "entry_id": joined[n]["participant"]["entry_id"], "boot_id": "b", "sequence": int(t * 10) + 1,
                "source_mono": t, "source_utc": 1000.0 + t, "provenance": "live", "layout_id": "10", "local_session_id": "l",
                "values": {"position": pos_at(t), "lap": 0, "flags": 1},
            }
            s.telemetry(principals[n], body)

        send(0, 0.0); send(1, 0.0)
        await s.session_action("start")
        for i in range(1, 20):
            t = i * 0.3
            send(0, t)
            send(1, max(0.0, t - 0.3))
        for e in s.active()["entries"].values():
            e["baseline"] = 0
        for live in s.live.values():
            live["received"] = time.time()
        return principals[0], principals[1]

    driver0, driver1 = asyncio.run(check())
    return s, driver0, driver1


def test_traffic_is_none_for_drivers_by_default(tmp_path):
    s, driver0, driver1 = build_group(tmp_path)
    g = s.group(s.active()["id"])
    raw = s.raw_snapshot(g)
    data = s.filter_snapshot(raw, g, driver0)
    assert data["traffic"] is None


def test_traffic_is_none_for_non_driver_principals_even_when_shared(tmp_path):
    s, driver0, driver1 = build_group(tmp_path)
    g = s.group(s.active()["id"])
    g["share_traffic_with_drivers"] = True
    raw = s.raw_snapshot(g)
    data = s.filter_snapshot(raw, g, {"kind": "overlay", "group_id": g["id"], "subject": "x"})
    assert data["traffic"] is None


def test_traffic_is_basic_only_and_present_for_drivers_when_shared(tmp_path):
    s, driver0, driver1 = build_group(tmp_path)
    g = s.group(s.active()["id"])
    g["share_traffic_with_drivers"] = True
    raw = s.raw_snapshot(g)
    data = s.filter_snapshot(raw, g, driver0)
    traffic = data["traffic"]
    assert traffic and len(traffic) == 2
    row = traffic[0]
    assert set(row) == {"entry_id", "number", "name", "D", "median_lap_s", "in_pit", "battle_state"}
    # never raw telemetry/fuel values - only the basic classification fields
    assert "fuel_l" not in row and "speed_kmh" not in row


def test_traffic_battle_state_reflects_current_battles(tmp_path):
    s, driver0, driver1 = build_group(tmp_path)
    g = s.group(s.active()["id"])
    g["share_traffic_with_drivers"] = True
    gid = g["id"]
    entry_ids = list(g["entries"])
    s.battles[gid] = [{"id": "b1", "ahead": entry_ids[0], "behind": entry_ids[1], "state": "hot"}]
    raw = s.raw_snapshot(g)
    data = s.filter_snapshot(raw, g, driver0)
    states = {r["entry_id"]: r["battle_state"] for r in data["traffic"]}
    assert states[entry_ids[0]] == "hot" and states[entry_ids[1]] == "hot"


def test_public_projection_exposes_pit_loss_seconds_but_never_raw_fuel(tmp_path):
    s, driver0, driver1 = build_group(tmp_path)
    g = s.group(s.active()["id"])
    g["publication"] = list(set(g["publication"]) | {"fuel", "strategy"})
    g["format"] = "laps"
    g["laps"] = 10
    g["pit_loss_s"] = 27.5
    now = time.time()
    proj = s._compute_projection(g, now)
    assert proj is not None
    s.projections[g["id"]] = proj  # _public_projection reads from this cache, not _compute_projection's return
    public = s._public_projection(g)
    assert public is not None
    assert public["pit_loss_s"] == 27.5
    assert all("fuel_l" not in e for e in public["entries"])
