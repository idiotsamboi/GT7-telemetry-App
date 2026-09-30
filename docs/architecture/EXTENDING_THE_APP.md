# Extending the app

One recipe per task: Files, Snippet, Test, Regenerate/verify. Snippets were run against the current APIs in a scratch
process (derived engine, dispatcher, protocol registry, graphics registry, permissions, training definitions, migrations, rules,
analysis cache, exports, intents, services, bus) or type-checked with the frontend `tsc` (recipes 3 and 6). Three pieces are
shape-only and were not executed: the parser/`_META` rows in recipe 1 (no free wire bytes to place a real field), the transport branch
in `public.py` (recipe 5) and the `Runtime.execute` handler (recipe 13). The example ids (`coasting`, `pit_window`, ...) are
illustrations, not features that exist. "Pinned tests" lists existing tests that assert the
current contents of a registry and must be edited in the same change.

Conventions used below:

```
PY   = .venv/Scripts/python.exe
PYT  = .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=<writable dir>
GEN  = .venv/Scripts/python.exe scripts/gen-contracts.py         # then add --check to verify
```

`gen-contracts.py` rewrites `docs/architecture/CONTRACTS.md` and `frontend/src/domain/{channels,commands,capabilities,graphics}.generated.ts`.
`tests/test_contracts_fresh.py` fails when they are stale. Never edit generated files by hand.

## 1. New telemetry channel

Decide first whether the value is on the wire or computed. Computed values belong in a derived channel (recipe 2).

Files

- `backend/app/telemetry/parser.py` `FIELDS`: `(name, offset, struct_format, units, first_variant)`; `_LAYOUT` and `CAPABILITIES` follow.
- `backend/app/telemetry/frame.py` `_META[name]`: `(label, group, canonical_unit, formatter, color_role, sampling)`. Add the name to
  `EXPERIMENTAL` if it is undocumented or unverified, so it is labelled and gated.
- `DATA_FIELDS.md`: one row `| name | 0xOFFSET | \`fmt\` | units / caution | variant |`.
- `backend/app/telemetry/parser.py` `demo_sample` and `tests/fixture_generator.py` if tests need a value in the bytes.

The four known variants (296, 316, 344, 368 bytes) are mapped except the magic, the Salsa20 seed at 0x40 and one pad byte,
so a new wire field normally means a new variant (`LENGTHS`, `XOR`) as well.

Snippet

```python
# parser.py FIELDS (shape only: 'example_gauge' is hypothetical)
('example_gauge', 372, 'f', 'bar', 'D'),
# frame.py _META
'example_gauge': ('Example gauge', 'engine', 'bar', 'number:2', None, 'ui'),
# frame.py, only if unverified upstream
EXPERIMENTAL = frozenset({..., 'example_gauge'})
```

A value the parser itself normalises (like `speed_kmh`) is set in `parse()` and registered in `_NORMALIZED` in `frame.py` with
the tuple `(name, group, unit, source, formatter, color_role, sampling, note)`.

Test: `tests/test_telemetry_frame.py::test_every_field_registered` covers registration for every `FIELDS` row and the variant. Add a
decode assertion against `tests/fixtures/packets.json` (regenerate with `python tests/fixture_generator.py` only if the fixture
bytes change).

Regenerate/verify: `GEN`, `PYT tests/test_telemetry_frame.py tests/test_udp.py tests/test_contracts_fresh.py`,
`PY scripts/gen-contracts.py --check`.

## 2. New derived metric

Files: `backend/app/telemetry/derived.py` (a function plus one `add(...)` call inside `_register()`).

Contract: `compute(frame, state) -> value` is pure given `state`; `depends_on` ids missing (None) in `frame.values` give `None`
without calling it; `valid_when(frame)` false gives `None`; an exception gives `None` and is counted in `engine.errors`.
State is per channel per `DerivedEngine`; give a stateful channel a `DerivedState` subclass through `state=`.

Snippet

```python
def _coasting(frame: TelemetryFrame, state: Any) -> bool:
    v = frame.values
    return v['throttle'] < 0.05 and v['brake'] < 0.05 and v['speed_kmh'] > 60


# inside _register(), after the existing add(...) calls
add('coasting', 'Coasting', 'controls', 'bool', 'none', ('throttle', 'brake', 'speed_kmh'), _coasting,
    note='No pedal input above 60 km/h')
```

