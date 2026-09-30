---
paths:
  - "backend/app/telemetry/**"
  - "backend/app/sessions.py"
  - "backend/app/analytics.py"
---
# telemetry-truth
- Do not edit parser/bus without explicit need; measure with scripts/bench_ingest.py before and after.
- Unavailable GT7 fields stay UNAVAILABLE: tyre wear, compound, official pressure, penalties, flags, official validity.
