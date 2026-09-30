# Task: Put the track map on Pit Wall and Wheel, and build a dense SimHub-style Wheel dash

Repo: GT7 Race Engineer. The backend is Python/FastAPI; the frontend is React/TS/Vite in `frontend/src`. The track/map backend was just rebuilt (`backend/app/track_*.py`). Build on it; don't rewrite it.

## Ground rules (token budget)
- Don't read `main.tsx` (about 39 KB) end to end. Use `grep` or a targeted `Read` with offset/limit.
- Start with these files:
  - `frontend/src/WheelDash.tsx` and `WheelDash.css`;
  - `frontend/src/RaceVisuals.tsx` (`CircuitMap`, `TrackSelect`);
  - the grep hits in `main.tsx` for `WheelDash`, `RaceVisuals`, `PITWALL_TABS`;
  - `backend/app/api.py` routes `/api/track*`;
  - `backend/app/runtime.py` for the live state fields (`track_selection`, `live_delta`, `trace`, and anything new from the track rebuild);
  - `frontend/src/colors.ts`.
- Reuse the existing map component. If the track rebuild added a newer map component or API, use that instead and remove the duplicate. **Never create a third map renderer.**
- Only edit what this task needs. Don't reformat unrelated code.
- Earlier project rules still apply:
  - values are real, calculated or shown as "—"; never fake data;
  - semantic colours: throttle green, brake red, clutch light blue, overall fastest purple, personal best green, other laps yellow, delta line green when gaining and red when losing.

## 1. Answer first (before you edit anything)
In 3–5 lines, tell me exactly where the map currently lives: mode, tab, panel and component. Tell me whether Wheel has it. Then continue.

## 2. Map on Pit Wall
- Make the map easy to find on **Live Race**: near the top at desktop widths, never collapsed by default.
- Add a compact map card to **Telemetry** (car position plus delta-coloured line) and to **Analysis** (the selected lap's line, clickable to jump the chart cursor if the data supports it).
- Everything uses the same component with props. Performance:
  - redraw only when the data changes;
  - cap the points drawn;
  - skip hidden tabs entirely.

## 3. Map on Wheel
- **RACE page**: a mini-map tile showing the car dot with a heading arrow, the delta-coloured recent line, the start/finish tick, and the track name or recognition state.
- **New MAP page** in the Wheel pager: a full-size map, the current corner/sector if the backend provides it, the lap and delta, and the recognition status ("Recognizing", "Locked 98%", "Unknown").
- **Wheel map settings**: `interactive=false`, high contrast, thicker lines, no controls. When unknown, show a "Track unknown" state instead of an empty box.

## 4. Denser Wheel dash (the main visual job)
**Reference image**: `docs/reference/wheel-reference.png`. Open it with Read and match its density and layout style. If the file is missing, ask me for it and use the patterns below meanwhile.

**Patterns to copy** from SimHub dashes (Lovely Dashboard, Formula/GT3 dashes, DDU-style) and real car displays (F1 steering wheel, GT3 / Porsche Cup / Aim / Motec dashes):
- a full-width shift-light LED strip across the top;
- a huge centre gear, with speed and RPM beside it;
- tight tile grid, thin 1px dividers, almost no padding;
- tabular monospace digits, and a label above every value;
- colour-coded states, with a text label next to every colour.

**Content for the RACE page**. Everything below must be real telemetry or clearly calculated; verify field names in `telemetry.py` and the runtime state:
- **Shift lights** from `rpm` against the packet's `rpm_min`/`rpm_max` alert range (upstream "RPM flashing alert"), not a guessed redline. The rev-limiter flag makes the strip flash.
- Gear, and the **suggested gear** (high nibble of `gears`) with a "shift ↑/↓" hint.
- Speed, RPM, turbo boost (value − 1 per upstream; hide when the car has no turbo per flag bit 4).
- Throttle, brake and clutch as vertical bars, plus the throttle/brake overlap percentage if live analysis provides it.
- Lap timing: current (needs trusted C fields, otherwise "—"), last, best, delta with a bar, predicted lap only if the backend computes it, and the lap count and total when meaningful.
- **Fuel**: litres, percentage of tank, litres per lap, laps remaining, finish margin, and whether saving is required.
- **Tyres**: 4 surface temperatures on a colour scale plus front/rear and left/right spread. Label it as surface temperature.
- **Status lamps from the flags bitfield**: TCS active, ASM active, rev limiter, handbrake, lights / low / high beam, paused, in gear.
- **Dynamics**: longitudinal/lateral g if validated (otherwise longitudinal only), per-wheel slip indicator from wheel speed vs car speed (suppressed at low speed), and suspension travel bars.
- Mini-map tile (section 3), the top engineer message line, box-this-lap and connection/stale lamps.

**Don't show**: brake bias, TC/ABS levels, ERS/DRS, tyre wear or pressure, race position, or water/oil temperature warnings. Either leave them out or show them as greyed "N/A" slots, whichever looks better. Don't invent values to fill space.

**Other pages** (TIMING, FUEL, TYRES, STRATEGY, MAP): same density. Each fills the screen with a grid; no big empty areas.

**Layout targets**:
- 800×480 and 1024×600 (common wheel/USB screens), 1280×480 ultrawide, and phone landscape;
- no scrolling, and gear readable at arm's length;
- use CSS grid with named areas per breakpoint.

**Performance**: the dash updates at the UI stream rate. Keep the existing GSAP effects light. Use refs or memoised tiles so one packet doesn't re-render the whole tree.

**Pages via settings**: let the user show or hide Wheel pages. Keep the existing ←/→ and Esc keys.

## 5. Verify, then iterate
1. `cd frontend && npm run build`: no TypeScript errors. Run `pytest -q` if you touched the backend.
2. Using the demo source, take Playwright screenshots of:
   - Wheel RACE and MAP pages at 800×480, 1024×600 and 1280×480;
   - Live Race, Telemetry and Analysis at 1440 wide and 360 wide.

   Save them to `docs/screenshots/`. **Open each screenshot, compare it against the reference image, and fix any overlap, clipping or sparse areas.** Do at least one improvement pass.
3. Add or extend the Playwright checks: map visible on Live Race and Wheel MAP, the Wheel pager includes MAP, and no console errors.
4. Finish with a short summary:
   - where the map is now (per mode/tab);
   - files changed;
   - which Wheel fields are live, which are calculated, and which are N/A;
   - screenshots taken;
   - anything left undone.