Argument order of `add`: `id, name, group, unit, formatter, depends, compute` then keywords `color`, `min_variant`, `valid`, `note`,
`sampling` (`full|ui|lap`), `source`, `state`. Derived values live in `Runtime.derived_values` (evaluated at 20 Hz), not in
`Sample.values`.

Test

```python
def test_coasting():
    assert DerivedEngine().evaluate(demo_frame(throttle=0.0, brake=0.0, speed_kmh=100.0))['coasting'] is True
    assert DerivedEngine().evaluate(demo_frame(throttle=0.5, brake=0.0, speed_kmh=100.0))['coasting'] is False
```

Pinned: `tests/test_telemetry_derived.py::test_expected_derived_set_registered` (exact id set). Regenerate/verify: `GEN`,
`PYT tests/test_telemetry_derived.py tests/test_contracts_fresh.py`, and re-run the ingest bench if the channel is heavy
(`PERFORMANCE_BUDGETS.md`; the measured cost of the whole derived set at 20 Hz was about 39 us per evaluation).

## 3. New Pit Wall panel

State of the frontend, stated plainly: `frontend/src/domain/panels.ts` (`PANELS`) and `domain/modules.ts` (`BUILTIN`) are data
only; their own comments say the shell does not consume them yet. Today panels are mounted by hand in `frontend/src/main.tsx`
(pit wall tabs), and the component files live directly under `frontend/src/`. `frontend/src/ui/driver/` exists but is empty and is
the intended home for new panel components. `npm run check:arch` enforces that `src/domain/**` never imports a `.tsx` component and
that `fetch()` is only called from `domain/http.ts`.

Files

- Component: `frontend/src/ui/driver/FuelMargin.tsx` (default export). Read live data with `useLive` from `app/liveStore`
  (`fuel`, `sampleValues`, `session`, `health`, `receiver`, `liveAnalysis`, `liveDelta`, ...); send commands with `run()` from
  `domain/commands`; never call `fetch`.
- Registry row: `frontend/src/domain/panels.ts` `PANELS` (`component` is a string key the shell will resolve; `channels` lists the
  `/ws` slices or channel ids it reads).
- Module: add the panel id to a `panels: [...]` array in `domain/modules.ts` `BUILTIN` (or a new `ModuleDef` with `routes`, `commands`,
  `settingsSections`, optional `requires: CapabilityId`).
- Mount: until the shell resolves `component`, render it in `main.tsx`, wrapped in `ErrorBoundary variant="panel"`.

Snippet (type-checked with the frontend `tsc`)

```tsx
// frontend/src/ui/driver/FuelMargin.tsx
import {useLive} from '../../app/liveStore'

export default function FuelMargin(){
 const fuel=useLive('fuel')
 if(!fuel?.available)return <p className="subtle">{fuel?.reason||'Fuel data unavailable'}</p>
 return <div className="card"><h3>Fuel margin</h3><b>{fuel.margin_l==null?'—':fuel.margin_l.toFixed(1)}<span> L</span></b></div>
}
```

```ts
// frontend/src/domain/panels.ts, inside PANELS
{id:'strategy.fuel',title:'Fuel margin',component:'FuelMargin',channels:['fuel'],minSize:{w:240,h:120},boundary:true},
```

Test: there is no frontend unit-test runner; cover the behaviour with a Playwright case in `tests/e2e/` (see `TESTING.md`) and keep
the panel free of I/O. Backend data it needs should already have a test.

Regenerate/verify: `npm --prefix frontend run check:arch`, `npm --prefix frontend run build` (`tsc -b && vite build`).

## 4. New Race Control command

Files: `backend/app/commands_catalog.py` (payload model, handler, `_def(...)`); `frontend/src/domain/commands.ts` (`CommandId`
union is hand-written); `tests/test_commands.py`.

