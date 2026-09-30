# Implementation Spec: Broadcast Action Director + Spatial Strategy & Coaching
<!-- For: the implementing agent (Claude Code / Codex). All design decisions are made here. Implement exactly; where this spec and the code disagree on names, follow the code's existing names but keep the behaviour. Written 2026-09-29 against the current source (see docs/AI_CONTEXT.md). -->

## 0. How to use this document
- **Read first**:
  - `docs/AI_CONTEXT.md`
  - `backend/app/group/service.py` (`raw_snapshot`, `delayed_snapshot`, `filter_snapshot`, `public_state`, `classification`, `decision`, `take`, the packet ingest that sets `self.live[entry_id]`)
  - `group/models.py`, `group/client.py`, `group/timing.py`
  - `backend/app/runtime.py`, `sessions.py`, `analytics.py`, `live_delta.py`, `live_analysis.py`, `engineer.py`, `requests.py`, `local_ai.py`
  - `track_model.py` (`TrackProgress.candidates`), `track_catalogue.py`, `track_recognition.py`
  - `frontend/src/RaceDesk.tsx` (the race director desk; the feature request calls it "GroupDesk"), `GroupStudio.tsx`, `GroupGraphics.tsx`, `main.tsx`
- **Build order is mandatory** (§11): Phase 0 (v3 track wiring) comes before everything spatial.
- **Project rules still apply**:
  - Values are always reported, calculated (labelled) or unavailable, never invented.
  - Server-side permission filtering; bounded memory and queues; nothing heavy in the UDP receive path.
  - Live/demo/replay isolation.
  - New code is readable: one statement per line, type hints, docstrings.

## 1. Design corrections to the original feature request (binding)
These fix assumptions in the request that don't match the code or the data GT7 provides.

| Request said | Reality | Decision |
|---|---|---|
| Battle Index uses `live_delta` | `live_delta` is one driver vs **their own** reference lap; group packets don't carry it | Gaps between cars use **host-side distance-time history** (interval gap = when the car behind reaches the point where the car ahead was) |
| "Average pit-stop time for the v3 layout" | No layout pit-loss data exists; the gt7info `PitLaneDelta` isn't shipped (licence unconfirmed) | Pit loss comes from, in order: host-entered value → learned from observed stops in this event → unavailable (projection hidden) |
| Qwen writes micro-coaching sentences | 0.5B models hallucinate numbers; the project forbids invented facts | Deterministic templates produce every sentence with numbers. Qwen only **selects/orders** evidence (existing role); optional rephrase is accepted only if every number in its output appears in the evidence (§8.6) |
| "Stay out two laps to overcut the traffic in sector two" | The driver's app has no opponent data; sectors are not official | Needs host opt-in `share_traffic_with_drivers`. Output names cars and gaps, not "sector two" (custom corner names only if the v3 model has them) |
| "Push for two laps to build a 20 s gap" | You can't know if a gap is buildable | Fuel branches are **Save**, **Splash**, and (group only) a **Gap check** against the car behind, using measured intervals |
| `penalty/investigation` pops for any decision | Decisions default `public=False`; private decisions must never reach OBS | Auto-popup only for `public=True` decisions, respecting the broadcast delay |
| Tyre "degradation" alert | Surface temperature is not wear | Name it **tyre heating-rate alert**; wording never mentions wear |

## 2. Shared foundations (build these once, used by several features)

### 2.1 Race distance `D` (per entry, host side)
`D = completed_laps * L + s`, where:
- `L` is the layout length in metres: v3 `TrackProgress.length`, otherwise the legacy projector length (compute `Projection.length` in metres; it already exists).
- `s` is progress in metres: `sample['progress'] * L` (legacy gives a fraction), or v3 `Progress.s`.
- `completed_laps` comes from `classification()` (`lap − baseline`, respecting counter resets). Laps come from the lap counter, not from `s` wrapping.
- Validity: `D` is valid only if the entry is not stale, `layout_compatible` is true, progress is not None, and not `counter_reset`. Otherwise `D = None`.
- Wrap guard: if `s` jumped more than 150 m backwards without a lap increment, set `D = None` for that tick (the projector should prevent this; be defensive).

### 2.2 Common timeline `T`
Use a clock-corrected source time: `T = packet.source_utc − clock_offset_ms/1000` for that participant's boot. The offset is already measured by the ping/clock exchange in `client.py`; store `offset_ms` next to `uncertainty_ms` in `self.boots` if it isn't already stored. If no offset is known, fall back to host receipt time and add 250 ms to the uncertainty.

### 2.3 `DistanceHistory` (new: `backend/app/group/history.py`)
```python
class DistanceHistory:
    """Per-entry bounded (T, D) samples, monotonic in D, 5 Hz, 180 s."""
    MAX_AGE_S = 180
    MIN_STEP_S = 0.2                      # decimate to <= 5 Hz

    def __init__(self):
        self.t = deque()                  # float timeline seconds
        self.d = deque()                  # float metres (monotonic non-decreasing)

    def add(self, T, D):
        if D is None: return
        if self.t and T - self.t[-1] < MIN_STEP_S: return
        if self.d and D < self.d[-1] - 5.0:     # regression (reset/teleport)
            self.clear(); 
        self.t.append(T); self.d.append(max(D, self.d[-1]) if self.d else D)
        while self.t and T - self.t[0] > MAX_AGE_S: popleft both

    def time_at(self, D):
        """Timeline when this car was at distance D; None if outside history."""
        if not self.d or D < self.d[0] or D > self.d[-1]: return None
        i = bisect_left(self.d, D)        # convert deques to lists lazily per tick (see perf note)
        if self.d[i] == D: return self.t[i]
        return lerp(self.t[i-1], self.t[i], (D - self.d[i-1]) / (self.d[i] - self.d[i-1]))
```
- Store it in `GroupService.histories: dict[entry_id, DistanceHistory]`.
- Feed it from the packet-ingest path right after `self.live[...]` is set. Reset it on session change and on entry stream change.
- **Performance**: 16 entries × 900 points is tiny. Per worker tick, snapshot each deque into a list once (`list(self.d)`) before running bisects.

