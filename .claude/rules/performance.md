---
paths:
  - "backend/app/telemetry/**"
  - "backend/app/gamification/**"
  - "backend/app/runtime.py"
---
# performance
- No unbounded queries or scans per packet. Bounded, async, incremental. Measure before/after; never claim gains without numbers.