Rules: use an existing capability or add one (recipe 7); set `audited=True` for anything privileged or externally visible (race
control, broadcast, destructive); add `rate=(max, seconds)` for anything a UI could spam; `destructive=True` requires
`confirm: true` in the payload. Handlers receive `ctx.services` (the `Runtime`); group handlers call `GroupService` methods, which
validate their own bodies and raise `AppError`. Return `_ok(message, data)`.

Module registration: `backend/app/modules.py` builds each module's command list by id prefix (`_commands('group.', 'raceControl.')`
belongs to `group_race_control`), so a new `raceControl.*` or `group.*` id is picked up automatically. A new prefix needs a
`ModuleDef` (or an entry in the orphan allowlist of `tests/test_modules_engineer.py::test_every_service_and_command_belongs_to_a_module`).
Add a newly used capability to that module's `capabilities` tuple if you want it listed.

Snippet

```python
class Announcement(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    expires_in: int = Field(60, ge=5, le=3600)


async def _announce(ctx, b):
    return _ok('', await _group(ctx).message({'text': b.text, 'scope': 'all', 'expires_in': b.expires_in, 'acknowledgement': True}))


_def('raceControl.announce', 'raceControl.messageAll', Announcement, _announce,
     'Send a message to every driver (acknowledgement requested)', audited=True, rate=(30, 60))
```

Test (in `tests/test_commands.py`)

```python
EXPECTED_ROLES['raceControl.messageAll'] = LOCAL_OPS        # required: test_role_command_matrix raises KeyError otherwise

def test_announce_needs_message_all():
    ctx = cmd.Ctx(principal('driver'), services=None)
    result = asyncio.run(cmd.dispatch(ctx, 'raceControl.announce', {'text': 'Box'}, limiter=cmd.RateLimiter()))
    assert result.code == ResultCode.NOT_AUTHORIZED
```

`test_role_command_matrix` then covers every role automatically. For behaviour and audit, extend
`test_race_control_flow_through_commands_with_audit` (real app through `POST /api/commands/{id}`; assert `audit_id`).

Pinned: `EXPECTED_ROLES` (above). Regenerate/verify: `GEN`, `PYT tests/test_commands.py tests/test_modules_engineer.py tests/test_contracts_fresh.py`.
Legacy routes are not needed for new commands (`COMMANDS_AND_PERMISSIONS.md`).

## 5. New network message

Files: `backend/app/group/protocol.py` (payload schema plus one `MessageType` in the `for _m in (...)` tuple); the transport branch in
`backend/app/group/public.py` (driver socket) or `group/client.py`; `tests/test_protocol_v2.py`.

The registry fixes the type name (max 32 characters), the Pydantic payload schema, the reliability class (`ephemeral` =
latest wins; `reliable` = retried until acked, deduplicated by envelope id) and the roles allowed to send it.
`RELIABLE_TYPES` and `ALLOWED_TYPES` are computed from the registry at import, so the entry must sit in that tuple, not be
registered later. `decode(raw, role=...)` enforces size (32 KiB), envelope, schema and the role allowlist (403 otherwise).
Transports still dispatch on the type by hand: the driver socket in `public.py` has an `if kind == ...` chain that ends in
`fail(422, 'Unknown message')`, so an inbound driver type needs a branch there.

Snippet

```python
class PitRequestPayload(Payload):
    lap: int
    reason: str = ''


# in the tuple of MessageType(...) rows
MessageType('pit_request', PitRequestPayload, 'reliable', frozenset({'driver'}), 'Driver asks the host for a pit window'),
```

```python
# group/public.py, driver socket chain
elif kind == 'pit_request': reply = codec.out('ack', {'id': env.id, 'of': 'pit_request'})   # plus the service call (shape only)
```

Test

```python
def test_pit_request_is_reliable_and_driver_only():
    envelope = encode('pit_request', {'lap': 4}, sender='d1')
    assert decode(envelope, role='driver').envelope.type == 'pit_request' and 'pit_request' in RELIABLE_TYPES
    with pytest.raises(ProtocolError) as info:
        decode(envelope, role='spectator')
    assert info.value.status_code == 403
    with pytest.raises(ProtocolError):
        encode('pit_request', {'reason': 'x'})            # lap is required
```