### 2.4 Interval gap between an entry behind (B) and the one ahead (A)
```python
def interval(hA, hB, D_B, T_now):
    """Seconds B is behind A at B's current position. None if unknown."""
    tA = hA.time_at(D_B)                  # when A passed where B is now
    if tA is None: return None            # A passed there > 180 s ago (lapped / huge gap)
    return T_now_B - tA                   # T_now_B = B's latest T
gap_uncertainty = sqrt(uA**2 + uB**2)/1000 + 0.05   # clock uncertainties (ms) + 50 ms interpolation
```
- If `D_A − D_B > L/2`, they're on different laps; mark `lapping=True` (§3.3).

### 2.5 Pit-state detection (host side, per entry)
- **In pit**: the v3 model has a `pit_lane` polyline and the position is within 12 m of it for more than 1 s. Without a pit lane: speed < 90 km/h for more than 4 s **and** the entry is within 60 m of the start/finish region **and** it's not a slow corner (the reference speed at that `s` is above 120 km/h). Label heuristic detections `inferred`.
- **Stop completed**: the fuel value increases by 1 L or more (requires fuel sharing), **or** the entry was in pit state for more than 8 s and then exited.
- Record `PitStop{entry_id, lap, T_in, T_out, fuel_before, fuel_after, lap_time_ms}` in `g['pit_stops']` (bounded to 256 per session, persisted with `commit_group`).
- **Learned pit loss** = median over stops of `(pit_lap_ms + next_lap_ms − 2 × median_clean_lap_ms_of_that_entry)` / 1000. Needs at least 1 stop; label `learned (n stops)`.
- **Learned refuel rate** = median `(fuel_after − fuel_before) / stationary_s`, where `stationary_s` is the time spent below 2 km/h during the stop.

### 2.6 v3 track wiring (Phase 0; spatial features depend on it)
Create `backend/app/track_service.py`:
```python
class TrackService:
    """Owns the v3 recognizer + locked TrackProgress. Runs in the existing track worker, not the UDP loop."""
    def __init__(self, root, settings):
        self.recognizer = track_catalogue.new_recognizer(overrides=load_user_models(root))
        self.locked: TrackProgress | None = None
        self.last_progress: Progress | None = None
        self.lock_lock = threading.Lock()

    def observe(self, sample):            # called from runtime track worker at <= 20 Hz (decimated)
        result = self.recognizer.update(...)          # use existing signature
        if result.state == 'locked' and (self.locked is None or self.locked.layout_id != result.layout_id):
            self.locked = TrackProgress(track_bundle.get_model(result.layout_id))
        elif result.state != 'locked': self.locked = None

    def project(self, position, heading=None, previous_s=None, expected_m=None) -> Progress | None:
        if not self.locked: return None
        branches = self.locked.candidates(position, heading=heading, previous_s=previous_s, expected_m=expected_m)
        return branches[0][1] if branches else None
```
- **Runtime**:
  - Instantiate it in `Runtime.__init__`.
  - In `consume(s)`, keep a lightweight per-sample projection (`project(...)` with `previous_s`) **only when locked**; target ≤ 0.2 ms per sample. Store `self.progress_s`.
  - If profiling shows more than 0.2 ms per sample, project at 20 Hz and interpolate `s` by `speed × dt`.
- **Manual selection**: `TrackSelect` calls both `track_map.select` (legacy, unchanged) and `recognizer.select`.
- **Precedence**: a v3 lock is authoritative for `s`. The legacy `TrackMap` keeps drawing learned lines until the map UI migrates.
- **State**: add `state['track'] = {layout_id, state, confidence, s, lap_fraction, corner: {id,name}|None, source:'v3'|'legacy'|'none'}`.
- **Group host**: when `g['layout_id']` has a v3 model, `GroupService.projectors[g['id']]` uses a `TrackProgressAdapter`. It exposes `.project(position, previous_fraction) → fraction` (so existing callers keep working) and `.length`. The legacy `Projection` stays as a fallback for user-supplied maps.
- **Acceptance for Phase 0**: existing tests stay green; replaying the recorded Willow Springs lap locks and yields monotonic `s`; per-sample projection p95 ≤ 0.2 ms on the dev PC.

## 3. Feature A: Battle Index (heat scoring)

### 3.1 Worker
- In `GroupService`, add `battle_task`: an asyncio loop at **2 Hz**, started with the group session and cancelled at session end or close.
- Each tick it computes the battles from **raw** (undelayed) data and stores `self.battles[group_id] = BattleSet`.
- `raw_snapshot()` includes `battles` so that `delayed_snapshot` and the broadcast delay apply automatically to overlays and spectators. The host desk reads raw.

### 3.2 Pair selection per tick
```python
rows = [r for r in classification(g, now) if r valid D and not stale and not in_pit]
rows.sort(key=lambda r: -r.D)                      # race order by distance (not the classification order)
pairs = adjacent(rows)                              # (ahead, behind) consecutive
if g has classes: pairs += adjacent(rows filtered by same class) not already in pairs
```
Cap at 48 pairs.

