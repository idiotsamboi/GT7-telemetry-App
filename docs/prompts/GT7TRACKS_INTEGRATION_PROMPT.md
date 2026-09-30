# Task: Integrate vthinsel/GT7Tracks into the v3 track system, with optimization targets

Repo: GT7 Race Engineer. Build on the existing v3 track pipeline; don't create a parallel one.
- Read first: `scripts/track-tool.py`, `backend/app/track_model.py`, `track_fusion.py`, `track_overlap.py`, `track_recognition.py`, `track_catalogue.py`, `track_bundle.py`, and `scripts/evaluate-track-recognition.py`.
- Keep the layout IDs in `backend/app/data/tracks.json`.
- Earlier project rules still apply: truthful labelling, no network at runtime, and bounded work outside the receive loop.

## 1. What the source contains (verified at commit `905f5efd5def1793bc1d7ec2fd87257904b51408`)
- **Licence**: MIT (the copyright line is an unfilled template). Attribute it as "vthinsel/GT7Tracks, MIT, commit 905f5ef".
- **`dumps/<id>.csv`**: 22 raw 60 Hz telemetry drives, about 207k rows, 34 MB. Filenames are GT7 course IDs from ddm999/gt7info, the **same IDs as our `tracks.json`**; all 22 exist in our catalogue: 95, 119, 154, 346, 358, 365, 439, 470, 602, 790–795, 846, 1224, 1225, 1226, 1231, 1232, 1233.
- **Columns**: `track_id,x,z,y,speed,rpm,orientation,rotation_x,rotation_z,rotation_y`.
  - **Trap:** the order is x, **z**, y. Column `z` is the horizontal world z; column `y` is **elevation** (for example Alsace 62–119 m).
  - Rows contain consecutive duplicates (repeated packets) and stationary periods.
- **`track_list.csv`**: a snapshot of ddm999 `course.csv` with ID, Length, IsReverse, NumCorners, LongestStraight, ElevationDiff, PitLaneDelta, and more.
  - Row 1225 has a corrupted name. **Join by ID only; never use their names.**
  - Check gt7info's licence before shipping any of its values. If it's unclear, use it only as build-time validation.
- **`gt7.model`** (Keras): classifies from a single point (7 inputs → softmax over 22 tracks), with no temporal memory. **Don't port it or add TensorFlow, pandas, sklearn or matplotlib.** Our HMM recognizer supersedes it. Say this in the docs.

**Why it's worth adding:**
- (a) Real **elevation** for 22 layouts; the current bundle has none.
- (b) World-frame geometry for the Lago Maggiore East End / Centre variants (790, 791, 793, 795), currently unavailable because of source quality flags.
- (c) A second independent source to cross-check existing models.
- (d) Real drives to use as an evaluation set.

## 2. Build pipeline (in `scripts/track-tool.py`; never imported at runtime)
- **Commands**:
  - `refresh --source gt7tracks`: download the pinned commit (zip or raw files) into `data/reference-research/gt7tracks/` (gitignored), with a per-file sha256 in the manifest and a 64 MB size cap. **Never commit the CSVs.**
  - `build` consumes every cached source.
  - `report` lists the source of each layout.
- **Parse** with the stdlib `csv` module, streaming, keeping `x, z, y, speed`:
  1. Drop consecutive duplicate rows and rows with speed < 1 m/s.
  2. Reject non-finite values and jumps over 50 m between rows.
- **Segment laps**: a lap is complete when the car returns within 30 m of an anchor after covering at least 90% of the catalogue length, with continuous heading.
  - Use the existing model's start/finish line as the anchor when one exists.
  - Discard the opening partial lap, pit/garage segments (off the existing centreline by more than 25 m) and laps whose length differs from the catalogue by more than 3%.
  - Log lap counts per file.
- **Build models**:
  - Resample to 2 m as `[x, elevation, z]`.
  - Use `build_model`, then `fuse_laps` with any existing laps for that layout.
  - Reverse layouts use their own dumps (439, 602, 790, 791, 794, 1225, 1231, 1233); don't derive them.
- **Merge policy** per layout, in precedence order:
  1. user;
  2. surveyed edges and corners;
  3. fused world geometry from all captures.

  Before fusing a GT7Tracks lap with an existing jbhoorasingh/zetetos model, require a median distance of 8 m or less and a p95 of 20 m or less.
  - If it fails, don't fuse. Keep the better-closing source and record `conflict` in the coverage report with both numbers.
  - Provenance lists every contributing source, with its commit and laps used.
- **Elevation**:
  - Take elevation from the GT7Tracks laps: median per 2 m bin, then light smoothing (5-bin window).
  - Transfer elevation to sibling layouts at the same venue (the Lago Maggiore and Alsace variants) wherever their centreline lies within 5 m of an elevated model. Mark it `elevation_source: transferred`.
  - Elsewhere, elevation stays null.
