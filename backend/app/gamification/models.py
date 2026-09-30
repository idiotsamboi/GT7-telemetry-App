"""Typed public career foundation contracts; unknown metrics remain nullable."""
from typing import Any, Literal, TypedDict

class DriverProfile(TypedDict):
    id: str
    name: str
    driver_id: str
    display_name: str
    created_at: str
    total_xp: int
    eligible_sessions: int
    comparable_laps: int

class SkillProfile(TypedDict):
    category: str
    score: float | None
    confidence: float
    xp: int
    evidence_count: int
    source_id: str | None

class SessionScorecard(TypedDict):
    session_id: str
    driver_id: str
    created_at: str
    status: Literal['eligible', 'excluded']
    xp_awarded: int
    exclusions: list[str]
    evidence: dict[str, Any]


class XPEvent(TypedDict):
    id: str
    driver_id: str
    session_id: str
    source_id: str
    category: str
    amount: int
    created_at: str
    evidence: dict[str, Any]


class Achievement(TypedDict):
    definition_id: str
    title: str
    earned_at: str
    source_id: str
    evidence: dict[str, Any]
