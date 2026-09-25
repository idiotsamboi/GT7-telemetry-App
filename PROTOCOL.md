# Protocol and source provenance

Primary source: https://github.com/MacManley/gt7-udp
Exact commit studied and preserved: **a768574ba809429ce0455b988794e028660f6b9b**, retrieved September 23, 2026 local time. Files: `vendor/gt7-udp/GT7UDPParser.cpp`, `GT7UDPParser.h`, `README.md`, `LICENSE`. This is an Arduino ESP library; the application ports its logic to native Python sockets and PyCryptodome (`Crypto.Cipher.Salsa20`), not an ESP bridge.

| Variant | Bytes | Heartbeat | Seed XOR |
|---|---:|---|---|
| A | 296 | A | 0xDEADBEAF |
| B | 316 | B | 0xDEADBEEF |
| Tilda | 344 | ~ | 0x55FABB4F |
| C | 368 | C | 0xDEADBEEF |

Transmit heartbeat from the bound local UDP 33740 socket to console UDP 33739 every five seconds by default. Local and console addresses are independent. Length identifies the actual received variant. No continuous probing or menu-silence fallback is attempted.

Key: first 32 ASCII bytes of `Simulator Interface Packet GT7 ver 0.0`. Seed: encrypted bytes 0x40–0x43, unsigned little endian. Nonce: `<II` encoding of `(seed XOR constant), seed`. Decrypt with Salsa20/20, require little-endian magic `0x47375330` and an exact supported length before parsing. Never use native struct alignment.

## Deliberate corrections/differences

- The header defines `PacketC : PacketTilda`; the README incorrectly shows `PacketB`. C additions begin at 344, with current timing at 348 and road-wheel angles at 352. The actual method name is `readData()`, not README `read()`.
- Reject short/unknown packets and invalid magic. Upstream does not provide these full safety checks and its checked-in read function includes a syntax typo.
- Every parse creates new values, so A cannot inherit stale C fields.
- Source ID bits are interpreted as uint32 for modular ordering, even though the C header declares signed int32. Lap counts and timing retain signed semantics; negative timing sentinels become null.
- Duplicate IDs are rejected. Forward modular deltas below 2^31 count gaps, including wraparound. Backward packets are rejected; three consecutive increasing backward IDs establish a reset and new session epoch. This is a heuristic and can confuse a sustained reordered old run; counters remain visible.
- `wheelRPS` is treated as angular rad/s, consistent with upstream multiplying radius directly. Wheel linear speed is `abs(omega * radius)`; no extra 2π. Ratios are suppressed below 10 m/s, during yaw, or when the road-plane distance check fails. Ratios do not prove tyre slip.
- Do not infer EV type solely by casting capacity. Nonpositive capacity disables fuel strategy.
- Constant oil/water temperatures do not generate overheating alarms. Pre-race position/count are raw channels, never live standings.
- C semantics are structurally parsed and recorded but C timing/surface advice is opt-in pending hardware validation. Steering/acceleration extensions remain raw; coordinate-frame-based handling diagnosis is disabled.

## Fixtures

`tests/fixtures/packets.json` contains independent synthetic encrypted fixtures for all variants. `tests/fixture_generator.py` implements scalar Salsa20 separately from the production PyCryptodome code; it is checked against a standard all-zero key/nonce Salsa20/20 vector. Expected fields use independently written explicit byte offsets. Seed bytes are overlaid in the encrypted fixture, as the wire format requires. This verifies nonce construction beyond a production encrypt/decrypt round trip.

No captured PS5 datagrams were provided. C++ layout inspection and independent cipher tests are not proof of live GT7 compatibility. Preserve permitted real captures with game version, provenance and known displayed readings before promoting extended interpretations to validated.

## Parser/receiver hardening, September 24

Parser version 1.1 separates `decrypt_datagram` from normalized `parse`, precompiles struct readers, timestamps receipt before decoding, and produces classified `PacketError` diagnostics. Invalid datagrams do not enter session/recorder state. Raw negative timing values and signed packet-ID bits remain available alongside normalized values. Every upstream packed field offset is now checked by independently walking declarations in the preserved header.

`tests/test_udp.py` uses actual loopback sockets and independently encrypted datagrams, exercising the same receiver path as the console. It verifies heartbeats from the configured receive socket, mixed actual variants, malformed lengths/magic, duplicates/reordering/gaps, recording, settings-driven reconnect and continued operation after an injected unexpected parser exception. This is still an emulated console, not a live PS5 capture.

Windows receivers use exclusive socket binding rather than SO_REUSEADDR. Port conflicts are reported with owner PIDs and names where permissions allow. It is not safe to silently steal/share another telemetry app's port. IPv4 console/bind settings are validated explicitly. Console/UDP setting changes now reopen the receiver immediately; no variant probing is performed during a working session.
