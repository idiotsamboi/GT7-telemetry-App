# CLAUDE CODE MASTER PROMPT: GT7 Race Engineer UI/UX redesign (tailored to this repository)

You are working in the **GT7 Race Engineer** repository. Redesign and implement the whole operator UI as **one application with two explicitly separated workspaces: BROADCAST and DRIVER**. This is real implementation in the real app, not mockups, static HTML or a style guide. Preserve every working feature.

Read first: `docs/AI_CONTEXT.md` (feature and architecture map), then `frontend/src/main.tsx`, `style.css`, `RaceVisuals.tsx`, `WheelDash.tsx`, `Training.tsx`, `GroupControl.tsx`, `RaceDesk.tsx`, `GroupStudio.tsx`, `LeagueBranding.tsx`, `GroupGraphics.tsx`, `Chart.tsx`, `colors.ts`, `motion.ts`, and `tests/e2e/*.spec.ts`.

---

## 0. Facts about this codebase (verified; design around them)

| Area | Current reality | Consequence for the redesign |
|---|---|---|
| Stack | React 19 + TypeScript + Vite 6; deps are only `react`, `react-dom`, `uplot`, `lucide-react`, `gsap` | No router, no state library, no CSS framework. **Don't add Tailwind, MUI, Radix, Redux or react-router.** Build small primitives in-house. A tiny dependency is acceptable only if justified in the final report and under 15 kB gzipped |
| Navigation | `main.tsx` holds `page` state. `MODES` = Pit Wall, Race Control, Studio, Wheel, Training; `PITWALL_TABS` = Live Race, Telemetry, Analysis, Strategy, Engineer, Sessions. Race Control and Studio both render `GroupControl` (different props). Wheel returns `WheelDash` *instead of* the shell | Replace with a hash router and workspace shell (§3). Keep the Race Control/Studio split, but give each its own view |
| Routing constraint | The FastAPI backend serves the SPA only at `/`. `/group` and `/overlay/{id}` are separate public pages (`GroupPublic`). `/recovery` is standalone HTML | Use **hash routes** (`#/driver/pit-wall/telemetry`) so refresh works in the browser and pywebview without backend changes. **Never touch `/group`, `/overlay/*`, `/recovery`** |
| Live data | One WebSocket `/ws` (latest-state-wins, `ui_hz` default 12). The whole `state` object lives in `App` `useState`, so the full tree re-renders every frame | Build a telemetry store with selector subscriptions (§11). This is the biggest performance fix |
| Styling | `style.css` (~37 kB) is hand-written with almost no CSS variables. `Inter` is named but not bundled. `GroupGraphics.css` holds OBS overlay styles | Create a token system (§5). **The OBS overlay renderers and their 10 style presets are broadcast output, not operator UI; don't restyle them.** Studio previews must keep rendering them exactly as OBS shows them |
| Charts | uPlot in `Chart.tsx` | Keep uPlot. Extend it into synchronized lanes (§8.3) |
| Map | `RaceVisuals.CircuitMap` is the only map renderer; also used by `RaceDesk`, `WheelDash` and the overlay map graphic | Reuse and extend it (heat overlays, cursor linking). **Never create a second map renderer** |
| Persistence | Only `localStorage 'wheelPages'` exists. Backend `Settings` holds theme, minimal, reduced_motion, ui_hz | Add a view-state store (localStorage, versioned keys). Keep backend settings as the source for server-affecting options |
| Existing UX | Dark F1-broadcast style. Semantic colours are in `colors.ts`. The layout is currently responsive down to 360 px | Keep semantic meanings (§5.3). Desktop-first now, with a usable compact fallback (§10) |

**Data truthfulness (project rule, overrides the generic design brief).** GT7 doesn't send, and the UI must never show as live values: race position, gaps to other cars (except Race Control connected-group estimates), official sectors, race flags (the app has player status only), tyre wear, tyre pressure, tyre compound, weather, damage, brake bias, TC/ABS levels, lateral G (unvalidated), official lap validity.
- Where the brief asks for these (status ribbon position/gap/compound, tyre wear/pressure, sector colours, weather), render a **designed "N/A · not transmitted by GT7" slot** or omit it. Use the existing wording from `telemetry.UNSUPPORTED`.
- **Custom sectors** may appear only when a track model supplies them, labelled "custom".
- Never add demo numbers to real screens; the synthetic demo source is already labelled.

---

## 1. Primary concept

**One program, three design layers:**
1. **Shared shell**: neutral, the same in both workspaces.
2. **BROADCAST workspace**: Race Control and Studio. Modelled on Blackmagic ATEM Software Control, DaVinci Resolve and physical production consoles: tactile keycaps, bevelled chassis, illuminated states, silkscreen labels.
3. **DRIVER workspace**: Pit Wall (Live, Telemetry, Analysis, Strategy, Engineer, Sessions), Wheel and Training. Modelled on F1/WEC engineering terminals and Grafana-style monitoring: flat, dense, gridded, computational.

The two workspaces must be distinguishable **in grayscale**. Broadcast = depth, keycaps, bevels, mechanical motion. Driver = flat panels, hairlines, corner ticks, charts, data motion.

## 2. Mapping every existing feature into the new hierarchy

