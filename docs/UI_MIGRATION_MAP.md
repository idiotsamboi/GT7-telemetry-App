# UI redesign migration map (Phase 0)

Every control in the current app (`frontend/src/main.tsx` plus `GroupControl.tsx`, `RaceDesk.tsx`, `GroupStudio.tsx`,
`LeagueBranding.tsx`, `WheelDash.tsx`, `Training.tsx`) and where it lands in the new Broadcast/Driver workspace
structure. Nothing here is deleted without a listed new home. Old `page` names are string state in `App`; new
locations are hash routes under the redesign.

Baseline measurements (before any redesign code), taken from the current production build:

- `dist/assets/index-*.js`: **428 KB** (uncompressed) — the single `App` bundle; everything (Pit Wall, Settings,
  Race Control, Studio, Training) ships in one chunk except the lazy `Chart` chunk.
- `dist/assets/Chart-*.js`: 56 KB (lazy, uPlot + wrapper).
- `dist/assets/index-*.css`: 72 KB (from a 136-line, single-statement-per-line `style.css`).
- `dist/assets/Chart-*.css`: 4 KB.
- Re-render behaviour: `App` holds one `useState<any>(null)` for the *entire* `/ws` payload
  (`main.tsx:24,30`) and re-renders on every message — at the default `ui_hz=12`, that's up to **12 full-tree
  commits/second** even when the visible page (e.g. Sessions, Settings) never reads telemetry. This is the
  concrete problem Phase 1's `liveStore` slices fix.

## Global chrome

| Old | Where (file:approx line) | New home |
|---|---|---|
| Pairing gate (`!paired`) | `main.tsx:43` | Kept as its own unauthenticated route, `#/pair`, same behaviour |
| Sidebar mode nav (Pit Wall/Race Control/Studio/Wheel/Training + Settings) | `main.tsx:46` | `TopBar` → `WorkspaceMenu` (BROADCAST ▾ / DRIVER ▾) + `#/settings` |
| Breadcrumb + Hz + connection dot | `main.tsx:47` | `StatusCluster` in shell `TopBar` |
| Recovery link (header) | `main.tsx:47`, also `:50,52,79` | `StatusCluster` → Recovery icon; standalone `/recovery` untouched |
| Fullscreen toggle | `main.tsx:47` | `StatusCluster`; Wheel page gets its own `F` shortcut per §8.4 |
| Pit Wall sub-tabs | `main.tsx:48` | `IdentityBar` section tabs under `#/driver/pit-wall/*` |
| Page heading (eyebrow/title/description) | `main.tsx:49` | `IdentityBar` region, workspace-styled |
| Try demo / Use PS5 badge+button | `main.tsx:49` | Status ribbon tile / command palette command, Live page |
| Disconnected/reconnecting notice | `main.tsx:50` | Global `Notifications` + connection-state banner (`status.ts` OFFLINE/RECONNECTING) |
| Recovery notice / host-only banner | `main.tsx:51-52` | Same, surfaced via `Notifications`; host-only lamp also shown in Race Control session strip (§8.6) |
| Error banner | `main.tsx:53` | `Notifications` (dismissible entries), not a full-width page banner |
| Socket error notice | `main.tsx:54` | Folded into unified `status.ts` ERROR state |
| Telemetry connection troubleshooting panel (phase/heartbeats/datagrams/valid packets/last error, Reconnect button) | `main.tsx:55` | Live page empty/error state (`WAITING FOR GT7 · …`) per §6.3, plus a persistent diagnostics entry in Settings → Advanced |
| Performance-degraded notice | `main.tsx:56` | `Notifications` |
| Replay transport bar (pause/resume, speed, restart) | `main.tsx:74` | Broadcast `Timeline` component (§6.1) reused on Driver pages when `source==='replay'`; Studio/Race Control get the full orange-playhead Timeline |
| Footer tag | `main.tsx:75` | Kept, shell-level, neutral tokens |

## Pit Wall → Driver workspace (`#/driver/pit-wall/*`)

