# Automatic track memory

The tracker keeps layout IDs from the existing catalogue. It runs geometry matching and file writes in a background worker, no more than twice per second. Receiver collection is bounded to 4,096 lap points and 256 recognition samples. Up to eight completed laps wait for persistence; overload is reported.

## First visit

1. Open Live Race. Select a circuit/layout for an immediate offline reference preview, or leave it unassigned.
2. Drive past the opening partial lap, then complete a continuous lap. Pauses, source packet gaps, discontinuities, incomplete closure and oversized laps prevent saving.
3. For an unfamiliar unassigned route, use **Confirm a learned layout**, select its exact circuit/layout and save the retained lap. Reference-shape suggestions are evidence for confirmation, never authoritative identities.
4. On leaving the circuit, the current line and recognition state clear. The library and unnamed candidates remain on disk.
5. On return, a unique complete-lap match restores the named map automatically. Partial/shared sections show candidates without selecting. Same-length variants and geometrically indistinguishable learned routes require confirmation. Reverse layouts are separate IDs and direction is checked.

Manual selection remains available. The last configured track is only a startup hint. The opening partial lap is deliberately discarded, so automatic recognition can take a full lap after the first start/finish crossing.

## Reference and learned lines

Toggle **Reference outline** and **Learned line** independently. Green/red live segments still show gaining/losing reference delta. Dotted purple references are approximate driven-route outlines, not track limits. Unaligned references are shown separately; cars are never positioned on an unverified reference image.

Alignment allows translation, rotation and one uniform scale only. It never stretches axes or mirrors the path, and does not reverse travel order. World-space learned geometry supplies positioning. References never supply timing gaps or marshal-zone coordinates.

The bundled reference coverage report lists all 122 catalogue layouts. 101 have reviewed outlines; 21 are unavailable or excluded for source quality. Everything works offline after installation. The source is ordered open reference data, rather than guessed pixel tracing. See [coverage and provenance](TRACK_REFERENCE_COVERAGE.md).

## Map history and Race Control

Maps are atomically replaced only after successful writing and synchronization. Eight previous distinct revisions are retained. Use **Restore previous map** to restore one; the replaced revision remains in history. Existing legacy map JSON is upgraded without deleting points or layout IDs. Legacy/imported geometry is not considered continuous until geometry checks pass.

Choose the event layout when creating a group. Race Control and the OBS map graphic use the same versioned model as the race viewer. **Use saved layout map** explicitly adopts it when a group has a manually supplied map. A running session freezes its map and marshal zones. New library revisions queue until the next session starts; changing the approved geometry clears old zone definitions. Demo league maps remain synthetic and do not alter the live library.

Demo/replay laps cannot overwrite live saved maps. Unknown layouts, gaps and failed writes retain the previous valid map. Save errors appear in the circuit panel.

## Local API

All endpoints retain local administration authentication; they are not exposed by the group listener.

- `GET /api/track-map`: status, candidates, reference, alignment, revision and previous revisions.
- `GET /api/track-map/library`: saved layout and reference coverage metadata.
- `POST /api/track-map/select`: `{ "layout_id": "10" }`; empty ID resumes automatic recognition.
- `POST /api/track-map/confirm`: `{ "candidate_id": "…", "layout_id": "10" }`.
- `POST /api/track-map/restore`: `{ "layout_id": "10", "revision": "…" }`.
- `PUT /api/track-map`: existing world-space JSON import remains supported.

Maps live under the application data directory in `track-maps/`. Back up that directory to retain personal learned geometry and candidates. Static references are packaged under `backend/app/data/track-references.json`.

## Validation scope

Automated tests cover repeat visits/restarts, unnamed candidate confirmation, shared and reverse geometry, ambiguity, packet gaps, failed writes, atomic history restoration, legacy migration, source isolation, reference alignment and group revision freezing. Synthetic tests are not claims of PS5 hardware validation or official track identity verification. The geometry microbenchmark in `track-memory-benchmark.json` is separate from the pending full race-host/OBS workload benchmark.