Pinned: `test_type_allowlist_per_role` (exact driver set), `test_every_existing_message_type_is_registered` (exact reliable set).
Regenerate/verify: `GEN` (message table in CONTRACTS.md), `PYT tests/test_protocol.py tests/test_protocol_v2.py tests/test_group.py`.
Do not change the envelope version for an additive type.

## 6. New OBS graphic

Files

- `backend/app/group/graphics.py`: one `_t(...)` row (order is the studio library order). `required_models` must be names in
  `group/state_models.py` `MODEL_NAMES`; `sharing` is the set of sharing categories the group must publish
  (`basic|telemetry|fuel|strategy`); `slots` are `('primary',)` or `('a','b')`; `lifecycle=_POPUP` makes it a transient popup.
  `Graphic.template` is a `Literal` built from the registry at import, so no model change is needed.
- `frontend/src/GroupGraphics.tsx`: a `case '<id>':` in the `switch(g.template)` of `GraphicView`. An id without a case renders
  nothing (the `default` is `content=null`).
- Preview: `preview_fixture` is a label only (`league_demo`, `league_demo:battle`, `league_demo:fuel_strategy`); no code resolves it.
  Preview a graphic by starting the league demo (`POST /api/group/demo`, the "rehearsal demo" button) and checking the studio
  preview. If the demo state does not exercise your graphic, extend `backend/app/group/demo.py`.

Snippet

```python
_t('pit_window', 'Pit window', 'strategy', 700, 220, models=('SelectedEntries',), sharing=('fuel',),
   data=('fuel',), slots=_SELECTED)
```

```tsx
case 'pit_window':{if(!selected)return null;content=<>{heading('Pit window')}<b>{value(selected,'fuel',' L')}</b></>;break}
```

(`selected`, `heading` and `value` are the helpers already defined in `GraphicView` and at the top of the file; the case was
type-checked.) Show unavailable data as unavailable; never infer game facts.

Test: `tests/test_group_graphics_contract.py::test_every_template_fulfils_the_contract` checks name, category, models, sharing,
lifecycle keys and size for every template automatically. Add sharing and slot assertions to
`test_sharing_and_models_match_what_each_graphic_reads`, and an e2e case if the studio needs it.

Pinned: `tests/test_graphics_registry.py` (`len(rows)==28`, `NEW` set), `tests/test_group_graphics_contract.py` (`PREVIOUS` table,
`len(...) == 28` in three places). Regenerate/verify: `GEN` (`graphics.generated.ts`), `PYT tests/test_graphics_registry.py
tests/test_group_graphics_contract.py`, `npm --prefix frontend run build`.

## 7. New permission

Files: `backend/app/core/permissions.py`; `frontend/src/domain/permissions.ts` (the `CapabilityId` union is hand-written);
`tests/test_commands.py`, `tests/test_permissions_matrix.py`.

`CAPABILITIES` is filled from the `{area: [(id, description), ...]}` dict. `host` gets every capability; `local` gets every capability
except areas `driver` and `overlay`; `driver`, `spectator`, `overlay` are explicit frozensets in `ROLES`, so add the id there if
they should hold it. Use `CONDITIONAL_GRANTS` for a flag-dependent grant and `@scope_rule('<id>')` for resource-level checks.

Snippet

```python
'raceControl': [..., ('raceControl.zones', 'Edit zones'), ('raceControl.pitBoard', 'Send pit board instructions')],
# ROLES: host and local pick it up automatically. Give it to another role explicitly:
'spectator': frozenset({'graphics.view', ..., 'raceControl.pitBoard'}),
```

Test

```python
# tests/test_commands.py: independent of ROLES, written by hand
EXPECTED_ROLES['raceControl.pitBoard'] = LOCAL_OPS
# tests/test_permissions_matrix.py, add rows to test_static_role_table
('host', 'raceControl.pitBoard', True), ('driver', 'raceControl.pitBoard', False), ('spectator', 'raceControl.pitBoard', False),
```

With the example addition, `can()` was verified to grant `host` and `local` and deny `driver`, `spectator`, `overlay`. Pending or
removed participants hold nothing regardless. Regenerate/verify: `GEN` (role matrix), `PYT tests/test_commands.py
tests/test_permissions_matrix.py tests/test_core_foundation.py`. The server enforces; the frontend `can()` only hides UI.

