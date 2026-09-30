# Rule: Performance & Resource Constraints
- Telemetry packet receiving loop must never block on disk or database I/O.
- Measure baseline CPU/RAM and disk latency before and after major changes.