| Old control | File:line | New home |
|---|---|---|
| Broadcast strip + `FlagIndicator` | `main.tsx:57` | Live status ribbon "PLAYER STATUS" tile (§8.1) — relabelled, not "flags" |
| Session strip (track/car, REC indicator, status) | `main.tsx:57` | Status ribbon tiles: lap/session/recording |
| `RaceVisuals` circuit+car panel (map, track/layout select, import/export, layout confirmation) | `main.tsx:58`, `RaceVisuals.tsx` | Track map panel (§8.1) keeps `CircuitMap` (never re-implemented); track/layout select + import/export/confirm move into the map panel's menu |
| Vehicle telemetry card (RPM bar, speed, gear, pedals) | `main.tsx:59` | Car State panel |
| Lap timing card (current/last/best/delta/sector placeholders/fastest placeholder/legend) | `main.tsx:60` | Lap Timing panel; sector/fastest N/A slots per data-truthfulness rule |
| Fuel & range card | `main.tsx:61` | Fuel & Range panel |
| Tyre temperatures card | `main.tsx:62` | Tyres panel (2×2, "surface temperature, not wear") |
| Recent-pace mini chart (`Chart.tsx`) | `main.tsx:62` | Pace panel (bars, not just a line chart, per §8.1) |
| Radio bar (status + subtitle + "Open radio") | `main.tsx:63` | Alerts/Radio panel header |
| Mute/Unmute, Hold-to-talk (PTT), hands-free toggle, mic status | `main.tsx:64` | Alerts/Radio panel controls; PTT pointer-capture logic reused verbatim (do not rewrite the pointer-capture handlers — they're a correctness-sensitive pattern) |
| Mark incident | `main.tsx:64` | Bottom action bar, Live page |
| Start/End session | `main.tsx:64` | Bottom action bar (End requires confirm when laps > 0, per §8.10) |
| `MapCard` (Telemetry tab) | `main.tsx:65` | Superseded by the Telemetry page's linked map (§8.3); `MapCard`/`CircuitMap` component itself is reused, not replaced |
| Real-time analysis card (G/coast/overlap/tyre-spread, braking-episode JSON) | `main.tsx:65` | Telemetry page stat strip; braking-episode detail becomes a `DenseTable`/annotation instead of raw `<pre>` JSON |
| Channel chips + uPlot explorer | `main.tsx:65` | Telemetry page's channel tree + lanes (§8.3) — the biggest single rebuild |
| Analysis empty state / stat row / toolbar / lap table / comparison / coaching grid / quality notes | `main.tsx:66` | Analysis page (§8.2), same data, `DenseTable` + `AlertLane`-style insight feed |
| Strategy fuel-estimate card + assumptions form | `main.tsx:70` | Strategy page (§8.2); adds Scenario A/B and `fuel_scenarios` branches if present |
| `LocalBrief` | `main.tsx:71`, `LocalBrief.tsx` | Engineer page header |
| Radio desk card (status, speaker test, stop-talking, hard mute, command form, quick chips) | `main.tsx:71` | Engineer page |
| Microphone & delivery card | `main.tsx:71` | Engineer page |
| `RequestLibrary` | `main.tsx:71`, `RequestLibrary.tsx` | Engineer page; **also indexed into the global Command Palette** (§6.3) |
| Speech decisions & evidence event list | `main.tsx:71` | Engineer page `AlertLane` |
| Sessions search/import toolbar, session card list, empty state | `main.tsx:72` | Sessions page master list → `DenseTable` (§8.2) |
| Replay button (per session) | `main.tsx:72` | Sessions page row action; opens Live/Wheel with replay transport |
| Protect (★) toggle | `main.tsx:72` | Sessions page row action |

## Settings (`#/settings/*`, neutral)

| Old control | File:line | New home |
|---|---|---|
| Save settings button + restart note | `main.tsx:73` | Global save bar, same behaviour |
| Console & connection card | `main.tsx:73` | Settings → Connections |
| Local AI card | `main.tsx:73` | Settings → Advanced → Local AI |
| Audio & recognition card (devices, Vosk, eSpeak/Piper, speaker/noise/record tests, device JSON) | `main.tsx:73` | Settings → Audio |
| Display & engineer card (theme, verbosity, UI Hz, thresholds, minimal toggle) | `main.tsx:73` | Settings → Appearance (theme/motion/density/scale) + Settings → Driver (verbosity/thresholds) — split, since these are two different concerns in the new hierarchy |
| Track & setup profile card (track/layout/direction, pit limit, notes, save/load profile) | `main.tsx:73` | Settings → Connections (track fields) + a "Setup profile" sub-section |
| Test live telemetry card | `main.tsx:73` | Settings → Advanced (reception test) |
| Live diagnostics card (raw health JSON) | `main.tsx:73` | Settings → Advanced |
| Protocol capability registry card | `main.tsx:73` | Settings → Advanced |

Note: "Pair browser" (docs/AI_CONTEXT.md §10) is the same pairing-token gate already listed under Global chrome
(`main.tsx:43`), not a separate Settings feature — there is no second pairing surface in the current code.

## Wheel (`#/driver/wheel`)

`WheelDash.tsx` is preserved wholesale (pages RACE/TIMING/FUEL/TYRES/STRATEGY/MAP, page-visibility settings,
←/→ paging, shift lights, lamps, mini-map). Only change: it now mounts inside the Driver shell with a framed
view + `F`/Fullscreen-API toggle instead of `main.tsx:44`'s full replacement of the whole app tree; `Esc` from
fullscreen returns to the framed view rather than exiting to Live Race.

## Training (`#/driver/training`)

`Training.tsx`, `TrackVisualizer.tsx`, `RouletteWheel.tsx` preserved wholesale: recording-active stats/progress
card, point-cloud visualizer, untrained-layouts picker + roulette, training-goals list (resume/restart). New:
a Progression tab (Dashboard/Track Coverage/Challenges/Progress/Achievements) computed server-side from real
training/session records (§8.5) — additive, does not change existing Training behaviour.

## Race Control (`#/broadcast/race-control`) — `GroupControl.tsx` (mode="control") + `RaceDesk.tsx`

| Old control | New home |
|---|---|
| Alarm strip (active flag banner) | Session strip, same data |
| Session setup panel (league/event create, demo start) | Session strip / setup flow, same data |
| Session bar (lock/pause/start/end/confirm/close) | Session strip controls, ARM→EXECUTE added to finalize/close |
| Source-select ATEM button bank | Command bank / entrant selection |
| Battles panel (heat, state, Focus/Focus&Take/Dismiss) | Track+incidents area or a dedicated Entrants sub-panel |
| Standings table, admission list, driver inspector | Entrants panel |
| Steward decision form + cue queue | Command bank / Stewarding section |
| Shared map + driver markers | Track+zones+incidents panel (`CircuitMap`, reused) |
| Fuel & pit strategy panel | Command bank or a collapsible strategy drawer |
| Marshal zones editor | Track+zones panel |
| Instructions section (scope bus, flag grid, active list) | Command bank (flag keys, scope BusRow) |
| Driver messages (scope, chips, send, ack log) | Messaging panel |
| Steward decision history | Event log / Steward log tab |
| Rehearsal demo controls (grid size, pause/resume, speed, simulate disconnect/ack) | Session strip / demo controls, unchanged behaviour |
| Host-only mode | Session strip lamp |
| Replay (recorded group sessions) | `Timeline` with orange playhead, play/pause/speed/seek, EXIT REPLAY |

## Studio (`#/broadcast/studio`) — `GroupControl.tsx` (mode="studio") + `GroupStudio.tsx` + `LeagueBranding.tsx`

| Old control | New home |
|---|---|
| Draft preview / Program monitor | Monitor wall (preview green tally / program red tally) |
| Take to program / Save draft / Discard / Clear draft / Clear program now | Transition bank (CUT/AUTO/T-BAR + SAVE/DISCARD/CLEAR, ARM→EXECUTE on Clear program) |
| Scene layers list + Add-a-graphic library | Scene layers + Graphics library (categorized) |
| Graphic settings panel (x/y/w/h, slot, title, duration) | Inspector |
| Workspace/shared-selection config (name, style, delay, driver slots) | PRIMARY/A/B buses + workspace settings |
| Style gallery (10 presets, live swatches) | Kept as-is, unchanged rendering |
| Share-workspace checkboxes | Output/Deliver sharing section |
| Overlay URL issuing (per-graphic + composite) | Output/Deliver sub-tab |
| LAN hosting card (origins, host-only, invitations) | Output/Deliver |
| Replay card | Output/Deliver → Timeline |
| Remote group-connection card (join as driver) | Output/Deliver (kept, since it's how *this* app joins someone else's group as a driver) |
| League branding (name/tagline/fonts/colors/logos/sponsors/teams) | Studio → Color (branding editor), unchanged data model |

**Explicitly not touched**: `GroupGraphics.tsx`'s `GraphicView`/`Composition` renderers, all 28 graphic templates,
all 10 style presets, `/group` (`GroupPublic`), `/overlay/{id}`, `/recovery` and `/recovery.js`. These are
broadcast *output*, not operator UI — screenshot-diffed before/after in Phase 6, never restyled.

## Explicitly deferred (not in this migration; flagged, not silently dropped)

- Popouts / multi-monitor (`#/popout/{panelId}`, `BroadcastChannel` sync) — Phase 7, optional.
- New `GET /api/sessions/{sid}/laps/{lap_id}/samples` multi-channel endpoint — Phase 5, needed before Telemetry
  lanes can share one endpoint call across channels; current `sessions/{id}/samples?channel=X` stays live until
  it's replaced.
- Training progression's `GET/PUT /api/training/progress-profile` — Phase 7.
