# Task: Track recognition engine + full map-system overhaul

Work in the existing repo. Read first: `backend/app/tracks.py`, `track_geometry.py`, `live_delta.py`, `group/timing.py`, `scripts/build-track-references.py`, `frontend/src/RaceVisuals.tsx`, `docs/TRACK_MEMORY.md`, `docs/TRACK_REFERENCE_COVERAGE.md`. All earlier project rules still apply and are not restated: data truthfulness, local-first, bounded queues, a single receiver, the ARM64 Orange Pi 4 GB target, and no network at runtime.

**Replace, don't layer.** The new engine supersedes `Fingerprint`/`shape_fit` matching and the duplicate projection code. Keep the layout IDs in `tracks.json`. Keep existing API routes (extend them, don't break them). Migrate the user's learned maps without losing any.

## 0. Critical fix (do first)
`signatures.json` from jbhoorasingh/gt7-datalogger-track-data stores `path` in **GT7 world-space metres (x, z)**, with bounding boxes, in driving order, at 20 m spacing. `build-track-references.py` normalises it to 0–1000, which throws away position and scale. That is why recognition currently needs a full lap, a shape fit and user confirmation.

GT7 uses a fixed world frame per circuit, so world-space references allow recognition from position within seconds.
- Rebuild the bundle and keep the raw world coordinates.
- Before relying on it, verify it against a real recorded live lap in `data/` (median distance about 15 m or less). Document the result.

## 1. Data sources
Build time only. Pin each source to a commit, store a checksum, and put licences in `docs/licenses`.
- **jbhoorasingh/gt7-datalogger-track-data** (re-pin to latest `main`):
  - `signatures.json`: path, bbox, length, `reverse` twin, `ambiguous_with`, `flags`.
  - `tracks/<slug>.json` surveyed bundles (format v5: borders, walls/run-off, start/finish line, named corners) for about 25 circuits.
- **zetetos/gt-telemetry** lap captures, as vendored in that repo, for configurations without a survey.
- **User data**: `data/track-maps/*.json`, `_corpus.jsonl` (confirmed clean laps), and the SQLite recordings (60 Hz positions).
- Add `scripts/track-tool.py` (build, refresh, report). Map sources to layout IDs by exact name (existing normaliser) plus a length check. Report anything unmatched. Never fetch at runtime.

## 2. Track model: schema v3, one per layout ID
- `frame`: `gt7-world` | `normalized-legacy`.
- Centreline resampled every 2 m as `[x, y_elev|null, z]`, with cumulative `s`, heading, curvature and length.
- Left/right edges, each with a source: `surveyed` | `observed-envelope` | `none`.
- Start/finish line (point + normal, with source). Pit lane as its own polyline, with entry/exit `s`, never part of the lap path.
- Corners: `[id, name, s_start, s_apex, s_end, dir, source: surveyed|auto|user]`. Custom sectors. Marshal zones as `s` ranges.
- Provenance on every element, a revision hash and 8 history entries. The spatial index is built at load time, not stored.
- **Fusion**: align confirmed laps by `s`, then take the median lateral offset per 2 m bin, rejecting outlier laps, to get a consensus centreline. The lateral spread becomes an envelope labelled "observed driving envelope", never "track limits". Raw laps stay in the corpus.
- **Auto corners**: curvature peaks with hysteresis and a minimum length, merging chicanes. Number them T1… from start/finish. Surveyed names override auto names, and user renames persist.
- Migrate v2 maps losslessly (elevation becomes null).

## 3. Recognition engine: `backend/app/track_recognition.py`
Use classical probabilistic map matching. This is the "AI"; no neural network.
- **A. Prune**: a global grid (25 m cells) maps each cell to the layouts that pass through it. Candidates are the layouts under the recent points.
- **B. Score**: each candidate runs an HMM/Viterbi, or at most 32 particles, over `s`.
  - Emission: Gaussian on distance to the centreline (σ≈6 m, clipped), on elevation difference when both are known (σ≈3 m), and on heading agreement (reverse direction is heavily penalised).
  - Transition: Δs must match speed·dt. No backward jumps except the start/finish wrap.
  - Forgetting window of about 2 km, so teleports and track exits recover.
- **C. Extra evidence**: position of the lap-counter increment vs the start/finish line; completed-lap length vs model length; pit entry. C-packet surface is weak evidence, used only after it's validated.
- **Decision**: compute a posterior over the candidates plus an **unknown** hypothesis (a uniform background likelihood), so off-map and unmodelled tracks stay unknown.
  - **Lock** only when: top posterior ≥ 0.98, likelihood ratio to #2 ≥ 50, ≥ 400 m travelled, and a discriminating section has been driven. For each pair of layouts, precompute the `s` ranges where they differ by more than 20 m. Shared sections alone never lock.
  - **Equivalence classes**: layouts within 5 m of each other everywhere lock as a class. Ask the user only if the choice changes start/finish or timing.
  - Direction is always decided by heading, never by shape.
- **Unlock / re-evaluate** on: off-track/paused flags lasting more than N s, a position jump over 200 m, a car change, a provenance change, or sustained unknown likelihood. Use hysteresis so it doesn't flap.
- **Output** at 5 Hz or less:
  - state (`searching|candidates|locked|ambiguous|unknown`) and the top 5 candidates with probability;
  - the lock reason and evidence, plus the time and distance it took to lock;
  - for the locked layout: `s`, lateral offset, and the current corner/sector.
