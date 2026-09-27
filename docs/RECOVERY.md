# Recovery and avoiding stuck states

Use **Recovery** in the header, the dashboard error fallback, or open `/recovery` at the same address as your app. The recovery page has independent HTML/JavaScript and does not depend on the React bundle. Local pairing remains automatic; remote recovery still requires the administration token. Group/spectator listeners cannot access recovery actions.

- **Return to PS5 / leave host-only mode** exits local demo/replay and re-arms recording. It keeps the group event/listener open.
- **Restore full dashboard** restores hidden panels and the normal refresh rate.
- **Restore UDP connection defaults** retains the PS5 address and restores automatic bind, standard ports, variant A and a one-second heartbeat.
- **Reset audio to system defaults** stops capture, selects default devices, enables speakers at 80%, and leaves hands-free off until you enable it.

Recovery retains sessions, maps, league history, assets and credentials. It does not fix an incorrect PS5 IP, missing model/runtime installation, operating-system permissions, a full disk or another process owning the network port.

Malformed settings are preserved in a timestamped `settings.invalid-*.json` backup and safe defaults allow startup. The normal UI reports that recovery. Settings changes cannot remove access from the running loopback origin.

Group sessions can always be closed without finalizing. Use **Unlock joining** to undo join locking; **Exit group replay** restores live output. Disabling host-only hosting re-arms local recording. Invalid hosting edits are validated before shutting down the existing listener. In Broadcast Studio, **Discard unsaved changes** restores the saved draft, and **Reset graphic placement** returns a selected graphic to its standard dimensions/location. Clear program remains reversible by taking the draft again.

A lost browser connection shows a reconnect banner. Rendering failures offer recovery/reload instead of a blank page. Hold-to-talk captures the pointer, so releasing outside the button stops capture.

Validation covers local authentication/origin protection, invalid settings, recovery actions, preserved database files, invalid hosting edits, host-only exit and idempotent demo stopping. This is a targeted recovery audit, not a guarantee against every hardware or OS failure.
