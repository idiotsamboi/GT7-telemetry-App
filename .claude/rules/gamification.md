---
paths:
  - "backend/app/gamification/**"
  - "frontend/src/career/**"
  - "tests/test_gamification*"
---
# gamification
- Every XP event: source event, evidence, timestamp, driver, reason, formula, confidence, source mode.
- Deterministic event IDs; processing twice is a no-op. Replay/demo/synthetic never award live career XP.
- Gamification failure is non-fatal and retryable. Everything behind feature flags + settings. No core feature gated by progression.
