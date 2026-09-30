# Driver Career repository map

Checkpoint: 2026-09-30. Current source is authoritative; the checkout contains substantial prior uncommitted changes. Do not stage or overwrite unrelated work.

| Path | Type / subsystem | Purpose / principal symbols | Dependencies / tests |
|---|---|---|---|
| backend/app/sessions.py | Python / recording | Sessions.start, close_lap, end; persisted comparable-lap summaries; discrete lifecycle events | analytics.Accumulator, Store; tests/test_reliability.py |
| backend/app/storage/store.py | Python / persistence | Store: bounded single writer queue; query, flush, health | storage.schema; tests/test_storage_repositories.py |
| backend/app/storage/schema.py | Python / migration | migrate, SCHEMA_VERSION; inline schema mirrors SQL | backend/migrations; tests/test_storage_migrations.py |
| backend/app/storage/repositories.py | Python / repository | SqliteSessionRepository; paginated metadata and summaries | Store; tests/test_storage_repositories.py |
| backend/app/runtime.py | Python / orchestration | Runtime._wire_bus, start, close, close_spatial_lap | existing TelemetryBus, Sessions, TrackService; tests/test_runtime_foundation.py |
| backend/app/telemetry/bus.py | Python / events | subscribe_events, emit; fault-isolated discrete events | tests/test_telemetry_bus.py |
| backend/app/analytics.py | Python / analysis | lap_statistics, improvements, Accumulator | tests/test_analytics.py |
| backend/app/domain/training_defs.py | Python / training | pure registered evaluators, Challenge, Achievement | tests/test_domain_insights_training.py |
| backend/app/track_service.py | Python / track | locked_layout_id, snapshot; authoritative v3 resolution | tests/test_track_service.py |
| backend/app/spatial_coaching.py | Python / coaching | corner_report: calculated distance-aligned observations | tests/test_spatial_coaching.py |
| backend/app/engineer_service.py | Python / engineer | RuntimeEngineer; existing validation and speech arbitration | tests/test_modules_engineer.py |
| backend/app/core/features.py | Python / feature flags | FEATURES, is_enabled | Settings.feature_flags; tests/test_foundation_api.py |
| backend/app/api.py | Python / HTTP | create_app; authenticated local API, single /ws | tests/test_api.py |
| frontend/src/app/router.ts | TypeScript / navigation | useRoute, navigate; hash-based Driver workspace | frontend/scripts/check-arch.mjs |
| frontend/src/domain/http.ts | TypeScript / transport | typed get/post adapters | existing pairing/security |
| frontend/src/domain/stores | TypeScript / state | existing bounded domain stores / live selectors | frontend/src/app/liveConnection.ts |
| frontend/src/main.tsx | TSX / shell | Driver navigation and page mounting | preserve existing shell |

Search exact symbols and read nearby sections. This index is intentionally compact rather than a source dump. File sizes and detailed exports can be obtained mechanically when needed.

## Validation commands

- Backend: `.venv/Scripts/python.exe -m pytest <test paths> -q`
- Frontend contracts: `cd frontend; npx tsc -b`
- Frontend architecture: `cd frontend; npm run check:arch`
- Frontend build: `cd frontend; npm run build`
- Generated contracts: `.venv/Scripts/python.exe scripts/gen-contracts.py` (inspect help/source before changes).
- Existing ingestion benchmark: `scripts/bench_ingest.py` (use its documented arguments).
