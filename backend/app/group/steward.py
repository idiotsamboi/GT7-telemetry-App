"""Automated stewarding graphics (docs/AI_CONTEXT.md section 6): turning a public
steward decision into a timed overlay cue, queued and prioritized so at most one
ever displays at once.
"""
from __future__ import annotations

from typing import Any

MAX_CUES = 16
DEFAULT_DURATION_S = 10

# Lower number = more urgent, matching this codebase's existing priority convention.
PRIORITY = {"disqualification": 0, "time": 1, "laps": 1, "investigation": 2, "warning": 3}


def cue_text(item: dict[str, Any], identity: dict[str, Any] | None) -> str:
    """The overlay line for one decision, per docs/AI_CONTEXT.md's template table."""
    identity = identity or {}
    tag = f"#{identity.get('number') or '?'} {identity.get('display_name') or 'Entry'}"
    reason = (item.get("reason") or "")[:80]
    kind, status, value = item["kind"], item.get("status", "open"), item.get("value", 0)
    if status == "withdrawn":
        return f"NO FURTHER ACTION · {tag}"
    base = {
        "investigation": f"UNDER INVESTIGATION · {tag} · {reason}",
        "incident": f"UNDER INVESTIGATION · {tag} · {reason}",
        "warning": f"WARNING · {tag} · {reason}",
        "time": f"{value:g} SECOND PENALTY · {tag}",
        "laps": f"{value:g} LAP PENALTY · {tag}",
        "disqualification": f"DISQUALIFIED · {tag}",
        "order": f"CLASSIFICATION ADJUSTED · {tag}",
        "correction": f"CORRECTION · {tag} · {reason}",
    }.get(kind, f"{kind.upper()} · {tag}")
    if status == "resolved":
        return "DECISION: " + base
    return base


def enqueue_steward_cue(
    cues: list[dict[str, Any]],
    item: dict[str, Any],
    identity: dict[str, Any] | None,
    popup_kinds: set[str],
    cued: set[tuple[str, str]],
    now: float,
) -> dict[str, Any] | None:
    """Append and return a new cue for this decision, or None if it doesn't
    qualify (private, an unlisted kind, or already cued for this exact status)."""
    if not item.get("public") or item["kind"] not in popup_kinds:
        return None
    key = (item["id"], item.get("status", "open"))
    if key in cued:
        return None
    cued.add(key)
    cue = {
        "id": item["id"] + ":" + item.get("status", "open"),
        "decision_id": item["id"],
        "kind": item["kind"],
        "status": item.get("status", "open"),
        "entry_id": item["entry_id"],
        "text": cue_text(item, identity),
        "created_t": now,
        "duration_s": DEFAULT_DURATION_S,
        "priority": PRIORITY.get(item["kind"], 3),
    }
    cues.append(cue)
    del cues[:-MAX_CUES]
    return cue


def active_cue(cues: list[dict[str, Any]], now: float) -> dict[str, Any] | None:
    """Which cue (if any) should be on screen at `now`, given the whole queue.

    Cues normally play back to back in arrival order; a higher-priority cue
    (lower PRIORITY number) cuts the current one short and starts immediately
    instead of waiting its turn. Pure function of the queue, so a delayed
    viewer's own cached `now` reproduces exactly what was on screen then.
    """
    ordered = sorted(cues, key=lambda c: c["created_t"])
    display_end = None
    current_priority = None
    result = None
    for cue in ordered:
        start = cue["created_t"]
        preempts = current_priority is not None and cue["priority"] < current_priority and display_end is not None and start < display_end
        effective_start = start if preempts else (max(start, display_end) if display_end is not None else start)
        end = effective_start + cue["duration_s"]
        if effective_start <= now < end:
            result = {**cue, "display_start": effective_start}
        display_end = end
        current_priority = cue["priority"]
    return result