### 3.3 Metrics per pair (A ahead, B behind)
- `gap` = `interval(hA, hB, D_B, T_B)` in seconds, plus `gap_unc`.
- `samples` = the pair's gap ring buffer: `deque(maxlen=60)` of (T, gap), i.e. 30 s at 2 Hz. Store it in `self.pair_state[(A,B)]`.
- `closing_rate` = OLS slope of gap vs T over the last 30 s, in s/s. **Negative means B is catching.** Requires ≥ 10 points spanning ≥ 8 s; otherwise None.
- `closing_per_lap` = `closing_rate × median_lap_s` (display only).
- `time_within_1s` = continuous seconds with gap ≤ 1.0 (resets when gap > 1.2).
- `lapping` = `D_A − D_B > L/2`. These are excluded unless the setting `battles_include_lapping` is on (default False). When included, label them "Lapping".
- `position` = the **race-distance order** index of B (1-based).
- `same_class` = both entries' `class_name` values are equal.

### 3.4 Heat score (0–100)
```python
f_gap   = clamp((2.0 - gap) / (2.0 - 0.2), 0, 1)              # 2.0 s -> 0, 0.2 s -> 1
f_close = clamp(-closing_rate / 0.02, 0, 1) if closing_rate is not None else 0   # 0.02 s/s = 1.2 s/min
f_pos   = 1.0 if position <= 3 else 0.8 if position <= 6 else 0.6 if position <= 10 else 0.4
f_class = 1.0 if same_class else 0.5
f_dur   = clamp(time_within_1s / 60, 0, 1)
heat = 100 * (0.40*f_gap + 0.30*f_close + 0.10*f_pos*f_class + 0.20*f_dur)
if gap_unc > gap / 2: heat *= 0.5; confidence = 'low'   else confidence = 'ok'
```
- Weights and thresholds are settings (§10) but have these defaults.
- Heat is not an official metric; label it "Battle heat".

### 3.5 States and alerting (hysteresis)

| State | Enter | Exit |
|---|---|---|
| `forming` | heat ≥ 40 | heat < 30 for 5 s |
| `hot` | heat ≥ 70 | heat < 55 for 5 s → `forming` |
| `critical` | gap < 0.5 s **and** closing_rate < 0 (or gap < 0.3 s), sustained 3 s | gap > 0.8 s for 5 s → `hot`/`forming` |
| `ended` | pair no longer adjacent, or either car stale/in pit for > 10 s | — |

- Each battle has `id = f"{A}:{B}:{epoch}"`. The epoch increments when a pair re-forms after `ended`.
- **Swap handling**: if the order flips between the same two cars within 20 s, keep the same battle id, swap A/B, and set `last_event='overtake'`. This is where "position change" events come from.
- **Desk alert** (`g['desk_alerts']` bounded deque of 32, raw only, host-visible), created on:
  - entering `hot` (priority 2);
  - entering `critical` (priority 1);
  - an overtake inside a tracked battle (priority 1).

  A cooldown of 90 s per battle id applies per alert type.
- Alert payload:
  ```
  {id, battle_id, kind:'hot'|'critical'|'overtake', created_T, entries:[A,B], position, gap, closing_per_lap, heat, confidence, text}
  ```
  Text template: `"P{pos} battle: #{numA} {nameA} vs #{numB} {nameB} — {gap:.1f}s, closing {abs(cpl):.1f}s/lap"`.

### 3.6 Data exposure and permissions
- A battle uses only `basic` data (positions, laps). Include it in the spectator/overlay snapshot when `basic` is published.
- Desk alerts are host-only; driver snapshots get no battles.
- `filter_snapshot` must drop battles involving entries that are not visible to the principal.

### 3.7 Desk UI (`RaceDesk.tsx`)
- A new **Battles** panel above the timing table:
  - A list sorted by state (critical > hot > forming), then heat.
  - Each row: a heat bar with the value; a state chip (critical: red + "CRITICAL" text; hot: amber; forming: blue); car numbers and names; gap; closing per lap with ▲/▼; the "Lapping" tag; low-confidence styling (grey + "low confidence").