- **Manual selection always wins.** If the manual choice fits badly, offer a switch; never change it silently.
- **Unmodelled track**: when the state is unknown after a clean closed lap, create a candidate model for confirmation (as today). Once confirmed, it becomes a world-frame model.
- **Budget**:
  - p95 ≤ 2 ms per update for all 122 layouts on one A55 core. Measure on x86 and extrapolate honestly; mark it as needing board verification.
  - All models ≤ 40 MB RAM.
  - Runs in the track worker, never in the receive loop.

## 4. One progress service
Build a single `TrackProgress` API and use it everywhere:
- live delta (compare at equal `s`; remove the 1500-point / 5-minute limit);
- lap fraction for fuel;
- Race Control timing and zones (replaces `group/timing.Projection`);
- analysis lap alignment (replaces index- and distance-fraction alignment where a model exists);
- OBS.

Delete the duplicated projection code.

## 5. Frontend map overhaul
Build one reusable `<TrackMap>` in `frontend/src/map/` (Canvas 2D), shared by Live Race, Analysis, Race Control and the Broadcast graphics.
- **View**: auto-fit and auto-rotate (or user-fixed north); pan, zoom, pinch and reset; Douglas–Peucker level of detail per zoom; devicePixelRatio aware; redraw only on change.
- **Layers** (each toggleable):
  - surveyed edges/walls or the observed envelope;
  - consensus centreline and reference line;
  - current line coloured by delta (existing green/red/grey);
  - speed/brake/throttle heat overlay in Analysis;
  - start/finish, pit lane, sectors, marshal zones in their flag colours;
  - corner labels and incident markers.
- **Cars**: marker with a heading arrow. Multiple numbered cars for Race Control/OBS, the selected car highlighted, stale cars greyed.
- **Elevation strip**: synced to `s`. Hovering the map moves the telemetry chart crosshair and vice versa.
- **Recognition UI**:
  - a status chip ("Searching", "3 candidates", "Locked: Suzuka East 98%", "Unknown");
  - a candidate list with probabilities and Confirm / Not this;
  - the manual picker and the reason text;
  - the track logo once locked.
- **Editor**: rename corners; drag sectors and zones along the centreline (`s`-based); set start/finish; mark the pit lane. Save as a user layer with a revision, with undo.
- **Broadcast variant**: transparent, no controls, styled from branding.
- Must be usable at 360 px.

## 6. Storage and API
- `data/track-models/*.json` (v3): atomic writes plus history. The built-in bundle `backend/app/data/track-models.bundle.json(.gz)` is read-only. User layers overlay the built-in data; they never overwrite it.
- Endpoints:
  - `GET /api/tracks/{id}/model?lod=`
  - `GET /api/track-recognition`
  - `POST` confirm / reject / select
  - `PUT` user layers
  - import/export of a track pack (checksum, size limits, validation, merge rather than overwrite)
- Keep the old `/api/track-map` routes as a compatibility shim until the frontend has migrated.

## 7. Evaluation harness (required): `scripts/eval-recognition.py`
- **Data**: the corpus, the SQLite recordings, held-out vendored captures, and synthetic perturbations:
  - position noise σ 1–5 m and packet dropouts;
  - starts from the pit exit or a mid-lap join;
  - reverse direction and rejoining after a menu;
  - teleports between tracks.
- **Report per layout**: accuracy, false-lock rate, median/p95 time and distance to lock, ambiguity rate, a confusion matrix, and runtime p50/p95.
- **Acceptance**:
  - zero false locks;
  - at least 95% of world-frame layouts lock within 1 km from a random start (documented equivalence classes excepted);
  - reverse layouts are never confused.
- Tune until the acceptance targets pass. Write `docs/recognition-eval.json` plus a summary.

## 8. Tests
- **Unit**:
  - model build/migration, fusion, auto corners;
  - start/finish wrap and pit divergence;
  - crossings and bridges: `s` must not jump when paths cross, using elevation and heading;
  - index pruning and lock/unlock hysteresis;
  - equivalence classes, unknown tracks, manual override;
  - provenance isolation (demo/replay never write models).
- **Integration**: replay a recorded session through the pipeline and check that it locks and produces `s`-based delta.
- **Playwright**:
  - the map at 360 px and 1920 px;
  - chip state transitions;
  - editor save and undo;
  - a transparent OBS map.
- Existing suites must stay green.

## 9. Code quality
Code you touch must be readable: one statement per line, type hints, and docstrings on public functions. Run `ruff`/`black` on touched Python and `prettier` on touched TypeScript. Keep lines under 120 characters. Split the map UI into modules.

## 10. Order and report
Order: 0 → 2 → 3 → 7 (tune) → 4 → 5 → 6 → 8. Keep the app working after every step.

Docs:
- Replace `docs/TRACK_MEMORY.md` with `docs/TRACKS.md`: how recognition works, what the confidence numbers mean, editing, and track packs.
- Coverage report per layout: surveyed / world capture / user-learned / none.
- Update `THIRD_PARTY_NOTICES`.

Final summary:
- files changed;
- evaluation numbers you actually measured;
- coverage counts;
- what's still unverified (Orange Pi timing, live PS5 check of the reference-frame alignment);
- remaining work.

Never report a result you did not measure.
