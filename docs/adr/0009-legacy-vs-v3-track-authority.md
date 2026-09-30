# 0009. Legacy vs v3 track authority and migration plan

Status: accepted (plan); implementation is a follow-up milestone

## Context
Two track systems coexist: legacy `tracks.py` (`TrackMap`, `LAYOUTS`, user-captured maps in
`track-maps/`) and the v3 stack (`track_service`, `track_model`, bundle `track-models.bundle.json.gz`,
recognition/fusion/overlap, `track-models/` for user models). `Runtime` feeds both.

## Decision
The **v3 `TrackService` is the authority** for "which track/layout am I on" and for distance-along-track
(`progress_s`), gated by the `v3_track_authority` flag (default on). The legacy `TrackMap` remains the
store for user-captured maps and the UI map endpoints until those are migrated.

Plan:
1. (done) Register both in TECH_DEBT; expose both through the `track` service status.
2. Provide a migration that converts `track-maps/*` user maps into v3 user models (`track-models/`).
3. Move `/api/track-map*` routes to `TrackService` (keep URLs, change the implementation).
4. Delete `TrackMap`; `LAYOUTS` consumers move to `track_catalogue`.

## Consequences
No behaviour change now; the plan and the flag give the retirement a clear seam.