```
APP (#/…)
├─ Shell (always visible)
│  ├─ Identity (red logo mark, "GT7 ENGINEER")
│  ├─ BROADCAST ▾  │  DRIVER ▾
│  ├─ Status cluster: CONNECTION · RECORDING · SESSION · SOURCE(LIVE/DEMO/REPLAY) · GROUP (hosting/member)
│  ├─ Notifications   ├─ Recovery   └─ Settings (global)
├─ BROADCAST
│  ├─ #/broadcast/race-control   ← GroupControl(race control parts) + RaceDesk
│  └─ #/broadcast/studio         ← GroupStudio + LeagueBranding + GroupControl 'Deliver' (hosting/OBS URLs)
└─ DRIVER
   ├─ #/driver/pit-wall/{live|telemetry|analysis|strategy|engineer|sessions}
   ├─ #/driver/wheel             ← WheelDash (framed; fullscreen toggle)
   └─ #/driver/training          ← Training (+ progression layer, §8.9)
#/settings[/section]             ← global settings (neutral)
#/popout/{panelId}               ← optional detached panel (§12)
```
- Legacy `page` names map to routes; migrate old saved state.
- Default route: the last route used, else `#/driver/pit-wall/live`.
- **Every existing control must have a home.** Before deleting any JSX, list what it did in `docs/UI_MIGRATION_MAP.md` (old location → new location). That covers:
  - recovery actions
  - hosting and host-only mode
  - invitations
  - replay controls
  - map import/export and restore
  - Pair browser
  - speaker/mic/noise tests
  - the AI briefing
  - the request library
  - session export/import, retention and protect
  - demo/Use PS5
  - start/end session
  - mark incident
  - hands-free and PTT
  - the reception test

## 3. Shell, navigation and routing

- **Top bar**: 44 px, neutral tokens (§5.1). Layout: `[logo] [BROADCAST ▾] │ [DRIVER ▾] [context] … [conn] [rec] [session] [source] [group] [bell] [recovery] [⚙]`.
  - The divider between the two menus is a visible 1 px rule with a gap. Both menus are always visible.
  - The active workspace gets a restrained filled treatment (Broadcast: a small red tally LED plus a lit label; Driver: a blue underline plus a lit label).
  - **Opening a dropdown doesn't switch workspace; selecting an item does.**
  - Dropdowns list the workspace's sections with icons and shortcut hints.
- **Identity bar** (28 px) directly under the shell: `DRIVER / PIT WALL / TELEMETRY` or `BROADCAST / STUDIO`, in the workspace's typeface and colour. The section tabs sit on the same row or the next.
- **Router**: `src/app/router.ts` (~80 lines). It parses `location.hash`, exposes `useRoute()` via `useSyncExternalStore`, and provides `navigate(path, {replace})`. It supports back/forward. Unknown routes redirect to the default.
- **Shortcuts** (registry, §9.4): `Ctrl+1` Driver/Live, `Ctrl+2` Telemetry, `Ctrl+Shift+B` Broadcast/Race Control, `Ctrl+Shift+S` Studio, `Ctrl+K` command palette, `Ctrl+,` settings.

### 3.1 State preservation (hard requirement)
Switching route **must never** stop or restart: the GT7 receiver, recording, `/ws`, group hosting/member publishing, OBS overlays, voice/mic, local AI, training capture, replay. These are backend-owned already; the frontend must not send any control request on navigation. Audit every `useEffect` cleanup in the pages for calls like `control('stop')`, mic disable or WS close, and remove any that fire on unmount.

- **View state** lives in `viewStore` (§11) keyed per route and panel, so pages can unmount and restore exactly. It covers:
  - sub-tab, selected laps, reference/compare, axis mode, zoom range, channel lanes;
  - table sort/filter/column widths, selected session, selected entrant;
  - inspector open state, scroll positions (restored after data loads), panel layout.
