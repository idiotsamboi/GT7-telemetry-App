---
paths:
  - "backend/app/storage/**"
  - "backend/migrations/**"
---
# database
- Additive migrations only, numbered, idempotent, with a migration test. Never scan tables per packet. Never delete telemetry on career reset.