- **Alert toasts**: a critical alert makes a toast slide in at the top right (no sound by default; optional "desk chime" setting). Clicking it scrolls to and highlights the row.
- **Row actions**: **Focus → Draft**, **Focus & Take**, **Dismiss** (suppresses that battle id's alerts for 5 minutes).

## 4. Feature B: Auto-populating overlays from a battle

### 4.1 API (local admin)
`POST /api/group/battles/{battle_id}/focus`
```json
{ "workspace_id": "…", "take": false, "ensure_graphics": true }
```
- It's also allowed on the public API for spectators, but only for their own or shared workspaces (reuse the `workspace()` permission check). A spectator only sees battles that pass their filter.

### 4.2 Server logic
```python
async def focus_battle(battle_id, workspace_id, take, ensure_graphics, principal=None):
    b = current battle (raw for host, delayed/filtered for spectator); 404 if absent or ended > 30 s ago
    w = workspace(workspace_id, principal)
    draft = clone(w['draft'])
    draft['slots']['a'] = b.ahead                # head-to-head left = car ahead
    draft['slots']['b'] = b.behind               # right = attacker
    draft['slots']['primary'] = b.behind         # selected-car telemetry follows the attacker
    draft['selection_mode'] = 'manual'
    warnings = []
    if ensure_graphics:
        for template, default_rect in (('comparison', (460, 760, 1000, 300)), ('telemetry', (1260, 780, 620, 260))):
            g = first graphic in draft with template == template
            if g is None and len(draft['graphics']) < 20:
                draft['graphics'].append(new Graphic(id=uid(), template=template, x,y,w,h=default_rect,
                                                     slot=('a' if template=='comparison' else 'primary'), visible=True))
            elif g and g['entry_id']:
                warnings.append(f"{template} is locked to an entry; left unchanged")
            elif g: g['visible'] = True
    save_workspace(draft, id=workspace_id, principal)      # validates, bumps draft_revision
    if take: await take(workspace_id, principal)            # atomic program publish
    log group event 'battle_focused' {battle_id, workspace_id, take}
    return {workspace, warnings}
```
- The comparison graphic already renders slots a and b. Confirm this in `GroupGraphics.tsx`; if it reads `primary` and `a`, map accordingly and document which is which.
- **Don't** auto-take unless `take=true`. There's also a workspace setting `battle_auto_take` (default False). When it's on, the desk's Focus button takes immediately.
- **Optional new graphic** `battle_tag` (500 × 120, basic): "BATTLE FOR P{pos}", both numbers, gap and closing arrow, bound to slots a/b. Add it to `GRAPHICS`, the `Graphic.template` Literal, and the renderer, and count it in the docs.
- **UI**: after a focus, the Studio shows the toast "Draft updated from battle P4 (#12 vs #7)". Warnings appear inline.

## 5. Feature C: Net position and pit-window projector

### 5.1 Inputs per entry (host side, needs `fuel` + `strategy` sharing from that member)
- `fuel_l`, `capacity_l` (the `fuel` category).
- `strategy.litres_per_lap`, `strategy.laps_remaining` (fuel laps); this is already a permitted packet field.
- If `strategy.litres_per_lap` is missing but the host observed 3+ clean laps with fuel data, compute the median burn host-side. Label it `host-calculated`.
- `D`, `completed_laps`, the interval to the leader (`gap_to_leader`: the sum of adjacent intervals along the race-distance order, or a direct `interval(leaderHist, h, D, T)` when available).
- **Race remaining**:
  - `laps` format: `laps_left = g.laps − completed_laps − s/L`.
  - `timed` format: `laps_left = ceil_frac((duration_s − elapsed_s) / leader_median_lap_s) + (1 if extra_lap)`. Mark it `estimate` and show the ±1 lap band.
  - `practice`/`qualifying`/`manual`: the projector is disabled ("not a race session").

### 5.2 Stop model
```python
stop_cost_s(entry, fuel_to_add_l):
    loss = settings.pit_loss_s (host-entered event value) or learned_pit_loss or None
    rate = settings.refuel_rate_lps or learned_refuel_rate or None
    if loss is None: return None
    refuel_s = fuel_to_add_l / rate if rate else 0      # if rate unknown: flag 'refuel time excluded'
    return loss + refuel_s

stops_needed(entry):
    need_l = laps_left * burn + reserve_l(host setting, default 1.0)
    deficit = need_l - fuel_l
    if deficit <= 0: return 0, 0.0
    usable_tank = capacity_l - reserve_l
    n = ceil(deficit / usable_tank)
    return n, deficit                       # add exactly the deficit split across n stops
```

### 5.3 Projection
```python
for e in eligible:                           # has burn, fuel, capacity, gap_to_leader
    n, add_l = stops_needed(e)
    cost = stop_cost_s(e, add_l) if n else 0.0
    if n and cost is None: e.status = 'pit loss unknown'; continue
    e.net_gap = e.gap_to_leader + n_pending_cost(e)     # = cost (includes all n stops' losses: n*loss + add_l/rate)
    e.stops = n
unc(e) = gap_unc + (0.15 * cost if pit loss learned from <3 stops else 0.05*cost) + burn_spread * laps_left * (loss per litre? no) -> keep: 0.1*cost if timed estimate
order = sort(eligible_with_net_gap, key=net_gap)
mark pairs whose |net_gap_i − net_gap_j| < unc_i + unc_j as '≈' (too close to call)
```
- Entries with a pit stop already completed that covers the deficit get `n = 0`.
- Recompute at **0.5 Hz**, only in race formats, and only while at least one entry has `n > 0`. Otherwise show "No stops required by current estimates".
- **Pit window** per entry: `window_open_lap = max(current_lap, laps_total − floor((fuel_l_after_min_add + fuel_l − reserve)/burn))`, `window_close_lap = current_lap + floor((fuel_l − reserve)/burn)` (the last lap they can reach on the current fuel). Show "L{open}–L{close}".

### 5.4 Exposure
- The projection publishes only if the group `publication` includes **both** `fuel` and `strategy`; otherwise it's host-only.
- Spectator/overlay data: rank, entry, stops, net_gap, "≈" flag, window. No raw fuel litres unless `fuel` is published (it is, by the rule above).

### 5.5 New graphic `net_order`
- **Registry entry**: `('Projected order after stops', 800, 640)`, required sharing `fuel` + `strategy`.
- **Title**: "PROJECTED ORDER AFTER STOPS". Subtitle: "Estimate · pit loss {x}s ({source})".
- **Rows**: projected rank, number, name, stops pending (●), net gap (+x.x s), "≈" chip, and the change vs current position (▲2 / ▼1 / =).
- **Footer**: "{n} of {m} cars share fuel data". When coverage is incomplete, show "Connected-group estimate".
- **Hidden**: when not a race format or no projection. Show a stale state when the inputs are stale for more than 5 s.

### 5.6 Host inputs (Race Control → Session setup)
- `pit_loss_s` (optional, 5–120) and `refuel_rate_lps` (optional, 0.5–20).
- The "Learned" readouts show values and n. A "Use learned" button copies the learned value into the host setting.

## 6. Feature D: Automated stewarding graphics

### 6.1 Trigger
In `decision()` after the commit, and in any decision **update** path: if the decision is being created or its status changes, call `enqueue_steward_cue(g, item)`. The cue is created only when all of these hold:
- `item['public']` is True;
- `item['kind'] in settings.steward_popup_kinds` (default `{'investigation','warning','time','laps','disqualification'}`; `incident`, `order` and `correction` are off by default);
- the de-duplication key `(decision_id, status)` hasn't been cued before (store the keys in `g['cued']`, bounded to 512).

### 6.2 Cue model
- Stored per group, not per workspace, so every workspace with auto-cues enabled shows it:
  ```
  {id, decision_id, kind, status, entry_id, text, created_T, duration_s: 10, priority}
  ```
- **Text templates**:

  | Case | Text |
  |---|---|
  | investigation / open | "UNDER INVESTIGATION · #{num} {name} · {reason}" |
  | warning | "WARNING · #{num} {name} · {reason}" |
  | time | "{value:g} SECOND PENALTY · #{num} {name}" |
  | laps | "{value:g} LAP PENALTY · #{num} {name}" |
  | disqualification | "DISQUALIFIED · #{num} {name}" |
  | status → resolved | "DECISION: " + the kind line |
  | status → withdrawn | "NO FURTHER ACTION · #{num} {name}" |

  Reasons are truncated to 80 characters.
- **Queue**: `g['steward_cues']` ordered by created_T, bounded to 16. Only one cue displays at a time. The next starts when the previous `created_T + duration` has passed on the timeline. Priority order: disqualification > time/laps > investigation > warning. A higher-priority cue can pre-empt: the current cue ends and the next starts.

### 6.3 Overlay rendering
- Cues ride in `raw_snapshot()['steward_cue_active']`, computed from the queue against the snapshot timeline. The broadcast delay therefore applies automatically.
- **Per workspace**: add `WorkspaceConfig.auto_steward: bool = True` and `steward_popup_graphic_id: str = ''` (which penalty graphic to use).
  - If empty, use the first `penalty` graphic in the program.
  - If the program has none, render a transient penalty graphic at the default rect (460, 90, 1000, 160). It isn't added to the program document.
- The renderer shows the active cue for `duration_s` with the existing popup animation, then returns to its normal behaviour (latest public decisions, or hidden if `duration_s` was configured as a popup).
- **Desk**: a "Steward cue queue" strip with Cancel per cue (`DELETE /api/group/steward-cues/{id}`) and a "Pause auto cues" toggle for the group.

## 7. Feature E: Tyre heating-rate alert (solo + group)

### 7.1 Signal processing (runtime, 5 Hz, per tyre i in FL, FR, RL, RR)
```python
if not driving or speed_kmh < 60 or paused or loading: skip sample
T = tyres[i] (finite)                                # surface temperature
ema_i = ema_i + α (T - ema_i), α = 0.2               # ~1 s smoothing at 5 Hz
if track locked (v3):
    bin = int(s // 100)                              # 100 m bins
    base = baseline[i][bin]                          # EMA across laps of ema at this bin, β = 0.3 per lap visit
    anomaly = ema_i - base  (only when that bin has been visited >= 2 laps)
    update baseline[i][bin] at bin exit
else:
    anomaly = ema_i - rolling_mean_i(last 90 s)      # fallback, weaker
rate_i = OLS slope of anomaly over trailing 20 s   (°C/s), need >= 60 points
```
The v3 path compares like with like: temperature at the same place on track vs previous laps, so normal corner-by-corner heating cancels out.

### 7.2 Alert rule (add to `engineer.RULES`)
```python
'tyre_heat_rate': {priority: 2, persist: 8, prerequisite: '2 warm-up laps completed since session start or refuel/pit; v3 lock preferred',
                   entry: 'rate_i >= 0.15 °C/s and anomaly_i >= +4 °C (both sustained)',
                   exit:  'rate_i < 0.05 °C/s or anomaly_i < +2 °C'}
```
- **Cooldown**: 120 s per tyre, and 60 s globally for this rule.
- **Suppressed**: during the first 2 completed laps, for 1 lap after a detected pit/refuel, when fewer than 4 tyres are finite, and in Quiet/Critical-only modes (P2 rules).
- **Grouping**: if both fronts trigger within 5 s, send one "fronts" message; likewise both rears or both of one side.
- **Messages** (template; never mentions wear or grip):
  - `"{Tyre name} heating fast: plus {anomaly:.0f} degrees over your usual at this point. Ease the entry or check your line."`
  - Fronts: `"Front tyres heating fast, plus {x:.0f} degrees. Consider a smoother entry."`
- **Evidence** logged: rate, anomaly, bin, laps of baseline.
- **Live analysis state**: `tyre_heat {rates[4], anomalies[4], method:'track-position baseline'|'time baseline'}`. Wheel TYRES page: show "▲ heating" on the affected tyre tile.
- **Tests**: positive (a synthetic ramp), negative (normal cyclical corner heating with v3 bins), noisy (±3 °C noise gives no alert), stale (no alert when stale), warm-up suppression.

## 8. Feature F: Spatial braking and micro-coaching (solo; works in group for the local driver)

### 8.1 Per-lap spatial timing trace (runtime)
- For the current lap keep `lap_time_at[bin]` with 10 m bins: when `s` crosses a bin boundary, record the elapsed lap time (the game's current_ms if C fields are trusted, else accumulated monotonic time since the lap started). Also keep per bin: min speed, max brake, throttle.
- Storage: an `array('f')` of `ceil(L/10)` entries (a 6 km track needs 600 floats).
- **Close the lap**: if the lap is complete and comparable, store `SpatialLap{lap_id, layout_id, car_id, times[], speed_min[], brake_max[], throttle[]}` in the session (in memory; persist into the lap payload JSON as a compact list rounded to ms and 0.1 km/h).
- **Reference**: the existing `sessions.reference` lap. It needs a `SpatialLap` with the same `layout_id`. A different `car_id` means a warning ("reference used a different car"), not a block.
- **Replace live delta**: `delta(s) = t_now − ref.times[bin(s)]` (interpolated). Remove the old 1500-point limit when v3 is locked; keep `live_delta.py` as the non-locked fallback.

### 8.2 Braking episodes with position
Extend the braking detection (`live_analysis` for live, `analytics.braking_episodes` for recorded) to store:
```
{s_onset, s_peak, s_release, s_apex(min speed), s_throttle(throttle > 0.2 after apex),
 entry_kmh, min_kmh, exit_kmh(at s_throttle+50), peak_brake, duration_s, lap}
```
- Onset is when brake > 0.10; release is when brake < 0.05 for 0.2 s.
- Discard episodes shorter than 0.25 s, or with entry speed < 50 km/h.

### 8.3 Corner matching
```python
corners = locked_model['corners']  # {id, name, s_start, s_apex, s_end, source}
def corner_for(ep):
    for c in corners:
        if in_range_wrap(ep.s_onset, c.s_start - 200, c.s_apex): return c
    return None                    # unassigned; report as "braking zone at {s:.0f} m"
```
Display name = the surveyed name if present, otherwise `"Turn {n}"`. Never invent names like "hairpin"; the word appears only if the model's name contains it.

### 8.4 Per-corner loss and cause
For each corner c, on lap-end, against the reference:
```python
a, b = c.s_start - 150, c.s_end + 100
loss = (lap.t(b) - lap.t(a)) - (ref.t(b) - ref.t(a))              # seconds, + = slower
if abs(loss) < 0.05: skip
ep, rp = lap episode for c, ref episode for c (both needed for cause)
causes = []
d_onset = ep.s_onset - rp.s_onset                                   # negative = braked earlier
if abs(d_onset) >= 8: causes.append(('onset', d_onset))
d_min = ep.min_kmh - rp.min_kmh
if abs(d_min) >= 3: causes.append(('min_speed', d_min))
d_thr = ep.s_throttle - rp.s_throttle                               # positive = later throttle
if abs(d_thr) >= 10: causes.append(('throttle', d_thr))
# split loss into entry (a..s_apex) and exit (s_apex..b) to pick the dominant cause
entry_loss = seg_loss(a, c.s_apex); exit_loss = seg_loss(c.s_apex, b)
primary = pick: if entry_loss >= exit_loss: prefer onset, then min_speed; else throttle, then min_speed
```
**Evidence item** (feeds the engineer and local AI):
```
{id:f'corner:{c.id}', priority:2, kind:'corner_loss', corner:c.name, lap:n,
 loss_s:round(loss,2), entry_loss_s, exit_loss_s, causes:[...], confidence:'moderate' if both episodes present else 'low',
 text: template(...)}
```
**Templates** (only verified numbers; correlation wording):
- onset: `"{corner}: {abs(loss):.1f} s slower than your reference. You braked {abs(d):.0f} m {'earlier' if d<0 else 'later'}."`
- plus min speed: `" Minimum speed {abs(dm):.0f} km/h {'lower' if dm<0 else 'higher'}."`
- throttle: `"{corner}: {abs(loss):.1f} s lost on exit. Throttle came in {abs(dt):.0f} m later than your reference."`
- gain: `"{corner}: {abs(loss):.1f} s quicker than reference. Keep that."` (priority 3)

### 8.5 Delivery
- **At lap end**, collect the corner items and keep the top 3 by |loss| (loss > 0 first). Put them in:
  - `state['coaching'] = {lap, items[], reference_lap, method:'s-aligned v3'}`;
  - the local AI evidence (replacing the generic "pace" item when present);
  - an **engineer P3 event** in Coaching mode: the top item only, offered when `workload` is low (the next straight: speed > 150 km/h and |steering| small for 3 s), expiring after 25 s.
- **Voice intents**: upgrade `loss` ("where am I losing time") to answer the top item from the last completed lap; if none, give the existing answer. Add intents (also to the Request library, keeping 3 answer forms each):
  - `"how was turn {n}"` / `"how was {corner name}"`: parse a number or fuzzy-match the name among model corners;
  - `"what cost me the most"` (alias of loss);
  - `"compare my braking"`: the top onset differences.
- **Analysis page**: a "Corner report" table (corner, loss, entry/exit split, onset Δ m, min speed Δ, throttle Δ), with a click-through to the map highlighting `s_start..s_end`.

### 8.6 Local AI role (unchanged principle)
- Qwen still only **selects up to 3 evidence IDs**. Evidence text is the template text.
- An optional setting `local_ai_rephrase` (default False) asks for a ≤ 30-word rephrase of the selected items. Accept it only if:
  - every numeric token in the output (regex `-?\d+(\.\d+)?`) appears in the selected items' texts; and
  - no corner name appears that is not in the evidence.

  Otherwise use the template text and log `rephrase_rejected`.

## 9. Feature G: Strategy upgrades

### 9.1 Multi-branch fuel scenarios: `analytics.fuel_scenarios(ctx)`
**Inputs**:
- `fuel_prediction(...)` result (burn, margin, laps_left);
- the lap list with fuel use and lap time;
- settings: reserve, `pit_loss_s`, `refuel_rate_lps`, `max_save_percent` (default 8), `fuel_time_slope_s_per_l` (optional user override);
- group context, optional: interval to the car behind, and that car's net pit state.

**Derived**:
```python
deficit_l = -margin_l                          # > 0 means short
if deficit_l <= 0: return {'short': False, 'branches': [], 'summary': 'Fuel is sufficient under current assumptions.'}
save_pct = 100 * deficit_l / (laps_left * burn)
# time cost per litre saved: learn from own laps if >= 6 comparable laps with fuel spread >= 3%
slope = ols(lap_time_s ~ fuel_used_l) over clean laps -> s per litre (negative expected);  cost_per_l = max(0.5, -slope) if valid
        else settings.fuel_time_slope_s_per_l or DEFAULT 4.0 s/L (labelled 'assumed')
```
**Branches**:
1. **SAVE**: feasible if `save_pct <= max_save_percent`. Cost ≈ `deficit_l × cost_per_l`. Text: `"Save {save_pct:.0f} percent: lift and coast, about {cost:.0f} seconds over the stint."`
2. **SPLASH**: needs `pit_loss_s` (setting, or learned in group). Add = `deficit_l + reserve_margin (0.5 L)`. Cost = `pit_loss + add/rate` (rate unknown means "plus refuel time"). Text: `"Splash for {add:.1f} litres: about {cost:.0f} seconds including the stop."`
3. **GAP CHECK** (group only, when the interval to the car behind is known): after the splash, `gap_after = interval_behind − splash_cost`. Text: `"A splash drops you {'behind' if gap_after<0 else 'ahead of'} #{num} by about {abs(gap_after):.0f} seconds."` Low confidence if either input is an estimate.

Rank feasible branches by cost. The recommendation is the cheapest, **unless** the gap check says the splash loses a position and SAVE is feasible; then prefer SAVE and state why.

**TTS** (max 2 branches, then the recommendation): `"You're {deficit:.1f} litres short. Option one: {b1}. Option two: {b2}. {Recommendation} is quicker."`
- Intents `finish`, `save`, `pit`, plus a new `"what are my fuel options"`, use this.
- A proactive P1 fires when the deficit first becomes confident (`fuel_prediction.confidence == 'moderate'`, ≥ 3 clean laps) and again only if the recommended branch changes. Cooldown 3 laps.

### 9.2 Clean-air pit advice (group mode, driver's app)
**Data path**:
- New group config `share_traffic_with_drivers: bool = False` (host opt-in, shown to members at consent time).
- When enabled, the driver snapshot (`public_state` for `kind=='driver'`, undelayed) includes a `traffic` list for **all** visible entries:
  ```
  {entry_id, number, name, D, median_lap_s (last 3 comparable), in_pit, battle_state}
  ```
  No fuel or telemetry values.
- `client.py.consume` stores the latest traffic in `runtime.group_traffic` with its timeline.

**Algorithm** (runtime, on the `pit` intent or strategy refresh every 10 s):
```python
if not traffic or my D unknown or pit_loss unknown: fall back to fuel-only answer
v_j = L / median_lap_s_j   (m/s);  v_me = L / my_median_lap_s
max_k = floor((fuel_l - reserve) / burn) - 1           # laps I can still stay out
options = []
for k in 0..min(max_k, 5):
    # advance everyone k laps at their pace; then I lose pit_loss while they continue
    t_k = k * my_lap_s
    D_me = my_D + k * L                                 # position at my pit entry
    others = {j: D_j + v_j * (t_k + pit_loss) for j in traffic if not j.in_pit}
    ahead = [j for j in others if 0 < (others[j] - D_me) / v_me < 2.0]      # within 2 s ahead on rejoin
    cost = sum(max(0, lap_s_j - my_lap_s) * min(3, laps_left - k) for j in ahead)   # time stuck behind slower cars, capped 3 laps
    if any(j.battle_state in ('hot','critical') for j in ahead): cost += 0.8
    options.append((k, cost, ahead))
best = min(options, key=cost); now = options[0]
recommend k=best.k if now.cost - best.cost >= 1.0 else 0
```
**Answer templates**:
- Stay out: `"Boxing now rejoins behind #{a} and #{b}, about {pace:.1f} s a lap slower{', and they're battling' if battling}. Staying out {k} lap{s} should give clean air."`
- Clear: `"Box when ready: you rejoin in clear air."`
- If `max_k == 0`: `"Box this lap: no fuel margin to wait."`

All of it is labelled an estimate in the Strategy page, which shows the option table (k, rejoin cars, estimated cost).

## 10. Settings and schema additions
**`config.Settings`** (local):
- `battles_desk_chime: bool=False`
- `local_ai_rephrase: bool=False`
- `max_save_percent: float=8 (1–20)`
- `fuel_time_slope_s_per_l: float|None=None (0.5–20)`
- `pit_loss_s: float|None=None (5–120)` and `refuel_rate_lps: float|None=None (0.5–20)` (solo strategy)
- `tyre_heat_rate_c_s: float=0.15 (0.05–1)`, `tyre_heat_anomaly_c: float=4 (1–20)`
- `coaching_min_loss_s: float=0.05`

**`GroupConfig`**:
- `pit_loss_s`, `refuel_rate_lps` (optional)
- `share_traffic_with_drivers: bool=False`
- `battles_include_lapping: bool=False`
- `battle_weights` (optional dict, validated keys gap/close/pos/dur)
- `steward_popup_kinds: list[Literal[...]]` (default above)
- `steward_popup_s: int=10 (3–60)`
- `auto_steward_paused: bool=False`

**`WorkspaceConfig`**:
- `auto_steward: bool=True`, `steward_popup_graphic_id: str=''`, `battle_auto_take: bool=False`

**Group state** (persisted via `commit_group`):
- `pit_stops`, `steward_cues`, `cued`, `desk_alerts` (desk alerts are in memory only; not persisted)

**Graphics**: add `net_order` (and optionally `battle_tag`) to `GRAPHICS`, the `Graphic.template` Literal, the renderer, `docs/BROADCAST_GRAPHICS.md` and `test_graphics_registry.py`.

## 11. API additions (all go through the existing auth, rate limits and permission checks)
**Local admin (`/api/group`)**:

| Method | Path | Purpose |
|---|---|---|
| GET | `/battles` | raw battles plus desk alerts |
| POST | `/battles/{id}/focus` | focus a battle into a workspace |
| POST | `/battles/{id}/dismiss` | suppress a battle's alerts |
| GET | `/projection` | net order, pit windows, learned pit loss/refuel |
| GET | `/steward-cues` | cue queue |
| DELETE | `/steward-cues/{id}` | cancel a cue |
| PUT | `/steward-cues/paused` | pause/resume auto cues |

**Public (`/group-api`)**:
- `POST /workspaces/{id}/focus-battle` (spectator; filtered battles only).
- Battles, projection (if published), `steward_cue_active` and `traffic` (drivers, if opted in) arrive through the existing snapshots.

**Local runtime state additions**: `track`, `coaching`, `fuel_scenarios`, `tyre_heat`, `pit_advice`.

## 12. Build phases and acceptance (do them in order; each must leave the app working)

| Phase | Scope | Done when |
|---|---|---|
| 0 | §2.6 v3 wiring (`TrackService`, runtime `s`, group adapter) | Tests green; replayed lap locks; `s` monotonic; projection p95 ≤ 0.2 ms/sample |
| 1 | §2.1–2.5 `D`, timeline, `DistanceHistory`, intervals, pit detection | Unit tests: interval within 0.05 s on synthetic constant-speed cars; lapped cars flagged; pit stop learned from demo |
| 2 | Feature A Battle Index + desk panel | 8-driver demo with 2 scripted battles: both reach `hot`; the scripted close pass reaches `critical` < 5 s after gap < 0.5 s; overtake keeps the id; no alerts for stale/pit cars; worker ≤ 2 ms/tick at 16 entries |
| 3 | Feature B focus + `battle_tag` (optional) | Focus→Draft sets slots a/b/primary and adds missing graphics; Take publishes atomically; spectator can't focus another's workspace (403) |
| 4 | Feature D steward cues | Public decision gives the cue on overlay within 1 s (+delay); private gives none; status change gives a new cue; dedupe; queue priority; cancel works |
| 5 | Feature C projector + `net_order` | Synthetic: 4 cars, 2 need a stop, pit loss 25 s, so the projected order matches a hand calculation; hidden when fuel/strategy unpublished; "≈" when within uncertainty |
| 6 | Feature E tyre heating-rate | The 5 test classes in §7.2 pass; no alert on 10 synthetic normal laps |
| 7 | Feature F spatial coaching | Synthetic lap braking 15 m earlier at corner T3 gives item "T3 … braked 15 m earlier" with loss sign correct; gain case; unassigned braking zone; rephrase rejection test |
| 8 | Feature G fuel branches + clean-air | Branch ranking tests incl. gap-check override; traffic example (2 slow battling cars ahead on rejoin) recommends k ≥ 1; opt-out means no traffic data in the driver snapshot |

## 13. Test inventory (new files)
- `tests/test_group_history.py`: DistanceHistory, interval, lapping, uncertainty, pit detection.
- `tests/test_battles.py`: heat formula values, the state machine and hysteresis, overtake swap, cooldown, filter/permissions, delay applied.
- `tests/test_battle_focus.py`: draft mutation, locked-graphic warning, take, spectator permissions.
- `tests/test_steward_cues.py`: public/private, kinds, dedupe, queue priority, cancel, delay.
- `tests/test_projection.py`: stops_needed, stop_cost with unknown rate, net order, "≈", timed-race band, publication gating.
- `tests/test_tyre_heat.py`, `tests/test_spatial_coaching.py`, `tests/test_fuel_scenarios.py`, `tests/test_clean_air.py`, `tests/test_track_service.py`.
- **Playwright** `tests/e2e/action-director.spec.ts`:
  - demo league → a battle appears in the desk;
  - Focus & Take → the overlay comparison shows both cars;
  - a public decision → a penalty popup shows for ~10 s;
  - the `net_order` graphic renders.
- **Extend the demo** (`group/demo.py`): scripted battles (two pairs converging), one scripted pit stop per car mid-race with a fuel increase, and fuel/strategy sharing enabled in the demo config. This drives the Phase 2–5 acceptance without a PS5.

## 14. Performance budgets
- Battle worker: ≤ 2 ms per tick at 16 entries (2 Hz). Projector: ≤ 2 ms per tick (0.5 Hz). Both run outside the lock except for the final swap-in of results.
- Runtime additions per UDP sample: ≤ 0.3 ms total (projection + bin updates). Tyre and coaching maths run at 5 Hz or at lap end, never per packet.
- Memory:
  - `DistanceHistory` 16 × 900 × 2 floats;
  - pair buffers 48 × 60;
  - `SpatialLap` about 5 KB per lap (keep the last 30 laps plus the reference);
  - tyre baselines 4 × (L/100) floats.
- No new runtime dependencies.

## 15. Docs to update
- `docs/RACE_CONTROL.md` (battles, focus, projector, steward cues)
- `docs/BROADCAST_GRAPHICS.md` (new graphics, cue behaviour)
- `ALERT_RULES.md` (`tyre_heat_rate`)
- `VOICE_COMMANDS.md` (new intents)
- `docs/AI_CONTEXT.md`
- A README features row

Every document states the limits:
- battle heat and net order are estimates from connected-group data;
- pit loss is host-entered or learned;
- coaching is correlation with the reference lap, not proof of cause.
