# Race Control development preview

This source build adds a Race Control workspace. The already-running PS5 receiver was left untouched during development; the backend additions load on the next normal application restart. It is **not yet the completed broadcast release** and the existing downloadable beta packages do not include it.

## Current workflow

1. Open **Race Control**. Create a league, select it, and create an event.
2. Enter the exact allowed browser origins (for example `http://192.168.1.20:8090,http://127.0.0.1:8090`). Enable the group listener deliberately. Port 8090 exposes the group surface, not the local settings or maintenance API.
3. Choose host-only to suspend local telemetry and microphone acquisition without changing saved settings. Leave this unchecked when the host is also driving.
4. Issue driver or spectator invitations and copy them when shown. Admitted members have separate credentials; revoking an invitation does not revoke existing members. Remove a participant to revoke their access.
5. Drivers use **Group Connection** in their installed app, enter the host address and invitation, and select accepted sharing categories. Hosts approve pending members. Spectators open the host's `/group` page and use a spectator invitation.
6. Start an application session. Session buttons do not start or control a GT7 race. The table is labelled connected-group timing; supplied telemetry is not identity verification.
7. Issue global flags or public messages. Instructions are individually cancellable. Driver message acknowledgements are separate from delivery receipts.
8. Create a Broadcast Studio workspace. Add graphics, choose primary/comparison entries, and arrange their coordinates and sizes on the 1920 x 1080 canvas. Save draft does not affect program; **Take to program** publishes the draft.
9. Issue an OBS output URL. Keep the entire URL, including its fragment, private. Add it as a Browser Source at 1920 x 1080 and 30 FPS. The output is transparent, read-only and contains no local application controls. Keep the fragment intact so refresh/reopen can authenticate again.
10. End the session and explicitly confirm final results. Current classification is provisional and spatial/race-result validation is still in progress.

## Implemented renderer templates

Timing tower, session bar, flag banner, race-control message, driver lower third, selected-car telemetry, head-to-head comparison, track map, grid/results panel, and league/event slate share Formula and Endurance styling. Unavailable telemetry is labelled; no speed, fuel or gap is invented. The composite uses one subscription.

## Data and network boundaries

Group publication defaults to basic timing, identities and positions. Detailed telemetry, fuel and strategy require opt-in. Host administration remains protected by the application's existing local pairing credential. The public listener uses hashed invitation/member/output credentials, explicit browser origins, short-lived subscription tickets, separate authenticated native publishing, bounded native frames and rate limits.

Use LAN access only on a trusted network. Remote use requires a user-managed secure network or HTTPS/WSS reverse proxy with WebSocket upgrades. There is no relay or account service. The app does not configure router forwarding or TLS automatically.

Relevant design references: [OWASP WebSocket security](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html), [OWASP file uploads](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html), and [OBS Browser Source](https://obsproject.com/kb/browser-source).

## Validation and remaining release work

The full Python suite passed previously; the latest validation is recorded below. Thirteen focused group tests currently pass, including admission, local/public API separation, identity binding, invitation revocation independence, publication filtering, workspace access, preview/program separation, storage-failure handling and browser/native handshakes. Production frontend build passes. An isolated Chrome flow verifies league/group/workspace creation, all ten renderers, preview/Take separation, a transparent scoped overlay and refresh authentication. This is browser validation, not an OBS hardware benchmark.

Not yet release-validated: actual OBS rendering/refresh, complete synthetic multi-member flow, final timing/crossing-history correctness, durable reconnect cursors, saved client reconnection, all branding/import/export controls, synchronized archive replay, connection pressure limits, release packaging, Dell benchmarks at 4/8/16 members and the two-hour 16-member soak. No CPU, memory, recording-loss or sub-250ms latency claim is made. Group archive version 2 is not implemented yet; existing single-driver version-1 archives remain supported.

The development UI currently exposes a subset of the backend controls. Zone creation/editing, roster reassignment, full branding editing, broadcaster workspace sharing and replay controls need further UI integration. Existing zones, selected-entry stewarding, scoped instructions, targeted messages and receipts are available in the Race director panel. Do not treat API scaffolding as finished release functionality.

## League demo and OBS rehearsal

Open **Race Control → Start league demo** and choose **4, 8 or 16 drivers**. A new branded synthetic league is created with PRO/AM classes, a generated circuit, two marshal zones and a ten-layer broadcast workspace. Six layers are enabled initially; the flag layer stays visually empty until an instruction is active. No invitation, console connection or LAN listener is needed to use the local demo. An existing active group must be closed first; the demo does not overwrite it or change PS5/audio settings.

Use **Pause/Resume**, **1×/2×/4×**, and **Simulate driver disconnect** to test the dashboard. Pausing stops fresh telemetry, so entries become stale after the normal two-second threshold. Click a timing-table driver to inspect fields and issue entry-specific instructions. Choose a marshal zone for local flags. Send a message and use **Simulate selected driver's acknowledgement** to exercise delivered/displayed/acknowledged states. These controls act only on synthetic members. Stopping closes the demo event; its saved league/event records remain available.

The studio now provides:

- Side-by-side draft and permission-filtered program monitors, including the effective broadcast delay.
- Drag-to-position graphics, editable dimensions, layer visibility, popup durations and shared or locked driver selections.
- Formula and Endurance presets, fastest-lap purple, pedal colors, and existing transparent car cutouts.
- **Save draft**, atomic **Take to program**, and **Clear program now**, which hides the output without erasing the draft.
- Scoped URLs for the complete 1920 × 1080 scene or one selected graphic. Set an individual OBS Browser Source to the displayed graphic dimensions.

To rehearse in OBS, enable hosting with an allowed loopback origin such as `http://127.0.0.1:8090`, issue an output URL, and paste the entire URL into OBS Browser Source. Use 30 FPS. Keep the `#access=...` fragment; it authenticates refresh/reopen without putting the secret in the HTTP request URL. An individual output also includes `&graphic=...` in that fragment. URLs remain private credentials. Each source uses one subscription.

Chrome validation covers the multi-car rehearsal, flags, acknowledgement receipts, disconnect/reconnect, pause/resume, transparent composite output, individual output refresh, and clearing program while preserving preview. This is not a claim of OBS rendering performance or completion of the two-hour soak.

Delayed program revisions are retained in bounded history, so a Take does not blank an existing delayed scene before its effective time. Demo map geometry and laps are synthetic and are not evidence of a real GT7 track or result.