- **Unsaved Studio draft edits** are kept in `viewStore` (sessionStorage) so switching to Driver and back never loses them. (Today they're lost when leaving Studio.) Show an "UNSAVED DRAFT" amber lamp in the Studio identity bar while dirty.
- **Hidden pages must not render charts or subscribe to high-rate data.** Unmount heavy pages; restore from `viewStore`. Keep-alive (`display:none` + `inert`) only for pages with expensive, non-restorable local state; document which.

## 4. Typography (bundled locally; the app runs offline)

- **Interface**: **Inter** (OFL). **Technical monospace**: **JetBrains Mono** (OFL). **Condensed display**: **Barlow Condensed** (OFL).
- Put woff2 files (Latin subset, weights 400/500/600/700) in `frontend/public/fonts/` with `@font-face` and `font-display: swap`. Add the OFL texts to `docs/licenses/` and entries to `THIRD_PARTY_NOTICES.md`. **No Google Fonts or CDN.**
- Use `font-variant-numeric: tabular-nums` on every changing number. Monospace for telemetry, timing, IPs, packet counts, coordinates, timecodes. Condensed for the big gear, panel headings and workspace identity only.
- Scale (px): 10 / 11 / 12 / 13 / 15 / 18 / 24 / 32 / 48 / 96 (gear).

## 5. Design tokens (`src/ui/tokens.css` + `src/ui/tokens.ts`)
Use CSS custom properties. The layers are `:root` (shared), `[data-workspace="broadcast"]` and `[data-workspace="driver"]` on the workspace root, plus `[data-motion="full|data|off"]` and `[data-contrast="high"]` on `<html>`. Migrate `colors.ts` to read the same values; channel colours stay semantic.

### 5.1 Shared
- Spacing: 2, 4, 6, 8, 12, 16, 24, 32.
- Radii: sm 2, md 4, lg 6 (max 6 anywhere in operator UI).
- Durations: instant 60, fast 100, base 140, slow 180, fade 1200.
- Easing: `cubic-bezier(.2,.8,.2,1)`; press `cubic-bezier(.3,0,.5,1)`.
- Shell colours: bg `#121417`, surface `#1A1D22`, border `#2A2F37`, text `#DDE3EA`, muted `#8B95A3`.
- Focus ring: 2 px `#3D8BFD`, offset 1.

### 5.2 Broadcast
| Token | Value | | Token | Value |
|---|---|---|---|---|
| window | `#161616` | | text | `#D9D9D9` |
| chassis | `#262626` | | text-2 | `#8C8C8C` |
| chassis-raised | `#2E2E2E` | | program (live/danger) | `#E5322D` |
| recessed | `#121212` | | preview (ready/safe) | `#2FBF4F` |
| edge-highlight | `#3C3C3C` | | selection | `#3D8BFD` |
| shadow-deep | `#0A0A0A` | | tool/playhead orange | `#F28C28` |
| editor-bg (Studio) | `#1E1E1E` | | warning/armed | `#F2B600` |

Keycap physics tokens: press 60 ms, release 140 ms, travel 2 px, overshoot 1 px, glow-on 90 ms, glow-off 120 ms.

### 5.3 Driver
| Token | Value | Meaning (binding) |
|---|---|---|
| bg | `#0A0D12` | |
| panel | `#10151C` | |
| panel-raised | `#161D27` | |
| border | `#232C39` | |
| text / text-2 | `#E6EDF5` / `#8A97A8` | |
| accent | `#4D9BFF` (glow `rgba(77,155,255,.35)`) | selection, focus, primary action |
| throttle / PB / gaining | `#2FD26B` | green = throttle, personal best, gaining delta |
| brake / losing / critical | `#FF4D5E` | red = brake, losing delta, critical |
| clutch | `#9EDBFF` | keep the existing clutch light blue |
| fastest | `#B36BFF` | purple = fastest |
| other laps | `#F4D34E` | yellow = other laps (user rule) |
| warning | `#FFB020` | |
| reference lap | `#35D0E6` | |
| comparison lap | `#F2F5F8` | |
| stale/unavailable | `#5B6675` | grey + "N/A"/"STALE" label |

These keep the user's earlier colour rules: throttle green, brake red, clutch baby blue, fastest purple, PB green, other laps yellow, red logo, delta line green when gaining and red when losing. Never use a semantic colour decoratively. Always pair colour with a glyph or label (▲▼ ● ◆ "PB" "FL" "REF").

## 6. Component library (`src/ui/`)
Build the primitives first, then migrate pages. Each primitive: keyboard accessible, token-driven, supports `data-motion`, has a Playwright or unit test for its critical behaviour.

```
src/ui/shared/   AppShell, TopBar, WorkspaceMenu, IdentityBar, StatusCluster, ConnectionStatus, Notifications,
                 Modal, ConfirmDialog, Tooltip, ContextMenu, CommandPalette, ShortcutRegistry, EmptyState,
                 LoadingState, ErrorState, VirtualList, Icon (lucide only)
src/ui/broadcast/ ChassisPanel, Keycap, KeyGroup, BusRow, TakeControls(Cut/Auto/TBar), Fader, Knob, Led, LedLadder,
                 LcdSelect, RecessedInput, LampToggle, SelectorTabs, EquipTooltip, EquipDialog, Timeline(orange playhead)
src/ui/driver/   Panel, PanelGrid, Button(primary/ghost/danger/icon), Chip, LapChip, SegmentedControl, DenseTable,
                 Stat, Sparkline, StatusLed, TelemetryLanes, ChannelTree, CursorReadout, AlertLane, CornerTable
```
- **Don't build**: PTZ joystick, zoom/focus rockers, audio mixer faders, audio meters for programme audio. The app has no camera or programme-audio control, and fake controls are forbidden. If you want, leave a documented `extension-points.md` entry.

### 6.1 Broadcast primitives (behaviour spec)
- **ChassisPanel**:
  - chassis gradient (raised → chassis), 1 px top highlight, darker bottom edge, radius 4;
  - silkscreen header: 10 px condensed uppercase, letter-spacing .12em, text-2;
  - optional tiny corner screws, used **only** on the four main equipment groups per page.
- **Keycap**:
  - Variants: standard 44×36, wide 88×36, small 28×24.
  - Kinds: normal, program (red), preview (green), destructive, illuminated, momentary, toggle; optional shortcut badge.
  - Layers: face, skirt, bevel, internal light, glow.
  - Hover: +6% face brightness.
  - Press: `translateY(2px)`, skirt compress, shadow compress, face −4%, 60 ms; release 140 ms with 1 px overshoot (motion full only).
  - Active: inner backlight plus edge leakage (box-shadow ≤ 2 layers).
  - Armed: amber pulse 1.6 s. Disabled: flat, 45% opacity, no press.
  - Keyboard activation plays the identical animation (via `data-pressed` set by the shortcut registry).
  - Optional click sound (Settings → Broadcast → key sounds, default off; WebAudio 8 ms tick, no files).
- **BusRow**: mutually exclusive keycaps. The program row lights red, the preview row green. Transitions cross-fade the old light out and the new one in (120 ms).
- **TakeControls**:
  - **CUT**: wide key, immediate, red flash 150 ms.
  - **AUTO**: amber while running, with a bottom progress bar.
  - **T-BAR**: recessed vertical channel with a ridged handle; drag tracks the pointer, snaps at the limits, settles 120 ms on release; a progress fill behind it. Keyboard: arrows move it, Enter completes.
  - **Important**: the backend `take` is atomic (overlays switch instantly). CUT, AUTO and completing the T-bar all call `POST …/workspaces/{id}/take`. AUTO and the T-bar are *gestures*; never imply a video crossfade. Releasing the T-bar before 100% returns it to 0 with no take.
- **Fader** and **Knob**:
  - Fader: drag; wheel = coarse, Shift+wheel = fine, double-click = reset; the value is always shown in mono with units.
  - Knob: vertical drag or wheel; a plain click never changes the value.
  - Use them only for real parameters: broadcast delay 0–120 s, graphic opacity 0–1, popup duration 0–3600 s, rows 1–32, speech volume (Broadcast audio settings if any).
- **Led** (6 px) and **LedLadder** (segmented green→amber→red with peak hold). Real uses: hosting listener, overlay subscribers, member freshness per entrant, program live, delay buffering, recording, connection.
- **LcdSelect**: recessed readout `[value ▼]`; menu opens in 100 ms with 28 px rows and a blue left strip on the selected row. Arrows, Enter, Esc, type-ahead.
- **RecessedInput**: mono for numbers, blue edge on focus, arrow stepping, units suffix, drag-to-scrub.
- **LampToggle**: a lit key or a lamp plus label. Never a pill switch. Checkbox = a small recessed square with a lit centre.
- **SelectorTabs**: flush keys; the active one is illuminated; content cross-fades in ≤ 80 ms.
- **EquipDialog**: 60% backdrop, scale .98→1 over 120 ms. Primary = illuminated key; destructive = red, needs confirmation.
- **Scrollbars**: 8 px recessed track, muted thumb.
- **Timeline** (Resolve-influenced, flatter, editor-bg):
  - thin separators, a dense toolbar, an orange playhead (triangle + 1 px line), a snap tick;
  - small MUTE/SOLO/LOCK-style keys only where they map to real state (layer visible = "ON", lock-to-entry = "LOCK").

### 6.2 Driver primitives (behaviour spec)
- **Panel**:
  - 1 px border, radius 2, optional corner ticks, 24 px header `[TITLE] [LIVE ● 12 Hz] [•••]`;
  - menu: reset, duplicate (where meaningful), pop out (§12), settings;
  - body scrolls internally; the page never scrolls in operational views.
- **Button**:
  - Primary: 28 px tall, accent border, 12% accent fill, hover glow, press scale .97, optional 180 ms light sweep (motion full).
  - Ghost: 1 px border.
  - Danger: red outline plus confirmation for meaningful actions.
  - Icon: 28×28 with tooltip and shortcut.
- **Chip**: 22 px. **LapChip**: `L12 1:47.932 PB ◆`; REF (cyan) and CMP (near-white) states; context menu for set ref/cmp/clear.
- **SegmentedControl**: TIME / DISTANCE / LAP %.
- **DenseTable**:
  - 24 px rows, sticky header, sortable, resizable columns (widths persisted), keyboard row navigation;
  - `VirtualList` above 200 rows; new-row flash (accent fading over 1.2 s); fastest-lap flash (purple 600 ms).
- **Inputs**: 26 px; searchable dropdown with type-ahead; a thin slider rail always paired with a value.
- **Stat**: label, value, unit, and optional trend glyph. Numbers tween 120 ms (reuse `motion.countTo`; disabled in motion off).
- **AlertLane**: timestamp, type icon, severity chip, message, source; slide-in 180 ms; virtualized.

### 6.3 Shared primitives
- **CommandPalette** (`Ctrl+K`, both workspaces, styled per active workspace). Indexes: routes and tabs, the 100 engineer requests (from `/api/engineer/requests`), sessions (recent 200), laps of the open session, telemetry channels, settings fields, layouts, and commands (start/end session, mute, PTT, demo/live, take program, clear program). Fuzzy match, keyboard-first, recent items, shortcut display. Destructive commands open their confirm dialog.
- **ContextMenu** (right-click and Shift+F10). Telemetry lane: hide, change channel, reset zoom, export PNG/CSV of the range. Session: open, protect, export, compare, purge (confirm). Graphic: preview, duplicate, edit, show/hide, copy OBS URL.
- **ConfirmDialog**: for destructive and race-wide actions. Two-step "ARM → EXECUTE" variant for Broadcast (§8.10).
- **Tooltip**: 500 ms delay, includes the shortcut. Global "Show control hints" setting.
- **Empty, loading and error states** (restrained technical copy plus a relevant action, no illustrations). Examples:
  - `WAITING FOR GT7 · Receiving on UDP 33740 · [Open diagnostics] [Try demo]`
  - `NO SESSION SELECTED`, `NO CARS CONNECTED`, `NO GRAPHICS IN THIS WORKSPACE`
  - `INITIALIZING RECEIVER`, `LOADING SESSION INDEX`
  - `TELEMETRY RECEIVER OFFLINE · port 33740 in use by PID … · [Retry] [Open diagnostics] [Copy error]` (use `receiver.port_owners`, `socket_error`)
  - Skeleton rows instead of spinners.

## 7. Unified status model (`src/app/status.ts`)
Derive from `/ws` state; don't add backend fields.

| State | Condition |
|---|---|
| OFFLINE | no `ps5_ip` and source live, or socket error |
| CONNECTING | receiver phase `bind`/`heartbeat`, no packets yet |
| LIVE | fresh, `rate_hz ≥ 45` |
| DEGRADED | fresh but `rate_hz < 45`, or gaps/parse errors rising in the last 10 s |
| RECONNECTING | stale less than `interrupt_seconds` after being live |
| ERROR | `socket_error` or port owner conflict |

- The source badge is separate: LIVE / SYNTHETIC DEMO / RECORDED REPLAY.
- **Recording** LED: green when a session is recording with no drops; amber for backlog; red for drops/failure (from `health.storage`).
- **Session**: status from `status`. **Group**: HOSTING n members / MEMBER connected / off.
- Normal jitter must not flash DEGRADED: use 3 s hysteresis. The connection LED pulses with incoming frames, throttled to at most 4 pulses/s.

## 8. Pages

### 8.1 Pit Wall → Live (`#/driver/pit-wall/live`)
Reference 1440×1080 layout (12-column `PanelGrid`, no page scroll):
```
STATUS RIBBON (compact tiles, 32 px)
CAR STATE (4 col) | TRACK MAP (5 col) | ALERTS / RADIO (3 col)
LAP TIMING (3) | FUEL & RANGE (3) | TYRES (3) | PACE (3)
CURRENT CAR (collapsible strip or tab in Car State) · ENGINEER CONTROLS (bottom action bar)
```
- **Status ribbon tiles**:
  - lap / total_laps (when > 0);
  - PLAYER STATUS (on track / paused / loading / off track), using a wipe animation on change and labelled "player status", not race flags;
  - session elapsed; fuel state; connection; Hz; recording; BOX intent (amber when marked);
  - POSITION, GAP and COMPOUND are **N/A tiles** (grey, "not transmitted"), or hidden via a "Show unavailable fields" setting (default: hidden).
- **Car state**:
  - huge gear (96 px condensed) with suggested gear (small "▲5" when it differs), speed next to it;
  - segmented RPM bar using `rpm_min/rpm_max` as the shift-light range, flashing on the rev-limiter flag;
  - throttle/brake/clutch bars; steering bar only when a B+ packet provides it (else N/A);
  - 10 s pedal trace sparkline (from `history`); boost (turbo flag only);
  - lamps: TCS, ASM, limiter, handbrake, lights.
- **Track map**: `CircuitMap`, a delta-coloured line, and an overlay selector (SPEED / BRAKE / THROTTLE / DELTA) on the current-lap trace. Opponents and flags only when group data exists (Race Control). Circuit/layout select, recognition status, export/import, and restore are in the panel menu.
- **Lap timing**:
  - current (needs trusted C fields, else "—"), last, best (PB ◆ green), estimated delta with a bar;
  - reference lap name; overall fastest only for connected-group data, else N/A;
  - sectors only as custom when a track model provides them.
- **Fuel & range**: litres, % of tank, laps remaining, L/lap, finish margin (green/red + text), saving %, refuel, uncertainty, and a sparkline of per-lap consumption. "LEARNING · need 3 clean laps" state. Units L/gal (view setting).
- **Tyres**: 2×2 surface temperatures with a restrained heat scale plus the numeric value; spread; "Surface temperature · not wear". Wear/pressure slots are N/A.
- **Pace**: last N comparable laps as bars (colour by fastest/PB/other), mean, median, trend glyph, best.
- **Alerts / Radio**: an AlertLane merging engineer `events`, the subtitle, transcripts (when enabled), group race-control messages/flags for the member, and system notices. Below it: mic LED, level meter (`audio.level`, clipping), hold-to-talk (pointer capture preserved), hands-free toggle, mute, "Enable audio".
- **Bottom action bar**: Start session / End session (confirm when laps > 0), Mark incident, Box this lap / Unmark (confirm), Try demo / Use PS5, AI brief.

### 8.2 Engineer, Strategy, Sessions, Analysis
- **Engineer**:
  - A command log with slash commands and autocomplete from the 100-intent catalogue (`/fuel`, `/finish`, `/save`, `/pit`, `/last`, `/best`, `/delta`, `/tyres`, `/status`, …). `/gap`, `/weather`, `/position` resolve to the catalogue's honest "unavailable" answers.
  - Quick-command chips; voice transcript (opt-in); local AI brief (`LocalBrief`) with evidence; the scheduler decision history (spoken/merged/suppressed + reason).
  - Radio verbosity (Quiet / Normal / Detailed / Coaching / Critical-only), hard mute, speech tests.
- **Strategy**:
  - Fuel calculator inputs (reserve, race laps/minutes, extra lap, target lap) with **Apply assumptions**; live outputs.
  - **Scenario A vs B**: a client-side what-if using the measured burn/lap time and user-entered pit loss/refuel rate, labelled "user assumptions".
  - If `fuel_scenarios` exists (see `docs/specs/ACTION_DIRECTOR_AND_COACHING_SPEC.md`), show its branches.
  - Stint/margin chart (uPlot). The BOX THIS LAP banner is prominent but needs confirmation.
- **Sessions**:
  - Master-detail. A DenseTable (session, track/layout, car, date, duration, laps, best, provenance, protected ◆, tags, notes), with search, filter (provenance/track/car/protected) and sort.
  - Preview panel: summary, lap mini-chart, metadata editor.
  - Actions: open in Analysis/Telemetry, replay (play/pause/speed/seek), export, import, compare, protect, archive, retention preview/apply, purge (typed confirmation).
- **Analysis**:
  - Filters and session summary; a lap table (lap, time, Δ best, fuel used, validity-by-app-quality, notes, incident markers) with sparklines; select ref/cmp; comparison graphs (`align_laps` delta).
  - Insights feed from the report improvement cards: severity, title, metric, jump-to-lap/corner.
  - A corner report when spatial coaching exists; otherwise the empty state "Corner analysis needs a locked track model".

### 8.3 Pit Wall → Telemetry (the most important Driver page)
```
TOOLBAR: session ▾ | lap chips (REF cyan, CMP white, others) | X: TIME·DISTANCE·LAP% | RANGE ▾ | LIVE/PAUSE | refresh
CHANNEL TREE (240px) | TELEMETRY LANES (flex) | MAP (360px) + CORNER DATA
CURSOR / STATISTICS BAR (mono readout per channel per lap; brush summary)
```
- **Channel tree**, searchable. Groups use only fields that exist:
  - DRIVE: speed, throttle, brake, clutch, gear, suggested gear, rpm
  - CHASSIS: steering (B+), longitudinal g (derived), angular velocity (raw), suspension ×4, body height
  - WHEELS: wheel speed ×4 (derived from rad/s × radius), slip ratio (derived, suppressed < 30 km/h)
  - TYRES: surface temperature ×4
  - FUEL: fuel, fuel/lap (derived)
  - ENGINE: boost, oil pressure, gearbox rpm
  - TIMING: lap, delta (derived)

  Each row: visibility, swatch (semantic for pedals), unit, drag handle. Drag a channel into a lane or onto "+ new lane".
- **Lanes**: stacked uPlot instances sharing one x-scale via uPlot's `cursor.sync` key. Defaults: SPEED · THROTTLE+BRAKE · GEAR · RPM · STEERING (if available) · DELTA (if a reference exists).
  - One linked crosshair drives the cursor readout, the map marker (cursor distance → position on the lap trace), and the corner highlight.
  - The drag/brush selection box shows MIN/MAX/AVG/Δ/time/distance plus **Compare this section**.
- **Range**: LIVE (follows `history`; scrolling back pauses follow and shows **RETURN TO LIVE**), LAST 30 s, LAST 60 s, CURRENT LAP, LAP N, SESSION, CUSTOM.
- **Axis**: DISTANCE is the default for lap comparison. Distance is cumulative from positions (and v3 `s` when available). Switching axis keeps the cursor at the same sample.
- **Annotations**: vertical markers across all lanes for lap boundaries, marked incidents, box intent, pause, pit (when detected), engineer alerts, user bookmarks (B key).
- **Keys**: Space live/pause, +/− zoom, J/K step samples (replay/recorded), 1–9 toggle lanes, Esc clear selection, B bookmark.
- **Backend addition allowed (read-only, small)**: `GET /api/sessions/{sid}/laps/{lap_id}/samples?channels=a,b,c&points=2000` returns per-channel **min/max-preserving** decimated series plus distance and time axes. The current endpoint is one channel with a 10k-row page. Add tests.
- **Architecture**:
  - A panel-type registry: timeseries, stat, table, histogram, state-timeline, XY scatter, track map, corner table. Ship the timeseries, map, stat and table types now; register the others with empty states.
  - Derived channels come from a pure-function registry `src/telemetry/derived.ts` (overlap, speed difference, delta, fuel per lap, steering rate, brake release rate), independent of rendering.
- **Performance**:
  - no per-sample React state: use a ring buffer in a store, and uPlot `setData` batched on requestAnimationFrame;
  - screen-space decimation; lanes only for visible panels.
  - Target: 60 fps interaction with 6 lanes × 2 laps × 2000 points, and ≤ 4 ms main-thread per live frame at 12 Hz UI.

### 8.4 Wheel (`#/driver/wheel`)
- Preserve `WheelDash` behaviour (pages RACE/TIMING/FUEL/TYRES/STRATEGY/MAP, ←/→, page visibility setting, shift lights, lamps, mini-map).
- It now opens inside the Driver shell with a **FULLSCREEN** key (F, or the Fullscreen API). Esc exits fullscreen back to the framed view instead of leaving the page. Keep its own dense dash styling; only align the fonts and tokens.

### 8.5 Training (`#/driver/training`)
- Keep all current behaviour: untrained list, goals, the roulette pick, start/stop/retry/restart capture, the point-cloud visualizer, the 2500 points/km goal. Restyle it in the Driver system.
- **Progression layer** (frontend plus a small persisted file, no invented telemetry):
  - Tabs: Dashboard · Track Coverage (the existing goals) · Challenges · Progress · Achievements.
  - Levels: Rookie → Club → Regional → National → Pro. XP comes from **real events only**: laps saved in training, layouts completed, clean comparable laps recorded, consistency (std of the last 5 comparable laps below a threshold), sessions completed.
  - Badges: hexagonal technical shields in bronze/silver/gold/platinum. Families: Track Mastery (layouts completed), Consistency, Precision (delta vs reference within X), Streaks (days), Collections (venues).
  - Storage: `GET/PUT /api/training/progress-profile` backed by `data/training-profile.json` (atomic write). Compute XP server-side from existing records.
  - **No reward popups during driving or on Pit Wall Live.** Show them post-session, on Training pages and in the debrief.

### 8.6 Race Control (`#/broadcast/race-control`)
ATEM-style equipment layout (1440×1080):
```
SESSION STRIP: league/event · layout · format · state · elapsed/remaining · coverage · hosting LEDs · delay
ENTRANTS (left, 320px) | TRACK + ZONES + INCIDENTS (center, CircuitMap with markers) | COMMAND BANK (right, 380px)
TIMING TABLE (connected-group standings, labelled) | EVENT LOG / STEWARD LOG (bottom, tabbed)
```
- **Entrants**:
  - a car list with number, driver, team, class, car thumbnail, a freshness LedLadder, sharing categories, admission status;
  - admit/remove (confirm); invitations (driver/spectator, copy, rotate, expiry); join lock/unlock.
- **Command bank**:
  - **FLAG keys** GREEN / YELLOW / DOUBLE YELLOW / RED / BLUE / WHITE / BLACK / BLACK-WHITE / MECHANICAL / CHECKERED / SC / FCY / VSC, in their flag colours with a text label and glyph.
  - Scope BusRow: GLOBAL / ZONE / CAR; zone LcdSelect; entrant from the selection; reason field; expiry knob.
  - The active instruction list has cancel keys.
- **Messaging**: target BusRow (ALL / CLASS / TEAM / CAR), preset keys (templates), a recessed text field, a priority knob, an acknowledgement lamp toggle, public toggle, and a history with delivered/displayed/acknowledged LEDs.
- **Stewarding**: decisions (incident, investigation, warning, time, laps, DQ, order, correction), status BusRow, public/private lamp, and an audit log.
- **Session controls**: start / end / finalize results / close group (finalize and close require ARM→EXECUTE).
- **Map/zones editor**, roster and identity editing, branding link, replay (Timeline with orange playhead, play/pause/speed/seek, **EXIT REPLAY**), and the rehearsal demo (4/8/16 drivers, pause/resume, 1×/2×/4×, simulate disconnect/ack).
- Host-only mode lives in the session strip, with an explicit lamp.

### 8.7 Studio (`#/broadcast/studio`)
- **Monitor wall**: PREVIEW (green tally, the draft) and PROGRAM (red tally, the permission-filtered program, showing its effective delay), side by side at 16:9, rendered with the **existing overlay renderers**.
- **Transition bank**: CUT (Take), AUTO (Take with a progress gesture), T-BAR, CLEAR PROGRAM (confirm), SAVE DRAFT, DISCARD CHANGES (confirm), plus the UNSAVED DRAFT lamp.
- **Car selection**:
  - A PRIMARY bus: a program row (red; the live program's primary slot) and a preview row (green; the draft's primary slot) with keycaps per entrant (number plus 3-letter driver code). The same for slots A and B (collapsible).
  - Selection mode keys: MANUAL / LEADER / CLASS LEADER / POSITION (disabled with a hint when classification is unusable).
  - A searchable roster with favourites/pinned: number, driver, team, class, car, colour chip.
- **Graphics library**: categories (Timing, Driver, Battle/Comparison, Session, Race Control, Track, Results, Branding, Pit/Strategy, Status).
  - 26 templates today, from the registry; use the registry to grow toward about 50 without placeholders.
  - Tiles show a live thumbnail, required sharing, and recommended size. Add to workspace; right-click: preview, duplicate, edit, show/hide, copy OBS URL.
- **Scene layers**: a Resolve-like dense layer list with ON (visible), LOCK (locked entry), and a duration knob. The inspector has x/y/w/h RecessedInputs, a slot BusRow, title, rows knob, opacity fader. Drag placement on the preview canvas shows the safe-area overlay (the branding `safe_area`).
- **Style gallery**: the 10 presets as live swatches (existing).
- **League branding and media library**: logos (primary/light/dark/compact/watermark) on light/dark/checkerboard, colours, sponsors, teams, event overrides. Uploads go through the existing validated endpoint; no remote URLs.
- **Output / Deliver** (a sub-tab within Studio):
  - hosting listener LEDs and allowed origins;
  - per-graphic and composite OBS URLs with resolution (recommended size / 1920×1080), transparency note, 30 FPS hint, **COPY URL** key, refresh/regenerate credential (confirm);
  - viewer count LEDs, broadcast delay fader.

### 8.8 Settings
- **Global** (neutral):
  - General: startup route, restore last route.
  - Appearance: UI scale 90–125%, density compact/comfortable, motion Full/Data only/Off, high contrast, dark/light; `reduced_motion` backend setting stays in sync.
  - Input: shortcut list.
  - Connections: PS5 IP, bind, ports, variant, heartbeat, reception test, Pair browser.
  - Audio: devices, speech engine/voice/rate/volume, mic/noise tests, key sounds.
  - Storage: data folder info, retention, backups hint.
  - Advanced: diagnostics, trust C fields, raw capture, local AI.
  - Recovery link.
- **Driver settings** (Driver style): units, telemetry defaults, engineer mode and quotas, alert thresholds, coaching, Training, chart prefs, show-unavailable-fields.
- **Broadcast settings** (Broadcast style): OBS defaults, key sounds, confirmation strictness, race-control defaults (flag expiry, message templates), branding defaults.
- Server-affecting fields still save through `PUT /api/settings`. View-only preferences go to `viewStore`.

### 8.9 Notifications
One notification center (bell with a count that animates on increment). Sources: engineer events, receiver/recording errors, group events (member joined/left, ack received, battle alerts when implemented), recovery notices. Each notification is actionable (jump to route/entity).

### 8.10 Safety rules (both workspaces)
- **ARM → EXECUTE** (two presses within 5 s; the armed key pulses amber) for: RED flag, CHECKERED, BLACK (DQ-style), finalize results, close group, clear program, regenerate credentials, purge session.
- Plain confirm dialog for: end session with laps, delete/purge, revoke invitation, remove participant, discard draft, BOX THIS LAP.
- Pending confirmations are never persisted.

## 9. Interaction systems

### 9.1 Motion (`data-motion`)
- **Full**: all micro-interactions and ≤ 3 ambient effects: connection LED pulse on packets, a one-time panel reveal on workspace open, a scan sweep after a dataset load.
- **Data only**: number tweens, row flashes, crosshair, alert slide; no ambient or physical overshoot.
- **Off**: instant state changes.
- Default: Data only, and Off when `prefers-reduced-motion`.
- Pause ambient effects when `document.hidden`.
- Budgets: animate transform/opacity only; ≤ 2 box-shadow layers per element; no `backdrop-filter` blur anywhere.

### 9.2 Accessibility
- Everything reachable by Tab/Shift+Tab; Enter/Space activate; Esc closes.
- Arrows navigate bus rows, tabs, tables, menus and lap chips (roving tabindex).
- ARIA: bus rows are `radiogroup`; keycap toggles use `aria-pressed`; lamps use `role=status` with a text label; dialogs are focus-trapped.
- Contrast ≥ 4.5:1 for text (verify token pairs). The high-contrast token set is wired even if minimal.

### 9.3 Layout and density
- **Layout families** from container width:

  | Family | Width |
  |---|---|
  | COMPACT | < 1200 |
  | STANDARD | 1200–1599 (reference 1440×1080) |
  | WIDE | 1600–2399 (1920×1080) |
  | ULTRAWIDE | ≥ 2400 or aspect > 2.1 |
  | TALL | aspect < 1.4 |

- Each panel declares min/preferred/max width, a priority, and its collapse behaviour (becomes a tab in a shared "More" panel).
- **PanelGrid**: 12 columns; drag/resize/dock inside the grid; reset layout; saved layouts. Presets: ENGINEER, STRATEGIST, DRIVER (Live-focused), BROADCAST OPERATOR, DIRECTOR.
- **COMPACT fallback**: single column, internal scrolling, still usable on a laptop or phone for quick checks. The app previously supported 360 px phones; keep Live and Wheel usable there, but don't design around it.

### 9.4 Shortcut registry (`src/app/shortcuts.ts`)
- Scopes: GLOBAL, BROADCAST, DRIVER, PAGE, CONTEXT.
- Registering a key already used in an overlapping scope throws in dev. Shortcuts are listed in tooltips, the palette and Settings → Input. The key map is data-driven, so it's editable later.
- Keycaps and buttons receive `data-pressed` for shortcut-triggered animation.

## 10. Popouts / multi-monitor (phase 6, optional but architected)
- `#/popout/{panelId}` renders a single panel in a new browser window.
- A `BroadcastChannel('gt7-ui')` syncs cursor distance, selected laps/entrant and program revision between windows.
- In pywebview desktop mode, if `window.open` is unsupported, show "Open in browser to pop out" with a copy link.

## 11. State architecture (no new libraries)
- `src/app/store.ts`: a minimal external store (`createStore<T>()` with `getState`, `setState(partial)`, `subscribe`, and `useStore(selector, equality)` via `useSyncExternalStore`).
- **Domain stores**:
  - `liveStore`: the latest `/ws` state split into slices (`sample.values`, `health`, `audio`, `session`, `fuel`, `track`, `events`, `training`, `replay`, …). Components subscribe to slices, so a speed change must not re-render Sessions.
  - `telemetryRing`: a typed-array ring buffer of recent samples for charts, outside React.
  - `groupStore`: `/api/group/state` polling/stream as it works today, in slices.
- **View store**: `viewStore` (persisted, versioned `ui:v1:*` keys, debounced writes, try/catch around storage). The workspace, route, layouts, lanes, laps, axis, zoom, table state and motion setting.
- The WebSocket lives in `src/app/liveConnection.ts`: a singleton with reconnect and the existing reconnect banner. It's created once at app start and **never** torn down by navigation.
- `App` renders only the shell, the router outlet and providers; pages pull data through selectors.

## 12. Iconography and sound
- **lucide-react only** (already installed); 16 px in Driver, 14 px in Broadcast keycaps. No emoji anywhere in the operator UI.
- **Sound**: optional Broadcast key clicks (default off). Driver stays silent except existing engineer speech and alert audio. State never depends on sound.

## 13. What not to do
- Generic Tailwind/SaaS cards, glassmorphism, neon RGB, blur, radii > 6 px, giant single-number cards, a mobile hamburger shell, Material/Bootstrap look-alikes, decorative animation, fake screws everywhere.
- Fake data or controls without a backend: PTZ, audio mixing, weather, tyre wear, positions.
- Changing OBS overlay output, the `/group` public page, `/overlay/*`, or `/recovery`.
- Stopping services on navigation.

## 14. Implementation plan (incremental; the app must build and pass tests after every phase)

| Phase | Deliver | Done when |
|---|---|---|
| 0 Map | Inventory `docs/UI_MIGRATION_MAP.md` (every current control → new home); performance baseline (React Profiler: renders/s of App at 12 Hz; bundle size) | Map reviewed against `main.tsx`, GroupControl, RaceDesk, GroupStudio, WheelDash, Training |
| 1 Foundations | fonts, tokens, `store.ts`, `liveConnection`, `liveStore` slices, router, shortcut registry, motion setting | App behaves as before on new plumbing; App no longer re-renders on every frame (only subscribed leaves) |
| 2 Shell | TopBar with both dropdowns, IdentityBar, StatusCluster, notifications, command palette skeleton, route migration from old `page` | All old pages reachable via new routes; navigation preserves services (test) |
| 3 Primitives | `ui/shared`, `ui/driver`, `ui/broadcast` components plus a hidden `#/dev/components` gallery route (dev builds only) | Keyboard and motion tests pass for Keycap, BusRow, TBar, LcdSelect, Panel, DenseTable, SegmentedControl, LapChip, CommandPalette |
| 4 Driver pages | Live, Engineer, Strategy, Sessions, Analysis, Wheel framing, Training restyle | Every migrated control works; 1440×1080 has no page scroll; N/A slots correct |
| 5 Telemetry | lanes with cursor sync, channel tree, lap chips, axis modes, range/live follow, annotations, map linking, brush stats, new lap-samples endpoint | Cursor at a point moves the marker on the map and the readouts; 60 fps interaction budget met |
| 6 Broadcast pages | Race Control equipment layout, Studio monitor wall/transition bank/buses/library/inspector/deliver | Take/Cut/T-bar publish atomically; ARM→EXECUTE on dangerous keys; overlays unchanged (screenshot diff of `/overlay` output before/after) |
| 7 Progression, popouts, layouts | Training progression and API; PanelGrid drag/resize/saved presets; popouts + BroadcastChannel | Layout persists across reload; popout cursor sync works in the browser |
| 8 Polish and verify | empty/loading/error states everywhere, context menus, high contrast, grayscale check | Acceptance list (§15) all green |

**For every component replaced**: (1) list what it owns, (2) keep that behaviour, (3) migrate, (4) test, (5) continue. Prefer small coherent commits.

## 15. Testing and acceptance
- **Playwright** (update the existing specs to the new selectors; add these):
  - workspace routing via both dropdowns (opening a dropdown doesn't navigate);
  - state preservation: Telemetry with 2 laps + zoom → Race Control message → back = identical;
  - WS not reconnected and no control POSTs on navigation (network assertion);
  - keyboard-only walk of shell, palette, bus rows and tables;
  - ARM→EXECUTE on the RED flag;
  - Take via CUT and via the T-bar;
  - layout persistence across reload; motion Off honoured;
  - the connection-state matrix via demo/replay/stale.
- **Screenshots** at 1440×1080, 1920×1080, 3440×1440 and 1280×800 for every route, saved in `docs/screenshots/redesign/`. Include **grayscale versions of one Broadcast and one Driver page**; they must still be clearly distinguishable. Also compare OBS overlay screenshots before and after (must be unchanged).
- **Performance**:
  - React Profiler: App commits ≤ 1 per second at idle (leaf components update instead);
  - Telemetry frame ≤ 4 ms scripting at 12 Hz;
  - no layout thrash warnings;
  - bundle growth reported (fonts excluded).
- `pytest -q` stays green (backend changes are only the lap-samples endpoint and the training profile).

**Acceptance (all must hold)**:
- Broadcast and Driver are unmistakably separate (including in grayscale) inside one app.
- Both menus are always visible.
- Switching preserves view state and never interrupts services.
- Broadcast has physical key behaviour; Driver has flat data controls.
- Telemetry lanes share a cursor linked to the map.
- The 1440×1080 reference has no page scroll, with sensible 1080p/ultrawide adaptation.
- Keyboard operation, reduced motion, and designed empty/loading/error states.
- All existing features are reachable and working (per the migration map).
- No fabricated data; OBS output unchanged.

## 16. Final report
Include: files changed; the migration map summary; before/after performance numbers (measured); screenshots list; anything deferred (with reason) and extension points left (panel types, derived channels, popouts); any new dependency and why.

**Don't reply with only a plan. Inspect the repository and begin implementing at Phase 0.**
