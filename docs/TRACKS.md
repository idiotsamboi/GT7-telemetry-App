# GT7Tracks integration

**Source**: vthinsel/GT7Tracks, MIT (the repository's copyright line is an unfilled
`[year] [fullname]` template), pinned at commit `905f5efd5def1793bc1d7ec2fd87257904b51408`.
License copy: `docs/licenses/gt7tracks-MIT.txt`. Refresh with
`python scripts/track-tool.py refresh --source gt7tracks`, then
`python scripts/track-tool.py build`.

## What it contributes

- **Real elevation** for the 22 captured layouts, taken as the median-per-2m-bin of each
  driven lap's `y` column, lightly smoothed over a 5-bin window. Previously every model
  in the bundle had null elevation except where a surveyed edge happened to touch it.
- **Three layouts previously uncovered** (flagged `catalog_length_disagrees` /
  `length_from_catalog` against the other source, or with no exact name match) are now
  built directly from these captures: **790** (Lago Maggiore East End Reverse), **795**
  (Lago Maggiore East End), **846** (Red Bull Ring Short Track).
- **Elevation transfer** to sibling layouts at the same venue (Lago Maggiore, Alsace)
  whose centreline lies within 5m of an elevated model — the shared sections of a venue's
  variants pick up real elevation even when that specific variant has no direct capture.
- **A cross-check** against the existing jbhoorasingh/gt7-datalogger-track-data geometry:
  every fusion is gated at median ≤ 8m / p95 ≤ 20m fit distance before the centreline is
  refined; a failing fit is recorded as a conflict and the existing (better-closing)
  source is kept untouched (see `docs/TRACK_WORLD_COVERAGE.md`).

## Why `gt7.model` (the bundled Keras classifier) is not used

GT7Tracks ships a trained Keras model (`gt7.model/`) that classifies which of its 22
tracks a *single telemetry point* belongs to (7 inputs → softmax over 22 classes), with
no temporal memory between calls. This project's own `TrackRecognizer`
(`backend/app/track_recognition.py`) already supersedes that approach for every purpose
this app needs:

- it is a bounded Viterbi recognizer with actual temporal state (particles carried
  frame-to-frame), not a single-point classifier;
- it covers all 122 catalogue layouts, not 22;
- it already has an O(1)-per-candidate elevation emission term (σ≈3m) for exactly this
  kind of data, used only when both elevations are known;
- it runs with zero new runtime dependencies. Porting `gt7.model` would require adding
  TensorFlow (or a Keras-compatible runtime), which this project's build-time-only,
  stdlib-first policy for the track pipeline explicitly rules out.

`gt7.model` and the training scripts (`LearnTracks.py`, `GT7TrackGuess.py`) are read for
context only; nothing from them is ported, and no TensorFlow/pandas/scikit-learn/
matplotlib dependency was added anywhere in this repository.

## Known gaps in this pass

- **95 (Nürburgring Nordschleife)**: its capture (~9.4 minutes at 60Hz) never returns
  within 30m of its own starting point after covering 90% of the 20.8km catalogue
  length, so no lap closes. This looks like a genuinely partial capture rather than a
  bug — the Nordschleife lap time for the car in this dump likely exceeds the recording
  window. Left uncovered this pass.
- **791 / 793 (Lago Maggiore Centre / Centre Reverse)**: each dump contains several laps'
  worth of driven distance, but the one lap that returns near its own start point
  overshoots the catalogue length for that specific short variant by more than the
  segmentation's length gate allows. The East End variants (790/795, same venue, longer
  layout) integrated cleanly from the same venue's captures. Left uncovered this pass;
  worth a closer look at anchor placement for the short "Centre" cut specifically.
- **track_list.csv** (bundled in the GT7Tracks repo, itself a snapshot of ddm999/gt7info's
  `course.csv`) is downloaded and checksummed by `refresh --source gt7tracks` but is
  **not parsed or shipped** in this pass — gt7info's own licence for that table wasn't
  confirmed, so nothing from it (including `PitLaneDelta`) is surfaced as a value here,
  per this project's licence-caution default.
- The bundle-size/lazy-load/LOD/ETag optimization work (packed int32/int16 encoding,
  LRU full-model loading, recognizer-loads-coarse-only, Douglas-Peucker LOD polylines,
  the `docs/track-perf.json` before/after measurement) was **not attempted** this pass —
  see the session summary for why.