- **Catalogue checks** (warnings only; never auto-correct):
  - model length vs catalogue Length;
  - elevation range vs ElevationDiff (within 15%);
  - auto-corner count vs NumCorners (report the difference).
  - If the licence allows, store `PitLaneDelta` as `catalogue_pit_lane_delta_s` for Strategy, labelled as a catalogue default the user can override.
- **Build-time precompute**: compute `track_overlap` discriminating intervals and equivalence classes at build time and store them in the bundle. Don't compute them at app startup.

## 3. Optimization requirements (measure before and after; record in `docs/track-perf.json`)
Take a baseline first: bundle size, cold load time, models' RSS, recognizer update p50/p95, and first map render. Then work toward these targets.

- **Bundle** (currently about 7.9 MB gzipped): at most 4 MB gzipped after adding GT7Tracks.
  - Store centrelines as packed little-endian int32 decimetres, delta-encoded, base64 in JSON (or a sibling `.bin`).
  - Store elevation as int16 decimetres with a null sentinel.
  - Store no derivable fields (heading and curvature are computed at load; indexes are built at load).
  - Round survey edges to 0.1 m.
  - Round-trip test: decoded equals source within 0.05 m.
- **Load**:
  - The recognizer loads only the coarse data: the 25 m cell index plus centrelines decimated to 10 m.
  - Full 2 m models load lazily when a layout is locked or selected. Keep an LRU of 4 full models.
  - Budgets: added startup time ≤ 300 ms (x86 measured; ARM64 estimate labelled), and total model RAM ≤ 40 MB.
- **Recognition**:
  - The elevation emission term is O(1) per candidate, used only when both elevations are known (σ≈3 m).
  - Update p95 ≤ 2 ms at 5 Hz across all layouts.
  - Zero allocations in the hot loop: preallocated arrays, no per-sample dict building.
  - Never runs in the receive loop.
- **API/Frontend**:
  - Serve models with an ETag equal to the model revision and `Cache-Control` for immutable bundle models.
  - Serve LOD polylines (Douglas–Peucker, ≤1500 points per level), computed once per revision and cached.
  - The elevation strip uses ≤ 400 points.
- **Build**: `track-tool.py build` must complete in under 60 s on the dev PC, processing the CSVs by streaming (peak RSS under 500 MB).
- **Dependencies**: no new runtime dependencies. Build-time stays stdlib (numpy only if it's already a dependency).

## 4. Evaluation (extend `scripts/evaluate-track-recognition.py`)
- Replay each GT7Tracks dump as a real telemetry trace through `TrackRecognizer`, starting at the file start and at 5 random offsets.
- **Leave-source-out:** when evaluating a layout's dump, build that layout's model **without** the GT7Tracks laps. Never test on training data. Report both variants: with GT7Tracks included, and held out.
- **Report**:
  - per-layout lock accuracy, false locks, and median/p95 time and distance to lock;
  - reverse confusions, and lock distance with vs without the elevation term.
- **Acceptance**:
  - zero false locks and zero reverse confusions;
  - lock distance with elevation no worse than without it;
  - at least 95% of the 22 layouts lock within 1 km in the held-out setting (documented equivalence classes excepted).
- Output `docs/recognition-eval.json` plus a summary table in `docs/TRACKS.md`.

## 5. Tests
- **Parser**: the column-order trap (y is elevation), duplicate/stationary removal, jump rejection, a corrupted name ignored.
- **Laps**: segmentation, partial/pit rejection, the length gate.
- **Merge**: fusion gate pass/fail, conflict reported, provenance lists both sources, precedence order.
- **Elevation**: transfer within 5 m only, null elsewhere.
- **Packed encoding**: round trip, size, null sentinel.
- **Loading**: lazy load plus LRU eviction; the recognizer works with coarse data only.
- **Bundle**: sha256 mismatch aborts `build`; the bundle is reproducible (same inputs give a byte-identical bundle).
- **Performance guards**: bundle size ≤ 4 MB, update p95 budget.
- Keep all existing suites green.

## 6. Docs and credit
- `THIRD_PARTY_NOTICES.md` plus `docs/licenses/gt7tracks-MIT.txt`, and gt7info only if its values are shipped.
- README credits line.
- `docs/TRACK_REFERENCE_COVERAGE.md` regenerated with a `sources` column and conflicts.
- `docs/TRACKS.md`: what GT7Tracks contributes, and why its Keras model isn't used.

## 7. Final report
- Files changed.
- Layouts newly covered, and layouts that gained elevation (direct vs transferred).
- Conflicts found.
- Before/after performance table, from measured numbers only.
- Evaluation results for both variants.
- Anything unverified (ARM64 timings, live PS5 check of the elevation frame).
