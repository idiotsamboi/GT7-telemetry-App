# 0008. Hash routing and the frontend domain layer

Status: accepted (the routing half belongs to the UI redesign, referenced here)

## Context
Nine components called `fetch(` directly, built URLs, and interpreted error bodies themselves. Services
and permissions had no frontend representation.

## Decision
- The redesign owns the shell, visuals and hash routing (`src/app/router.ts`, `store.ts`, `liveStore.ts`,
  `liveConnection.ts`). Navigation is view state; **services are backend-owned and never start or stop
  because of navigation** (tested in `tests/test_foundation_api.py::test_read_only_calls_never_change_service_state`).
- `frontend/src/domain/` is the data layer: `http.ts` (one fetch wrapper: same-origin cookie, JSON,
  `AppError`, abort/timeout, retry for idempotent GETs only), `api/*` clients per backend area,
  `commands.ts` (`run(id, payload) → CommandResult`), `permissions.ts`, `units.ts`, `channels*.ts`,
  domain stores (`services`, `capabilities`, `sessions`, `notifications`). `domain/` never imports React
  components; `ui/` and pages may import `domain/`.
- View state (workspace, layouts, zoom, filters) is separate and never persists domain data.
- Enforcement: `npm run check:arch` fails on a `.tsx` import inside `domain/` or any `fetch(` outside
  `domain/http.ts`; the allowlist is empty.
- Error boundaries wrap every page and panel; crashes report to `POST /api/client-errors` (rate-limited,
  redacted). OBS overlay pages keep their own boundary and never share editor state.
