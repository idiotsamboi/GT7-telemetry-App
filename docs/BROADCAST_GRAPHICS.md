# Broadcast graphics

The source app provides **28 graphic types**. Style presets share these renderers and are not counted as extra graphics. A workspace remains bounded to 20 layers; use separate workspaces when you need more templates.

## Using the studio

1. Create an event or start **Race Control → Start rehearsal demo**.
2. Open **Studio → Edit**, create/select a workspace, and expand **Add a graphic**.
3. Set the primary driver and comparison A/B slots. Team roster follows the selected driver’s team.
4. Arrange the draft and choose **Take to program**. Moving between Studio tabs keeps unsaved draft edits. Switching away from Studio or reloading still requires saving your draft first.
5. In **Studio → Deliver**, enable the group listener with the correct allowed origins. Return to Edit to issue individual graphic URLs, or expand **Composite output** for one shared scene.
6. Add the full URL to an OBS Browser Source. Individual outputs use each graphic’s recommended size; composite uses 1920 × 1080. Use 30 FPS. Refresh/reopen and changing the graphic fragment are supported.

## Available graphics

| Graphic | Recommended size | Required sharing |
|---|---|---|
| Timing tower | 440 × 850 | basic |
| Session bar | 1200 × 100 | basic |
| Flag banner | 1000 × 130 | basic |
| Race-control message | 1100 × 160 | basic |
| Driver lower third | 900 × 210 | basic |
| Selected-car telemetry | 620 × 260 | telemetry |
| Head-to-head comparison | 1000 × 300 | basic |
| Track map | 600 × 600 | basic |
| Grid/results panel | 1200 × 850 | basic |
| League/event slate | 1920 × 1080 | basic |
| Fastest lap announcement | 900 × 160 | basic |
| Class leader panel | 680 × 460 | basic |
| Penalty / investigation notice | 1000 × 160 | basic |
| Podium | 900 × 620 | basic |
| Sponsor rotation | 700 × 220 | basic |
| Fuel level | 420 × 220 | fuel |
| Tyre temperatures | 420 × 320 | telemetry |
| Pit board | 700 × 220 | basic |
| Starting soon slate | 1920 × 1080 | basic |
| Session clock | 420 × 180 | basic |
| Classification strip | 1824 × 180 | basic |
| Team roster | 700 × 500 | basic |
| Lap-time board | 800 × 520 | basic |
| Speed comparison | 1000 × 300 | telemetry |
| Connection status | 700 × 500 | basic |
| Event information | 780 × 440 | basic |
| Battle tag | 500 × 120 | basic |
| Projected order after stops (net order) | 800 × 640 | fuel + strategy |

## Data and presentation

- Classification strip and class leaders require usable positions. They do not invent positions for unclassified entries.
- Lap-time board distinguishes reported last laps from application-quality best laps. It does not claim official validity. Purple marks the displayed field’s fastest usable best, green marks personal bests, yellow marks other last laps.
- Speed comparison requires public telemetry sharing and fresh values for A/B. Missing/private/stale values display unavailable; the comparison is not a time gap.
- Fuel level requires fuel sharing. It displays reported litres and a capacity percentage, not an invented range prediction. Tyre temperatures are reported surface temperatures.
- Connection status reports freshness for registered connected-group entries, not internet health or anti-cheat verification.
- Pit board is a host-entered instruction. It no longer assumes BOX BOX without host text.
- Event information uses host-entered format/distance and current connected-group state. Session clock uses the delayed server timeline and freezes at the session end.
- Private steward decisions stay private. Penalty graphics show only public decisions. Reference-map controls never appear in OBS output.
- Battle tag shows a desk-focused battle's heat/gap/closing rate; it needs only basic sharing (position/lap data), but the underlying battle detection itself is desk/broadcast context only - a driver's own app never receives it.
- Net order (projected order after stops) needs both `fuel` and `strategy` sharing, never a raw fuel litre for anyone but yourself - only rank, stop count, net gap, uncertainty and pit window per entry.
- Live/demo/replay provenance, publication filtering and broadcast delay remain server-controlled. No graphic opens an additional GT7 receiver.

## Review and validation

The current-change review fixed red-flag precedence in Race Control, unsaved Studio tab switching, stale per-workspace OBS URL display, overlay fragment switching, malformed graphic settings, misleading fuel-range wording, missing penalty status handling and tyre-array handling. The backend rejects non-text titles, invalid row counts, invalid opacity and unknown settings before publication.

Tests cover the full Python regression suite, original composite/individual outputs, expanded graphics, sharing changes, refresh and fragment switching. Browser-source verification uses Chrome; testing inside OBS itself and a long hardware soak remain separate. Existing packaged installers are not rebuilt by a frontend build.