## 8. New alert rule

Files: `backend/app/engineer.py` (a `RuleSpec` in the `for _r in (...)` block); `ALERT_RULES.md` (documented rows come from the same
registry); `backend/app/modules.py` (the `engineer` module's `rules=(...)` tuple); `tests/test_engineer_rules.py`,
`tests/test_reliability.py`.

`RuleSpec(id, priority, persist_s, prerequisite, entry_text, exit_text, entry, exit, message)`. The three texts are the documented
conditions (served by `/api/capabilities` and CONTRACTS.md); `entry`, `exit` and `message` are callables of `RuleContext` (`v`,
`cfg`, `fuel`, `valid_fuel`, `temp`, `imbalance`, `speed` in km/h, `inside`). Priority 0 critical to 3 coaching. Persistence and the
global cooldown (`Settings.alert_cooldown`) are applied by `Rules.evaluate`; exit hysteresis is your `exit` callable. A spec without
callables (like `tyre_heat_rate`) is not evaluated generically and needs its own method. A rule that fires is spoken by the
Scheduler (arbitration in `ALERT_RULES.md`) and listed by the alert centre (`domain/alerts.py`, `Runtime._raise_alert`).

Snippet

```python
 RuleSpec('long_coast',3,6,'speed > 60 km/h','no pedal input above 60 km/h','either pedal above 10% or speed < 50 km/h',
  lambda c:c.v['throttle']<.05 and c.v['brake']<.05 and c.speed>60,lambda c:c.v['throttle']>.1 or c.v['brake']>.1 or c.speed<50,
  lambda c:'Long coast. Consider staying on the throttle or committing to the brakes.'),
```

Test (positive, negative and noisy, in `tests/test_engineer_rules.py`; it fires once at 6 s and never on flapping input)

```python
def test_long_coast_positive_and_noisy():
    rules = new.Rules(Settings(alert_cooldown=60))
    fired = [e for i in range(200) for e in rules.evaluate(frame(i / 20, throttle=0.0, brake=0.0, speed_kmh=120.0), 'S')
             if e.category == 'long_coast']
    assert len(fired) == 1 and fired[0].priority == 3
    noisy = new.Rules(Settings(alert_cooldown=60))
    assert not [e for i in range(200) for e in noisy.evaluate(frame(i / 20, throttle=0.0 if i % 40 < 20 else 0.5, brake=0.0, speed_kmh=120.0), 'S')
                if e.category == 'long_coast']
```

Pinned: `test_rule_registry_matches_documented_rules` (exact id list), `test_legacy_oracle_has_identical_rules_table` and the parity
tests compare against the frozen 10-rule oracle `tests/fixtures/legacy_engineer.py` (restrict them to the legacy ids), and
`tests/test_reliability.py::test_each_rule` needs an `if name==...` trigger branch for the new id. Regenerate/verify: `GEN`,
`PYT tests/test_engineer_rules.py tests/test_reliability.py tests/test_modules_engineer.py tests/test_contracts_fresh.py`.

## 9. New training achievement

Files: `backend/app/domain/training_defs.py`; `tests/test_domain_insights_training.py`.

An achievement is data plus an `EvaluatorRef(id, params)`. An evaluator is a pure function `(summary, params) -> Progress` over a stored
session summary (`{'status', 'provenance', 'laps': [...]}`); no I/O, clocks or randomness. Reuse an existing evaluator
(`clean_laps`, `consistent_streak`, `completed_session`) by adding only an `Achievement`; add an evaluator when the maths is new.

Snippet

```python
@evaluator('best_lap_under', 'Fastest clean lap at or under a target time')
def best_lap_under(summary, params):
    times = [l['duration_ms'] for l in summary.get('laps', []) if _clean(l)]
    best = min(times) if times else None
    return Progress(1 if best is not None and best <= params['target_ms'] else 0, 1,
                    {'best_ms': best, 'target_ms': params['target_ms']})


ACHIEVEMENTS.register(Achievement('sub_two_minutes', 'Sub two minutes', 'Set a clean lap of 2:00 or faster.',
                                  EvaluatorRef('best_lap_under', {'target_ms': 120000})))
```

Test: add cases next to `test_three_example_achievements_are_pure_evaluators` (met and not met, including a lap that is not
`comparable`); `test_evaluators_do_not_mutate_input_and_registry_is_strict` already checks purity, registration and
JSON-safety for every registered definition. Regenerate/verify: `PYT tests/test_domain_insights_training.py`. Nothing in the running app
calls the evaluators yet.

## 10. New session analysis

Files: the analysis function (today `analytics.py`, `Sessions.report()`, `spatial_coaching.py`, `domain/insights.py`);
`backend/app/core/version.py` (`ANALYSIS_VERSION`); `backend/app/analysis_cache.py` (no change needed).

There is no pipeline-stage abstraction: analysis functions are plain code that takes a session's stored data. `AnalysisCache` is the
place for results that are expensive to recompute. Bump `ANALYSIS_VERSION` whenever the output of any cached analysis changes
meaning, so old entries miss; the cache key is `(session_id, source_hash, analysis_version, settings_hash)`.

Snippet

```python
cache = AnalysisCache(data_dir)                       # <data>/cache/analysis, 500 MiB bound, LRU
src = source_hash(store, sid)                         # changes when samples or laps change
cfg = settings_hash({'reserve_l': settings.reserve_l})  # only the settings the analysis reads
result = cache.get(sid, src, cfg)
if result is None:
    result = my_analysis(store, sid)                  # JSON-serialisable
    cache.put(sid, src, result, cfg)
```

Run against a real `Store` with a recorded session: the first call computed, the second hit (`stats()` showed 1 hit, 1 miss).

Test: mirror `tests/test_storage_cache.py` (compute count is 1 across two calls; a new sample changes `source_hash` and forces
a recompute; a bumped version misses). Regenerate/verify: `GEN` (versions line in CONTRACTS.md), `PYT tests/test_storage_cache.py
tests/test_contracts_fresh.py`.

## 11. New settings value

Files: `backend/app/config.py` (`Settings` field); `backend/app/core/defaults.py` (the constant); `backend/app/core/config_migrations.py`
and `core/version.py` (only when needed); `backend/app/modules.py` (`settings_fields` of the owning module);
`frontend/src/domain/types.ts` (hand-written `Settings` type); the Settings UI if user-editable.

A purely additive field with a default needs no migration: old files load and Pydantic fills the default. Add a migration when
you rename, reinterpret or re-constrain a value, or want an explicit stamp and backup: bump `SETTINGS_SCHEMA_VERSION` and add
exactly one function per version (an `assert` enforces it). `Config` backs the old file up as `settings.v{n}.bak.json` before writing.

Snippet

```python
# core/defaults.py
EXAMPLE_HZ = 10
# config.py, in Settings (D is core.defaults)
example_hz:int=Field(D.EXAMPLE_HZ,ge=1,le=60)
# core/version.py
SETTINGS_SCHEMA_VERSION = 3
# core/config_migrations.py
def m2_to_3(raw: dict) -> dict:
    raw = dict(raw)
    raw.setdefault('example_hz', 10)
    raw['schema_version'] = 3
    return raw

MIGRATIONS: dict[int, Callable[[dict], dict]] = {1: m1_to_2, 2: m2_to_3}
```

`migrate({'schema_version': 2, 'ui_hz': 12})` returned the value with `example_hz` added, versions applied `[2]`, and kept `ui_hz`.

Test (patterned on `tests/test_core_foundation.py`)

```python
def test_migration_2_to_3_adds_example_hz_and_preserves_values():
    raw, applied = migrate({'schema_version': 2, 'ui_hz': 12})
    assert applied == [2] and raw['example_hz'] == 10 and raw['ui_hz'] == 12
```

Pinned: none for the field itself, but `tests/test_modules_engineer.py::test_modules_reference_only_things_that_exist` requires every
`settings_fields` entry to exist. Regenerate/verify: `GEN` (settings table), `PYT tests/test_core_foundation.py tests/test_modules_engineer.py
tests/test_contracts_fresh.py`.

## 12. New export format

Files: `backend/app/storage/exports.py`; `tests/test_storage_exports.py`.

`ExportFormat(id, name, extension, supports, write, media_type)`, `write(source, sid, stream, options)`. `source` is a `Store` or a
`SqliteSessionRepository`; use `_repo(source)`, `_require_detail`, and `_iter_samples` for paged reads; write bytes to `stream`.
`GET /api/sessions/{sid}/export?format=<id>` picks it up with no route change (`bundle_v1` is the only special case). Formulas in
CSV cells must go through `exporting.safe_cell`.

Snippet

```python
def _write_summary_json(source, sid, stream, options):
    repo = _repo(source)
    _require_detail(repo, sid)
    detail = repo.get(sid).to_public()
    detail.pop('report', None)
    stream.write(json.dumps(detail, indent=1).encode('utf-8'))


EXPORT_FORMATS.register(ExportFormat('summary_json', 'Session summary (JSON)', '.json', ('session',),
                                     _write_summary_json, 'application/json'))
```

Test (uses the module's `run(store, sid, fmt)` helper and `store` fixture)

```python
def test_summary_json(store):
    assert json.loads(run(store, 'sid', 'summary_json'))['id'] == 'sid'
```

Pinned: `test_storage_exports.py::test_registry_lists_formats` and `test_foundation_api.py::test_export_formats_registry_route` (exact id sets).
Regenerate/verify: `GEN`, `PYT tests/test_storage_exports.py tests/test_foundation_api.py tests/test_contracts_fresh.py`.

## 13. New engineer intent

Files: `backend/app/requests.py` (`CATALOG`); `backend/app/runtime.py` `Runtime.execute` (only for action intents);
`tests/test_requests.py`, `tests/test_api.py`.

The catalogue is exactly 100 entries (`assert len(CATALOG)==100`). Every entry has one exact spoken phrase (`voice.ALIASES` is built
from it, so the phrase works by voice and text) and three distinct response forms.

- Metric intent: one row in the `METRICS` block, `id|exact request|category|label|value path|unit|scale`. The three forms are generated
  from label and unit; the value path is read from `v.` (sample values), `fuel.`, `report.`, `analysis.`, `delta.`, `car.`, `settings.`,
  `runtime.`, `health.` and others. No handler code. Stale telemetry and missing values are answered for you.
- Action intent: `legacy(key, phrase, category, forms)` with exactly three forms, each containing `{answer}` (or fixed text), plus an
  `elif action=='<key>'` branch in `Runtime.execute` that sets `answer` (and optionally `navigate`). `execute` is shared by voice, text
  (`POST /api/command`) and the `engineer.ask` command through `engineer_service.RuntimeEngineer.ask`. An action with no branch answers
  "That value is unavailable from the current telemetry."

Snippet

```python
# requests.py, metric (millimetres = metres * 1000)
body_height|what is my body height|Car|body height reading|v.body_height|millimetres|1000
# requests.py, action
legacy('coast_report','how much have i coasted','Analysis',['{answer}','Coasting review. {answer}','Here is your coasting evidence. {answer}'])
# requests.py, keep the invariant in step
assert len(CATALOG)==102,len(CATALOG)
```

```python
# runtime.py, Runtime.execute, next to the other elif branches
elif action=='coast_report':
    c=self.live_analysis.result.get('coast_percent')
    answer=f'Coasting {c:.0f} percent over the last {self.live_analysis.result["window_s"]} seconds.' if c is not None else 'No coasting evidence yet.'
```

In a scratch process with both rows added, `intent('what is my body height')` returned `('body_height', None)`, three successive answers
had the three forms, and the action phrase parsed to `coast_report`.

Test: `tests/test_requests.py` parametrizes over `CATALOG`, so distinct phrases, three distinct replies and no unformatted `{` are
checked for free. Add a value assertion like `test_live_values_stale_gating_and_unknowns`.

Pinned: `test_catalog_is_one_hundred_distinct_requests` (`==100`), `tests/test_api.py` (`catalog['count']==100`), and the literal
`'count':100` in `GET /api/engineer/requests` in `api.py`. Regenerate/verify: `PYT tests/test_requests.py tests/test_api.py
tests/test_core.py` (intent grammar).

## 14. New service

Files: `backend/app/runtime_services.py` (probe or wrapper, plus `build_services`); `backend/app/modules.py` (a `ModuleDef` that lists it
in `services=`); `tests/test_modules_engineer.py`.

`ProbedService(id, probe)` reports the state of something whose lifecycle is owned elsewhere; `LoopService(id, runtime, coro_factory, probe)`
also owns one asyncio loop. A probe returns `(ServiceState, detail, metrics)` and must be cheap. `reg.register(service, depends_on=(...))` sets
start order; stop is the reverse; a failed service does not stop the others (`core/lifecycle.py`). Status appears in `/api/services`,
`/api/state` (`services`) and diagnostics.

Snippet

```python
def cooling_probe(runtime) -> Probe:
    def probe():
        return ServiceState.RUNNING, 'Fans nominal', {'received': runtime.received}
    return probe

# in build_services(runtime)
reg.register(ProbedService('cooling', cooling_probe(runtime)), depends_on=('diagnostics',))
```

```python
# modules.py
ModuleDef('cooling', 'Cooling', 'Fan and thermal monitoring', services=('cooling',)),
```

The registration and the `public()` listing were exercised on a live `Runtime`. Test: `test_modules_reference_only_things_that_exist` and
`test_every_service_and_command_belongs_to_a_module` (a service with no owning module fails) run automatically; add a behaviour test for
the probe. Regenerate/verify: `PYT tests/test_modules_engineer.py tests/test_core_foundation.py tests/test_foundation_api.py`.

## 15. New bus subscriber

Files: `backend/app/runtime.py` `Runtime._wire_bus`; `tests/test_runtime_foundation.py`.

`bus.subscribe(name, handler, mode='every'|'rate'|'latest', hz=None, critical=False)`. The handler receives a `TelemetryFrame`
(`f.sample`, `f.values`, `f.meta`). `every` runs inline on the ingest path for every frame and must stay cheap (ADR 0002: 50 us or less);
use `rate` (needs `hz`) for heavy work. A handler that raises is isolated: counted per subscriber and as a pipeline error, logged at most
once per 60 s. Subscribers run in subscription order (critical ones first); see TECH_DEBT #14 for why the recorder is not critical.
Names are unique per kind. For discrete events use `bus.subscribe_events(name, handler, kinds=[LAP_COMPLETED])`
(kinds: `lap_completed`, `session_started`, `session_ended`, `source_changed`, `connection_changed`, `track_locked`,
`track_unlocked`, `pit_detected`).

Snippet

```python
# in Runtime._wire_bus, order matters relative to the other subscribers
b.subscribe('cooling', lambda f: self.cooling.consume(f.sample), mode='rate', hz=5)
```

```python
# behaviour verified on a live Runtime: 120 frames at 60 Hz through a 5 Hz subscriber gave 10 calls and 0 errors
sub = runtime.bus.subscribe('probe', lambda f: seen.append(f.meta.packet_id), mode='rate', hz=5)
```

Test: assert the call count for a fixed frame stream and that a raising handler does not stop later subscribers (pattern:
`test_failing_subscriber_is_isolated_and_counted_as_pipeline_error`). Pinned:
`test_subscribers_are_wired_in_the_original_order` (exact ordered list). Regenerate/verify: `PYT tests/test_runtime_foundation.py
tests/test_telemetry_bus.py`, then the ingest bench (`PERFORMANCE_BUDGETS.md`).

## Before you merge

```
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=<writable dir>
npm --prefix frontend run build
npm --prefix frontend run check:arch
.venv/Scripts/python.exe scripts/gen-contracts.py --check          # run without --check first if you changed a registry
.venv/Scripts/python.exe scripts/bench_ingest.py --output <scratch>/bench_after.json   # if you touched ingest, bus, parser, derived or the recorder
```

Compare the bench with `docs/architecture/bench_baseline.json` (relative guard: no more than 5 percent regression; procedure and caveats
in `PERFORMANCE_BUDGETS.md`). Update the docs the change touches (`ALERT_RULES.md` for rules, `DATA_FIELDS.md` for fields). Playwright
(`npm --prefix frontend run test:e2e`) needs a running backend; see `TESTING.md`.
