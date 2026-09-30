---
paths:
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
---
# frontend
- Use src/domain api clients/stores; no raw fetch. `npm run check:arch` must pass. Reuse the existing live store; no second WebSocket.
