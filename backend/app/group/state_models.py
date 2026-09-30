"""Published state models: the shape of what `GroupService.filter_snapshot` hands to subscribers.

These TypedDicts document the wire contract for the broadcast overlays and the driver app. Each
graphic template names the models it needs (`GraphicTemplate.required_models`); the models are
composed into `PublishedSnapshot`, which is the full frame. A test compares them with a real
`public_state()` so they cannot drift from the code.

A value being `None` means "unavailable"; consumers label it as such and never infer game facts.
"""
from typing import Any, NotRequired, TypedDict


class EntryField(TypedDict):
    """One shared telemetry field of one entry (after the group's publication filter)."""
    value: Any
    source: str                    # 'reported' | 'derived'
    available: bool
    source_time: float | None
    received_time: float | None
    confidence: str


class Identity(TypedDict):
    display_name: str
    number: str
    team: str
    class_name: str
    driver_id: str
    roster: list[str]


class Flag(TypedDict, total=False):
    """A race-control instruction as it applies to one entry (also used in FlagState.instructions)."""
    id: str
    flag: str
    scope: str                     # 'global' | 'zone' | 'entry'
    target: str
    reason: str
    issuer: str
    effective: float
    expires: float | None
    cancelled: bool
    version: int
    expires_in: int | None
    applicability: str             # 'applies' | 'uncertain' (per-entry rows only)


class EntryRow(TypedDict):
    """One classified entry (a row of TimingState.entries)."""
    entry_id: str
    identity: Identity
    car: Any
    car_id: int | None
    stale: bool
    received: float | None
    last_ms: float | None
    best_ms: float | None
    reported_best_ms: float | None
    completed_laps: int | None
    progress: float | None
    D: float | None                # race distance in metres
    median_lap_ms: float | None
    in_pit: bool
    clock_uncertainty_ms: float | None
    quality: list[str]
    adjusted_laps: int | None
    penalty_ms: float
    adjusted_elapsed_ms: float | None
    disqualified: bool
    manual_order: int | None
    position: int | None
    gap_s: float | None
    lap_separation: int | None
    classification_source: str
    baseline_source: str | None
    fields: dict[str, EntryField]
    flags: list[Flag]


class SessionClock(TypedDict):
    state: str                     # 'draft' | 'running' | 'completed' | 'interrupted'
    started: float | None
    ended: float | None
    duration_s: int | None
    laps: int | None
    timeline: float                # frame time (already delayed for broadcast viewers)
    delay_s: NotRequired[float]


class RaceState(TypedDict):
    """Identity and geometry of the session being shown."""
    version: int
    group_id: str
    event_id: str
    session_id: str
    name: str
    event_name: str
    provenance: str                # 'live' | 'demo' | 'replay'
    format: str                    # 'practice' | 'qualifying' | 'laps' | 'timed' | 'manual'
    layout_id: str
    coverage: str
    map: list | None
    map_model: dict | None
    map_revision: str | None
    pending_map_revision: str | None
    zones: list[dict]
    loss: dict


class TimingState(TypedDict):
    entries: list[EntryRow]
    results: list[dict] | None     # finalized classification rows, once the host finalizes
    results_revision: int


class SelectedEntries(TypedDict, total=False):
    """Entries a graphic points at. Selection lives in the workspace program (slots), not in the
    frame: the renderer looks `workspace.slots[...]`/`graphic.entry_id` up in `entries`."""
    entries: list[EntryRow]
    workspace: dict


class FlagState(TypedDict):
    instructions: list[Flag]       # active (not cancelled or expired) instructions


class MessageEntry(TypedDict):
    id: str
    text: str
    scope: str
    target: str
    priority: int
    expires: float
    acknowledgement: bool
    public: bool
    issuer: str
    effective: float
    for_you: bool


class MessageState(TypedDict):
    messages: list[MessageEntry]


class Decision(TypedDict):
    id: str
    entry_id: str
    kind: str
    reason: str
    value: float
    status: str
    public: bool
    supersedes: str
    issuer: str
    utc: float


class DecisionState(TypedDict):
    decisions: list[Decision]      # public decisions only


class Battle(TypedDict):
    id: str
    epoch: int
    state: str                     # 'forming' | 'hot' | 'critical'
    ahead: str
    behind: str
    position: int | None
    gap_s: float | None
    gap_uncertainty_s: float
    closing_rate_s_per_s: float | None
    closing_per_lap_s: float | None
    heat: float
    confidence: str
    same_class: bool
    lapping: bool
    time_within_1s: float
    last_event: Any


class TrafficRow(TypedDict):
    entry_id: str
    number: str | None
    name: str | None
    D: float | None
    median_lap_s: float | None
    in_pit: bool
    battle_state: str | None


class BattleState(TypedDict):
    battles: list[Battle]          # empty for drivers
    traffic: list[TrafficRow] | None   # drivers only, and only when the host opted in


class ProjectionEntry(TypedDict):
    entry_id: str
    position: int | None
    projected_rank: int | None
    stops: int
    net_gap_s: float | None
    close_call: bool
    window: Any
    change: Any
    status: str


class Projection(TypedDict):
    entries: list[ProjectionEntry]
    summary: str | None
    pit_loss_source: str | None
    pit_loss_s: float | None
    coverage: dict                 # {'sharing': n, 'total': n}


class ProjectionState(TypedDict):
    projection: Projection | None  # None unless the group publishes fuel and strategy


class BrandingSnapshot(TypedDict):
    branding: dict                 # league branding merged with the event override (logos, colors, teams, sponsors)


class StewardCue(TypedDict):
    id: str
    decision_id: str
    kind: str
    status: str
    entry_id: str
    text: str
    created_t: float
    duration_s: int
    priority: int
    display_start: float


class StewardCueState(TypedDict):
    steward_cue_active: StewardCue | None


class PublishedSnapshot(RaceState, SessionClock, TimingState, FlagState, MessageState, DecisionState, BattleState,
                        ProjectionState, BrandingSnapshot, StewardCueState):
    """The full frame `public_state()` returns for a viewer."""
    workspace: NotRequired[dict]
    program_revision: NotRequired[int]
    taken_at: NotRequired[float | None]


# Model name -> TypedDict; graphic templates refer to these names.
STATE_MODELS: dict[str, type] = {
    model.__name__: model for model in (
        RaceState, TimingState, SelectedEntries, FlagState, MessageState, DecisionState, BattleState,
        ProjectionState, SessionClock, BrandingSnapshot, StewardCueState)}
STATE_MODELS['StewardCue'] = StewardCueState     # the cue channel is named StewardCue in templates
MODEL_NAMES = frozenset(STATE_MODELS)


def keys_of(model: type) -> frozenset[str]:
    """All keys a TypedDict declares, bases included."""
    return frozenset(model.__annotations__)
