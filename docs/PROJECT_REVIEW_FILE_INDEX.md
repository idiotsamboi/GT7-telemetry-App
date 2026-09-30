# GT7 Project Review File Index

Review snapshot: 2026-09-30. This is a structural index of project-owned source, tests, configuration, documentation, data manifests and vendored protocol references. All indexed text files were read by the inventory script; symbol extraction is not a claim of a line-by-line correctness audit. The companion PROJECT_BRAINSTORMING_CONTEXT.md contains the interpreted architecture and limits.

Excluded from content review: installed dependencies, Git internals, runtime databases and credentials, raw personal telemetry, model weights, compiled/minified distributions, caches, release binaries, and screenshot pixel-level verification. These categories were identified, not treated as authored application source. Existing lockfiles were consulted for dependencies rather than duplicated here.

Indexed files: **362**. Total indexed text lines: **60,918**. Counts describe the working tree, including uncommitted files, before this review document was written.

| File | Lines | Structural purpose or top-level symbols |
|---|---:|---|
| `.gitignore` | 11 | Configuration, styles, tooling or third-party reference |
| `ALERT_RULES.md` | 25 | Engineer rules and arbitration |
| `ARCHITECTURE.md` | 251 | Architecture |
| `backend/__init__.py` | 0 |  |
| `backend/app/__init__.py` | 0 |  |
| `backend/app/analysis_cache.py` | 123 | Disposable on-disk cache of analysis results, bounded in size.; _digest, settings_hash, source_hash, AnalysisCache |
| `backend/app/analytics.py` | 172 | Incremental metrics: no whole-recording rescan in the receive path.; fuel_prediction, lap_statistics, downsample, approximate_compare, Accumulator, improvements, align_laps, _ols_slope, fuel_scenarios, braking_episodes |
| `backend/app/api.py` | 406 | create_app |
| `backend/app/cars.py` | 6 | Offline, attributed car identity lookup. Unknown IDs never guess a brand.; identify |
| `backend/app/clean_air.py` | 70 | Clean-air pit advice (docs/AI_CONTEXT.md §12): runs on a driver's own app; pit_advice |
| `backend/app/commands_catalog.py` | 305 | Command catalogue: existing behaviour exposed as commands (no new features).; _ok, Value, Layout, Text, Milliseconds, ReplayStart, SeekPayload, SpeedPayload, Enabled, TrackImport, TrackConfirm, TrackRestore, _control, _intent ... |
| `backend/app/config.py` | 141 | Units, Settings, Config |
| `backend/app/control.py` | 107 | Operator control actions (source switching, audio, replay...). One implementation shared by the; control_action |
| `backend/app/core/__init__.py` | 1 | Application core: depends on nothing else in backend.app (enforced by tests/test_architecture.py). |
| `backend/app/core/commands.py` | 149 | Commands (state-changing or externally visible) vs queries (read-only GET).; uid, CommandResult, Empty, Ctx, CommandDef, register, RateLimiter, payload_hash, dispatch |
| `backend/app/core/config_migrations.py` | 69 | Settings schema migrations: raw JSON -> migrate -> validate.; m1_to_2, MigrationError, migrate, backup_before_migration, load_raw |
| `backend/app/core/defaults.py` | 39 | Centralised defaults and magic numbers. Settings validators and services reference these. |
| `backend/app/core/errors.py` | 55 | Application errors. Adapters (api.py, group/admin.py, group/public.py) map these to HTTP.; ResultCode, code_for_status, AppError |
| `backend/app/core/events.py` | 42 | Small in-process pub/sub for application events (lap, session, connection...). No broker.; AppEvent, EventBus |
| `backend/app/core/features.py` | 49 | Feature flags. Storage is Settings.feature_flags (plus legacy settings that already exist).; FeatureFlag, is_enabled, snapshot |
| `backend/app/core/lifecycle.py` | 163 | Service lifecycle: every long-running subsystem reports a ServiceStatus; one failure never stops the rest.; ServiceState, ServiceStatus, Service, BaseService, ServiceRegistry |
| `backend/app/core/logging_setup.py` | 159 | Structured JSON-lines logging with redaction, repeat suppression and an in-memory error ring.; redact_text, redact, RedactionFilter, RepeatFilter, JsonFormatter, ErrorRing, setup_logging, get_logger, log_event |
| `backend/app/core/modules.py` | 30 | Lightweight module registry. A feature is a module file plus one line in the composition root.; ModuleDef |
| `backend/app/core/permissions.py` | 119 | Capabilities and roles. Roles are data; the server always enforces, UI hiding is only cosmetic.; Capability, Principal, scope_rule, _owns_or_shared, _overlay_scope, capabilities_for, can, matrix |
| `backend/app/core/platform.py` | 52 | Platform adapter: feature code asks here, never `sys.platform` / `os.name` directly.; exclusive_udp_bind_supported, cpu_count, total_memory_bytes, resolve_performance_profile |
| `backend/app/core/registry.py` | 63 | One registry pattern for channels, commands, capabilities, modules, ... (docs/architecture).; DuplicateRegistration, Registry |
| `backend/app/core/version.py` | 14 | Single source for version numbers. Packaging, /api/health, the protocol hello and diagnostics read this.; versions |
| `backend/app/data/cars.json` | 2922 | JSON keys: 24, 31, 41, 48, 63, 82, 104, 105, 135, 137, 145, 173 |
| `backend/app/data/track-references.json` | 1 | JSON keys: schema, source_revision, source_sha256, layouts |
| `backend/app/data/tracks.json` | 1062 | JSON list, 41 entries |
| `backend/app/diagnostics.py` | 36 | Read-only network diagnostics. Never stops another application's receiver.; udp_owners, routing_address |
| `backend/app/diagnostics_report.py` | 84 | `GET /api/diagnostics` aggregate and the redacted "copy diagnostics" bundle.; mask_ips, _scrub, collect, redacted_bundle |
| `backend/app/domain/__init__.py` | 4 | Domain definitions: annotations, alerts, insights, timing models, training definitions. |
| `backend/app/domain/alerts.py` | 127 | Alerts (what the UI shows) and the declarative form of engineer rules.; Alert, AlertCenter, RuleDef |
| `backend/app/domain/annotations.py` | 103 | One typed timeline entry for a session (incident, flag, pit, radio, bookmark, ...).; Annotation, _epoch, from_decision_event |
| `backend/app/domain/insights.py` | 62 | A coaching/analysis finding in one shape, with adapters from the two existing producers.; Insight, from_improvement, from_corner_item, from_improvements, from_corner_report |
| `backend/app/domain/timing_models.py` | 30 | Small shared timing shapes. GT7 UDP carries no sector splits, so none are modelled (see SECTORS_NOTE).; LapTime, best_lap |
| `backend/app/domain/training_defs.py` | 140 | Achievement / Challenge definitions and pure evaluators.; Progress, Evaluator, EvaluatorDef, EvaluatorRef, Achievement, Challenge, evaluate, evaluate_all, evaluator, _clean, clean_laps, consistent_streak, completed_session |
| `backend/app/engineer.py` | 168 | Event, Scheduler, RuleContext, RuleSpec, _off_surface, Rules |
| `backend/app/engineer_service.py` | 84 | EngineerService boundary.; EngineerResponse, EngineerBrief, EngineerService, RuntimeEngineer |
| `backend/app/exporting.py` | 93 | Safe, bounded exports. Bundles contain JSONL + metadata + a checksum manifest.; safe_cell, report_html, export_bundle, inspect_bundle |
| `backend/app/group/__init__.py` | 1 | Race-control domain. No receiver, filesystem or server starts on import. |
| `backend/app/group/admin.py` | 225 | Local administration routes. Never mounted on the public group listener.; error_response, _app_error_handler, install_error_handlers, AppErrorRoute, router |
| `backend/app/group/asset_worker.py` | 20 | Minimal spawn target: no service, catalogue or application imports.; decode_worker |
| `backend/app/group/assets.py` | 37 | Isolated raster decoding. Originals are private; only normalized variants are served.; Assets |
| `backend/app/group/battles.py` | 255 | Battle Index: per-pair "how close a fight is right now" scoring; clamp, _ols_slope, PairState, BattleEngine |
| `backend/app/group/client.py` | 124 | Outbound forwarding of the existing normalized receiver; never opens a GT7 socket.; ProtocolIncompatible, NoRedirect, request, address, MemberClient |
| `backend/app/group/demo.py` | 54 | Deterministic synthetic league, independent of the local GT7 receiver.; scene, start_demo, tick |
| `backend/app/group/graphics.py` | 144 | Broadcast graphic templates: one registry entry per template instead of scattered tables.; GraphicTemplate, _t, public_templates, legacy_graphics, template_ids, describe |
| `backend/app/group/history.py` | 96 | Per-entry distance-over-time history and the gap math built on it.; DistanceHistory, interval, gap_uncertainty, is_lapped, common_timeline |
| `backend/app/group/migrations.py` | 129 | Per-document schema versions for group documents.; MissingUpgrade, team_id_for, ensure_team_ids, _branding_teams, _league_1_to_2, _group_1_to_2, _asset_1_to_2, schema_of, upgrade, stamp |
| `backend/app/group/models.py` | 194 | Model, Branding, GroupConfig, Identity, Join, Packet, Instruction, Message, Decision, Zone, Graphic, WorkspaceConfig |
| `backend/app/group/pit.py` | 182 | Host-side pit-stop detection and the learned pit-loss/refuel-rate estimates; _distance_to_polyline, _in_corner, detect, _EntryState, PitTracker, learned_pit_loss, learned_refuel_rate |
| `backend/app/group/principals.py` | 27 | Bridge from the credential dicts the group service authenticates to `core.permissions.Principal`.; principal_from_dict, allowed |
| `backend/app/group/projection.py` | 142 | Net position and pit-window projector (docs/AI_CONTEXT.md section 5): given; stops_needed, stop_cost_s, pit_window, project, FuelBurnTracker |
| `backend/app/group/protocol.py` | 432 | Group wire protocol v2: envelope, message registry, handshake and reliable delivery.; ProtocolError, Payload, HelloPayload, ClientHello, ServerHello, TelemetryPayload, LapPayload, ResponsePayload, PingPayload, PongPayload, ClockPayload, StatePayload, ErrorPayload, AckPayload ... |
| `backend/app/group/public.py` | 166 | Dedicated LAN surface. Deliberately contains no local administration routes.; public_app, registry |
| `backend/app/group/repository.py` | 65 | Durable group records in the existing SQLite database; independent of receiver queue.; uid, digest, encode, GroupRepository |
| `backend/app/group/service.py` | 660 | fields_for, fail, clone, GroupService |
| `backend/app/group/snapshots.py` | 40 | Shared computed snapshots: N subscribers with the same view share one computation.; SnapshotCache |
| `backend/app/group/state_models.py` | 260 | Published state models: the shape of what `GroupService.filter_snapshot` hands to subscribers.; EntryField, Identity, Flag, EntryRow, SessionClock, RaceState, TimingState, SelectedEntries, FlagState, MessageEntry, MessageState, Decision, DecisionState, Battle ... |
| `backend/app/group/steward.py` | 92 | Automated stewarding graphics (docs/AI_CONTEXT.md section 6): turning a public; cue_text, enqueue_steward_cue, active_cue |
| `backend/app/group/timing.py` | 57 | TrackProgressAdapter, validate_map, Projection, in_zone, applicable_flags |
| `backend/app/live_analysis.py` | 59 | Bounded, causal analysis. No inferred tyre wear, grip or opponent data.; ReceptionTest, LiveAnalysis |
| `backend/app/live_delta.py` | 54 | Approximate causal lap alignment, bounded to 1500 points and 42 segments/query.; LiveDelta |
| `backend/app/local_ai.py` | 177 | Bounded telemetry briefs with optional offline, evidence-only model ranking.; memory_available_mb, inference_threads, evidence, selected_items, LocalAI |
| `backend/app/modules.py` | 51 | The module list: existing features registered as modules (composition metadata, not a plugin API).; _commands |
| `backend/app/operations.py` | 133 | Operations shared by the legacy HTTP routes and the command catalogue.; settings_update, track_import, track_select, track_confirm, track_restore, training_start, training_stop, training_retry_lap, training_restart, recovery_action |
| `backend/app/requests.py` | 153 | The offline engineer's 100-request catalogue and three factual response forms.; legacy, value_at, answer, public_catalog |
| `backend/app/runtime.py` | 560 | Runtime |
| `backend/app/runtime_services.py` | 203 | Service wrappers over the existing Runtime subsystems.; ProbedService, LoopService, receiver_probe, recorder_probe, engine_probe, microphone_probe, local_ai_probe, track_probe, group_host_probe, group_client_probe, overlay_probe, diagnostics_probe, build_services |
| `backend/app/safe_mode.py` | 66 | Safe mode and crash detection.; SafeMode, RunMarker, decide |
| `backend/app/sessions.py` | 72 | utcnow, Sessions |
| `backend/app/spatial_coaching.py` | 243 | Spatial per-lap timing trace and corner-loss coaching (docs/AI_CONTEXT.md; SpatialLap, BrakingEpisode, LiveBrakingTracker, corner_for, corner_label, _segment_loss, corner_report |
| `backend/app/storage/__init__.py` | 2 | Storage package. The SQLite writer/reader lives in `store.py` and is re-exported unchanged. |
| `backend/app/storage/audit.py` | 26 | `AuditSink` is the `Ctx.audit` callable: it enqueues audit rows on the store's writer thread.; AuditSink |
| `backend/app/storage/exports.py` | 177 | Export formats and import handlers as registries.; _repo, ExportFormat, export_session, _require_detail, _iter_samples, _write_bundle_v1, _write_csv, _write_jsonl, _write_html_report, ImportRejected, ImportResult, ImportHandler, _validate_bundle_v1, import_session_file |
| `backend/app/storage/layout.py` | 88 | The data directory map. One place that names every file/folder under the data root.; Entry, DataLayout |
| `backend/app/storage/models.py` | 93 | Read models returned by the storage repositories. Plain dataclasses, JSON-safe via `to_public()`.; Page, SessionQuery, SessionSummary, SessionDetail, SampleRow, LapSeries |
| `backend/app/storage/repositories.py` | 181 | Repository layer over `Store`. It wraps the existing SQL/writer thread; it does not replace them.; SessionRepository, encode_cursor, decode_cursor, SqliteSessionRepository |
| `backend/app/storage/retention.py` | 80 | Retention selection. Pure: decides WHICH sessions to archive; the caller archives them (never purges).; RetentionPolicy, _epoch, is_eligible, select_for_archive |
| `backend/app/storage/schema.py` | 34 | Schema upgrades applied inline by the writer thread (mirrored by backend/migrations/*.sql).; _columns, migrate |
| `backend/app/storage/store.py` | 115 | Store |
| `backend/app/telemetry/__init__.py` | 15 | Telemetry package. The wire parser lives in `parser.py`; everything it exported is re-exported here, |
| `backend/app/telemetry/bus.py` | 254 | Synchronous in-process telemetry bus.; TelemetryEvent, SubscriberMetrics, Subscription, TelemetryBus |
| `backend/app/telemetry/derived.py` | 269 | Derived (calculated) channels and the engine that evaluates them per frame.; DerivedState, DerivedChannel, _finite, _on_track, _speed_kmh, _wheel_speed, _slip_ratio, _LongGState, _longitudinal_g, _pedal_overlap, _RateState, _rate, _FuelState, _fuel_per_lap ... |
| `backend/app/telemetry/frame.py` | 241 | TelemetryFrame (one parsed packet + cheap metadata) and the channel catalogue.; FrameMeta, TelemetryFrame, Channel, channel_public, _getter, _title, _register_all, experimental_channel_ids, public_channels |
| `backend/app/telemetry/parser.py` | 151 | Explicit GT7 wire layout, ported from MacManley/gt7-udp (MIT).; PacketError, decrypt_datagram, Sample, parse, Sequence, demo_sample |
| `backend/app/telemetry/sources.py` | 226 | Telemetry source contract and deterministic synthetic scenarios.; TelemetrySource, ReplayControls, ScenarioItem, _Builder, _as_variant, ScenarioSpec, scenario, _normal_laps, _lap_transition, _fuel, _braking, _packet_loss, _out_of_order, _stale ... |
| `backend/app/telemetry/units.py` | 132 | Unit conversion. Canonical (internal) units are m/s, m, degrees C, L, bar, s, rad, rad/s, rpm.; _bad, speed, speed_to_ms, temp, temp_to_c, fuel, fuel_to_l, distance, distance_to_m, pressure, pressure_to_bar, label, spoken_speed |
| `backend/app/track_bundle.py` | 55 | Streaming access to the trusted, build-time offline model bundle.; iter_models, get_model |
| `backend/app/track_catalogue.py` | 72 | Shared read-only packed catalogue; each tracker owns its own recognition state.; load_user_models, new_recognizer, bundled_document |
| `backend/app/track_fusion.py` | 96 | Robust confirmed-lap fusion; observed spread is never labelled track limits.; fuse_laps |
| `backend/app/track_geometry.py` | 84 | Bounded, direction-aware geometry matching; no network or receiver dependencies.; length, resample, Fingerprint, shape_fit, transform |
| `backend/app/track_model.py` | 319 | Version-three world models and the single indexed track-progress primitive.; revision, world_points, auto_corners, build_model, Progress, TrackProgress |
| `backend/app/track_overlap.py` | 74 | Build-time route discrimination and geometric equivalence, without telemetry noise.; separating_intervals, annotate_overlaps |
| `backend/app/track_recognition.py` | 286 | Bounded world-frame Viterbi recognition, intended for the track worker only.; Hypothesis, TrackRecognizer |
| `backend/app/track_service.py` | 124 | Runtime owner of the v3 recognizer and the currently locked TrackProgress.; TrackService |
| `backend/app/track_store.py` | 231 | Atomic v3 user-model storage, lossless migration, layers and bounded track packs.; atomic_json, validate_model, validate_layers, TrackModelStore |
| `backend/app/tracks.py` | 238 | Offline layout memory. Receiver collection is cheap; recognition and I/O run in a worker.; validate_points, revision, atomic, TrackMap |
| `backend/app/training.py` | 215 | Live capture of raw world-frame laps for layouts with no offline model yet.; TrainingRecorder |
| `backend/app/tyre_heat.py` | 112 | Tyre heating-rate signal processing (docs/AI_CONTEXT.md section 7): compares; _ols_slope, TyreHeatMonitor |
| `backend/app/voice.py` | 208 | Offline intent grammar and an optional, isolated microphone worker.; intent, mic_worker, Microphone, Speaker, audio_devices, audio_probe |
| `backend/migrations/001_initial.sql` | 10 | Configuration, styles, tooling or third-party reference |
| `backend/migrations/002_archive.sql` | 2 | Configuration, styles, tooling or third-party reference |
| `backend/migrations/003_annotations_audit.sql` | 10 | Configuration, styles, tooling or third-party reference |
| `config.example.json` | 56 | JSON keys: schema_version, ps5_ip, udp_bind, udp_port, remote_port, http_host, http_port, allowed_origins, variant, heartbeat, ui_hz, stale_seconds |
| `DATA_FIELDS.md` | 76 | Data field reference |
| `desktop.py` | 69 | Linux desktop entry point; owns its local backend and uses system WebKit.; main |
| `docs/adr/0001-normalized-frame-typed-view.md` | 23 | 0001. The normalized frame is a typed view over `Sample.values` |
| `docs/adr/0002-in-process-telemetry-bus.md` | 24 | 0002. In-process TelemetryBus with delivery modes; no broker |
| `docs/adr/0003-sources-behind-telemetry-source.md` | 23 | 0003. Live, demo and replay behind `TelemetrySource` |
| `docs/adr/0004-capability-permissions.md` | 23 | 0004. Capability-based permissions with data-driven roles |
| `docs/adr/0005-commands-vs-queries.md` | 27 | 0005. Commands vs queries and the `CommandResult` codes |
| `docs/adr/0006-group-protocol-envelope-v2.md` | 27 | 0006. Group protocol envelope v2 with a v1 compatibility window |
| `docs/adr/0007-audit-log-vs-debug-logs.md` | 23 | 0007. Audit log vs debug logs, and the `group_events` decision |
| `docs/adr/0008-hash-routing-frontend-domain-layer.md` | 22 | 0008. Hash routing and the frontend domain layer |
| `docs/adr/0009-legacy-vs-v3-track-authority.md` | 22 | 0009. Legacy vs v3 track authority and migration plan |
| `docs/adr/0010-performance-profiles-never-alter-recording.md` | 18 | 0010. Performance profiles never alter recording fidelity |
| `docs/AI_CONTEXT.md` | 502 | GT7 Race Engineer — AI context file |
| `docs/architecture/AUDIT.md` | 83 | Architecture audit (baseline before the foundation pass) |
| `docs/architecture/bench_after_1.json` | 32 | JSON keys: runs, best_p95_ms, median_p50_ms, python, platform |
| `docs/architecture/bench_after_2.json` | 32 | JSON keys: runs, best_p95_ms, median_p50_ms, python, platform |
| `docs/architecture/bench_baseline.json` | 32 | JSON keys: runs, best_p95_ms, median_p50_ms, python, platform |
| `docs/architecture/CONTRACTS.md` | 380 | Contracts (generated) |
| `docs/architecture/DOMAIN_MODEL.md` | 101 | Domain model: identity |
| `docs/architecture/TECH_DEBT.md` | 26 | Technical debt register |
| `docs/benchmark.json` | 23 | JSON keys: platform, source, samples, duration_s, samples_per_s, ingest_p95_ms, initial_report_ms, cpu_seconds, queue_peak, storage, hardware_validation |
| `docs/BROADCAST_GRAPHICS.md` | 65 | Broadcast graphics |
| `docs/car-assets-provenance.json` | 304 | JSON keys: database_commit, logos_commit, images |
| `docs/desktop-benchmark.json` | 23 | JSON keys: platform, source, samples, duration_s, samples_per_s, ingest_p95_ms, initial_report_ms, cpu_seconds, queue_peak, storage, hardware_validation |
| `docs/frozen-engineer-validation.json` | 18 | JSON keys: frozen, request_count, three_variations, speech |
| `docs/frozen-handsfree-validation.json` | 28 | JSON keys: frozen_executable, catalog_count, audio, heartbeat |
| `docs/group-load-test-validation.json` | 188 | JSON keys: platform, cpu_count, total_ram_mb, note, cases |
| `docs/heartbeat-confirmation.json` | 162 | JSON list, 2 entries |
| `docs/heartbeat-handsfree-validation.json` | 212 | JSON list, 3 entries |
| `docs/licenses/car-database-MIT-0.txt` | 18 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/car-logos-README.md` | 106 | Car Logos Dataset 🚗 |
| `docs/licenses/gt7tracks-MIT.txt` | 21 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/lucide-ISC.txt` | 15 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/react-dom-MIT.txt` | 21 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/react-MIT.txt` | 21 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/track-reference-CC0.txt` | 21 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/track-reference-upstream-MIT.txt` | 21 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/track-tools-MIT.txt` | 21 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/uplot-MIT.txt` | 21 | Configuration, styles, tooling or third-party reference |
| `docs/licenses/vosk-model-Apache-2.0.txt` | 202 | Configuration, styles, tooling or third-party reference |
| `docs/live-reception-validation.json` | 53 | JSON keys: test, analysis, stale |
| `docs/local-ai-validation.json` | 61 | JSON keys: elapsed_s, model_bytes, evidence_bytes, input, output, hardware |
| `docs/LOCAL_AI.md` | 26 | Local AI: Orange Pi 4 Pro 4GB |
| `docs/ORIGINAL_REQUEST.txt` | 352 | Configuration, styles, tooling or third-party reference |
| `docs/program-audit.json` | 43 | JSON keys: utc, python_tests, browser_workflows, referenced_logos, missing_referenced_logos, manufacturers_without_supplied_logo, logo_fallback, production_npm_vulnerabilities, python_dependency_check, live_heartbeat_s, default_heartbeat_s, hands_free_enabled |
| `docs/prompts/CLAUDE_CODE_ARCHITECTURE_PROMPT.md` | 657 | CLAUDE CODE MASTER PROMPT: Architecture foundation pass (tailored to GT7 Race Engineer) |
| `docs/prompts/CLAUDE_CODE_UI_REDESIGN_PROMPT.md` | 513 | CLAUDE CODE MASTER PROMPT: GT7 Race Engineer UI/UX redesign (tailored to this repository) |
| `docs/prompts/CLAUDE_CODE_WHEEL_MAP_PROMPT.md` | 84 | Task: Put the track map on Pit Wall and Wheel, and build a dense SimHub-style Wheel dash |
| `docs/prompts/CODEX_TRACK_SYSTEM_PROMPT.md` | 146 | Task: Track recognition engine + full map-system overhaul |
| `docs/prompts/GT7TRACKS_INTEGRATION_PROMPT.md` | 120 | Task: Integrate vthinsel/GT7Tracks into the v3 track system, with optimization targets |
| `docs/race-viewer-validation.json` | 17 | JSON keys: python_tests, browser_workflows_passed, production_build, live_after_restart, notes |
| `docs/RACE_CONTROL.md` | 118 | Race Control development preview |
| `docs/reception-recovery-validation.json` | 65 | JSON keys: source, stale, age_ms, receiver, socket_error, reception_test |
| `docs/recognition-capture-eval.json` | 290 | JSON keys: suite, source, source_checksum, simulated_speed_mps, limits, captures, false_lock_captures, correct_first_locks, results |
| `docs/recognition-eval-baseline.json` | 4866 | JSON keys: suite, seed, world_layouts, evaluated_layouts, trials_per_layout, model_retained_bytes, runtime_ms, false_lock_trials, within_1km_rate, confusion, layouts, unverified |
| `docs/recognition-eval-distinguishing.json` | 5803 | JSON keys: suite, seed, processor, python, world_layouts, evaluated_layouts, trials_per_layout, model_retained_bytes, runtime_ms, false_lock_trials, within_1km_rate, acceptance_rule |
| `docs/recognition-eval.json` | 4880 | JSON keys: suite, seed, processor, python, world_layouts, evaluated_layouts, trials_per_layout, model_retained_bytes, runtime_ms, false_lock_trials, within_1km_rate, confusion |
| `docs/recognition-validation.json` | 20 | JSON list, 3 entries |
| `docs/RECOVERY.md` | 18 | Recovery and avoiding stuck states |
| `docs/release-validation.json` | 7 | JSON keys: windows_zip_bytes, linux_deb_bytes, archive_integrity, checksums, no_user_settings_or_recordings |
| `docs/speaker-validation.json` | 9 | JSON keys: state, engine, output_device, frames, duration_s, error, last_text |
| `docs/specs/ACTION_DIRECTOR_AND_COACHING_SPEC.md` | 605 | Implementation Spec: Broadcast Action Director + Spatial Strategy & Coaching |
| `docs/track-car-assets-provenance.json` | 2520 | JSON keys: catalogue, revision, assets, car_artwork, missing_car_ids |
| `docs/track-frame-validation.json` | 17 | JSON keys: source_commit, recording_provenance, session_id, lap_id, reference, sample_stride, samples, median_distance_m, p95_distance_m, transform, recording_quality, live_ps5_check |
| `docs/track-memory-benchmark.json` | 9 | JSON keys: library_fingerprints, full_match_median_ms, full_match_max_ms, reference_suggestion_ms, receiver_geometry_matching, maximum_worker_frequency_hz, scope |
| `docs/track-model-sources.json` | 134 | JSON keys: repository, commit, files |
| `docs/track-overlap.json` | 560 | JSON list, 93 entries |
| `docs/track-recording-eval.json` | 173 | JSON keys: session_id, lap_id, layout_id, reference_revision, reference_frame, provenance, samples, outside_100m_corridor, median_distance_m, p95_distance_m, first_lock, false_locks |
| `docs/TRACK_MEMORY.md` | 48 | Automatic track memory |
| `docs/TRACK_REFERENCE_COVERAGE.md` | 134 | Offline track-reference coverage |
| `docs/TRACK_WORLD_COVERAGE.md` | 152 | World-model reference coverage |
| `docs/TRACKS.md` | 68 | GT7Tracks integration |
| `docs/UI_MIGRATION_MAP.md` | 150 | UI redesign migration map (Phase 0) |
| `docs/USER_GUIDE.md` | 81 | New-user guide |
| `docs/VALIDATION.md` | 53 | Validation log — 2026-09-24 |
| `docs/windows-frozen-self-test.json` | 8 | JSON keys: backend, frontend, model_loaded, cars, audio_devices, frozen |
| `docs/windows-frozen-webview-test.json` | 1 | JSON keys: heading, native_renderer, ok |
| `frontend/package.json` | 1 | JSON keys: name, version, private, type, scripts, dependencies, devDependencies |
| `frontend/playwright.config.ts` | 2 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/scripts/check-arch.mjs` | 54 | Configuration, styles, tooling or third-party reference |
| `frontend/src/app/liveConnection.ts` | 48 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/app/liveStore.ts` | 41 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/app/router.ts` | 66 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/app/shortcuts.ts` | 64 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/app/store.ts` | 48 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/Broadcast.tsx` | 20 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/carImages.json` | 1 | JSON list, 574 entries |
| `frontend/src/Chart.tsx` | 10 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/colors.ts` | 11 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/control.ts` | 13 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/diagnostics.ts` | 9 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/engineer.ts` | 6 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/graphics.ts` | 31 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/group.ts` | 55 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/index.ts` | 10 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/platform.ts` | 33 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/sessions.ts` | 26 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/settings.ts` | 13 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/tracks.ts` | 11 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/api/training.ts` | 13 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/capabilities.generated.ts` | 88 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/channels.generated.ts` | 1205 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/channels.ts` | 25 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/clientErrors.ts` | 50 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/commands.generated.ts` | 416 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/commands.ts` | 62 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/graphics.generated.ts` | 577 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/http.ts` | 173 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/modules.ts` | 40 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/panels.ts` | 34 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/permissions.ts` | 34 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/stores/capabilitiesStore.ts` | 26 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/stores/index.ts` | 5 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/stores/liveSelectors.ts` | 15 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/stores/notificationsStore.ts` | 47 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/stores/servicesStore.ts` | 47 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/stores/sessionsStore.ts` | 28 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/types.ts` | 147 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/domain/units.ts` | 119 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/GroupControl.tsx` | 68 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/GroupGraphics.css` | 233 | Configuration, styles, tooling or third-party reference |
| `frontend/src/GroupGraphics.tsx` | 71 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/GroupStudio.tsx` | 49 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/LeagueBranding.tsx` | 25 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/LocalBrief.tsx` | 4 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/main.tsx` | 114 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/motion.ts` | 55 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/RaceDesk.tsx` | 107 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/RaceVisuals.tsx` | 65 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/RequestLibrary.tsx` | 11 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/RouletteWheel.tsx` | 18 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/style.css` | 140 | Configuration, styles, tooling or third-party reference |
| `frontend/src/TrackVisualizer.tsx` | 90 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/Training.tsx` | 165 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/ui/ErrorBoundary.tsx` | 41 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/ui/tokens.css` | 41 | Configuration, styles, tooling or third-party reference |
| `frontend/src/ui/tokens.ts` | 29 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/vite-env.d.ts` | 1 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/src/WheelDash.css` | 174 | Configuration, styles, tooling or third-party reference |
| `frontend/src/WheelDash.tsx` | 222 | Frontend source or browser test; see detailed brief for runtime wiring |
| `frontend/tsconfig.json` | 1 | JSON keys: compilerOptions, include |
| `frontend/vite.config.ts` | 3 | Frontend source or browser test; see detailed brief for runtime wiring |
| `IMPLEMENTATION_STATUS.md` | 102 | Phase 4/5: five new broadcast templates, ten sampleable styles |
| `INSTALL_ORANGE_PI.md` | 59 | Native Orange Pi installation |
| `Open desktop app.vbs` | 11 | Configuration, styles, tooling or third-party reference |
| `Open in browser.vbs` | 11 | Configuration, styles, tooling or third-party reference |
| `PERFORMANCE.md` | 32 | Performance and endurance validation |
| `PROTOCOL.md` | 41 | Protocol and source provenance |
| `pyproject.toml` | 3 | Configuration, styles, tooling or third-party reference |
| `README.md` | 127 | GT7 Race Engineer |
| `requirements-desktop.txt` | 30 | Configuration, styles, tooling or third-party reference |
| `requirements-lock.txt` | 26 | Configuration, styles, tooling or third-party reference |
| `requirements-voice.txt` | 3 | Configuration, styles, tooling or third-party reference |
| `run.py` | 69 | GT7 launcher. No Node.js or network service is needed at runtime.; main |
| `scripts/backup.py` | 7 |  |
| `scripts/bench_ingest.py` | 50 | Hot-path micro-benchmark: Runtime.ingest_datagram (decrypt+parse+sequence+consume).; make_packets, main |
| `scripts/build-track-references.py` | 45 | Build offline visual outlines from an explicitly downloaded, pinned source cache.; norm |
| `scripts/desktop-launch.sh` | 18 | Configuration, styles, tooling or third-party reference |
| `scripts/download-model.py` | 20 | Explicit small English model download. Never invoked by app startup. |
| `scripts/evaluate-track-captures.py` | 73 | Evaluate vendored capture paths only against models built from separate surveys.; normalise, main |
| `scripts/evaluate-track-recognition.py` | 157 | Reproducible world-model recognition probes; synthetic trials are labelled explicitly.; percentile, retained_size, main |
| `scripts/fetch-car-assets.py` | 33 | Build the offline car catalogue and manufacturer-image cache from pinned sources.; fetch, commit, norm, download |
| `scripts/gen-contracts.py` | 181 | Generate contract docs and frontend TypeScript from the Python registries.; ts_literal, md_table, collect, render_md, render_channels_ts, render_commands_ts, render_capabilities_ts, render_graphics_ts, outputs, main |
| `scripts/group_load_test.py` | 199 | Load-check for the Race Control / Broadcast group pipeline.; wait_ready, viewer_task, process_tree, tree_rss, tree_cpu_percent, run_case, main |
| `scripts/import-race-assets.py` | 42 | Import attributed circuit metadata, logos and official transparent car thumbnails.; fetch, main |
| `scripts/install-local-ai.py` | 37 | Install pinned, checksum-verified local AI assets. No telemetry is uploaded.; digest, download, main |
| `scripts/install-service.sh` | 25 | Configuration, styles, tooling or third-party reference |
| `scripts/install-ubuntu.sh` | 19 | Configuration, styles, tooling or third-party reference |
| `scripts/launch.ps1` | 3 | Configuration, styles, tooling or third-party reference |
| `scripts/launch.sh` | 5 | Configuration, styles, tooling or third-party reference |
| `scripts/package-linux.py` | 48 | Build an ARM64 Debian package on any build host, without root or dpkg.; tar, add |
| `scripts/package-windows.py` | 20 | Create a portable x64 Windows beta with app and browser launch options. |
| `scripts/soak.py` | 17 |  |
| `scripts/track-tool.py` | 687 | Build, refresh and report pinned offline GT7 world models (never imported at runtime).; normalise, refresh_gt7tracks, refresh, survey_layers, parse_gt7tracks_csv, segment_gt7tracks_laps, fit_stats, attach_gt7tracks_elevation, transfer_elevation, integrate_gt7tracks, catalogue_checks, integrate_local_captures, build, report ... |
| `scripts/verify-local-ai.py` | 30 | main |
| `scripts/verify-release.py` | 25 | Verify archive integrity, platform payloads and absence of runtime user data.; private |
| `scripts/verify-track-recording.py` | 110 | Read-only validation of a world reference and matcher against a recorded live lap.; main |
| `scripts/verify-windows-runtime.py` | 31 | Smoke-test the packaged Windows microphone worker without touching live data.; call |
| `tests/__init__.py` | 0 |  |
| `tests/e2e/app.spec.ts` | 130 | Frontend source or browser test; see detailed brief for runtime wiring |
| `tests/e2e/broadcast-expanded.spec.ts` | 25 | Frontend source or browser test; see detailed brief for runtime wiring |
| `tests/e2e/group.spec.ts` | 35 | Frontend source or browser test; see detailed brief for runtime wiring |
| `tests/e2e/league-demo.spec.ts` | 20 | Frontend source or browser test; see detailed brief for runtime wiring |
| `tests/e2e/recovery.spec.ts` | 15 | Frontend source or browser test; see detailed brief for runtime wiring |
| `tests/e2e/track-memory.spec.ts` | 21 | Frontend source or browser test; see detailed brief for runtime wiring |
| `tests/e2e/wheel-map.spec.ts` | 16 | Frontend source or browser test; see detailed brief for runtime wiring |
| `tests/fixture_generator.py` | 30 | Independent Salsa20/20 scalar fixture generator (test-only, not production).; stream, fixtures |
| `tests/fixtures/legacy_engineer.py` | 140 | FROZEN copy of engineer.py as it was before the declarative RuleSpec port.; Event, Scheduler, Rules |
| `tests/fixtures/packets.json` | 6 | JSON keys: A, B, ~, C |
| `tests/fixtures/replay_golden.json` | 40 | JSON keys: events, laps, pace, quality |
| `tests/test_api.py` | 119 | test_backend_import_has_no_filesystem_initialization, test_request_catalog_and_speaker_only_test, test_api_demo_record_report_export_replay, test_bad_bundle_and_csv, test_equal_timestamp_records_export_without_loss, test_track_selection_and_map_api, test_training_endpoints_exclude_special_stage_x_and_support_retry |
| `tests/test_architecture.py` | 207 | Dependency-direction and hygiene rules (docs/architecture). Parses imports with ast; no imports executed.; modules, imports, app_targets, test_layering_edges, test_core_imports_no_app_modules_and_no_web_framework, test_only_adapters_import_fastapi, test_no_import_cycles_among_app_modules, _top_level_names, _find_cycle, test_every_queue_and_deque_is_bounded, test_platform_checks_only_in_platform_adapter |
| `tests/test_battle_focus.py` | 193 | Phase 3 of the broadcast/spatial build (docs/AI_CONTEXT.md section 4):; route, build, make_group_with_battle, test_focus_sets_slots_and_adds_missing_graphics, test_focus_does_not_take_unless_requested, test_focus_with_take_publishes_the_program, test_focus_warns_when_a_graphic_slot_is_locked_to_an_entry, test_focus_rejects_a_battle_that_does_not_exist, test_focus_within_grace_period_of_a_just_ended_battle_still_works, test_focus_refuses_a_battle_ended_too_long_ago, test_spectator_cannot_focus_into_someone_elses_workspace, test_spectator_can_focus_into_their_own_shared_workspace |
| `tests/test_battles.py` | 317 | Phase 2 of the broadcast/spatial build (docs/AI_CONTEXT.md section 3): the; row, history_at_constant_gap, history_with_closing_gap, test_heat_formula_matches_hand_computed_value_for_a_known_input, test_clamp, test_two_scripted_battles_both_reach_hot, test_a_closing_pass_reaches_critical_within_5s_of_gap_dropping_below_half_second, test_overtake_keeps_the_same_battle_id_when_order_flips, test_alert_cooldown_suppresses_a_repeat_within_90s, test_dismiss_suppresses_alerts_but_keeps_the_battle_listed, test_lapped_cars_are_excluded_unless_include_lapping, test_classmate_pairs_are_included_beyond_simple_adjacency, test_pair_cap_is_respected, test_worker_tick_is_fast_at_sixteen_entries ... |
| `tests/test_broadcast.py` | 37 | circle, test_reference_and_gain_loss, test_paused_and_wrong_car_have_no_delta, test_manual_reference_is_applied_on_next_lap_and_reset_safely |
| `tests/test_clean_air.py` | 110 | Phase 8 of the broadcast/spatial build (docs/AI_CONTEXT.md section 12):; traffic, test_unavailable_without_any_shared_traffic, test_unavailable_without_known_pit_loss, test_no_fuel_margin_recommends_boxing_this_lap, test_clear_air_when_nobody_rejoins_nearby, test_recommends_staying_out_behind_slow_battling_traffic, test_options_never_extend_past_laps_actually_left_in_the_race, test_unknown_laps_left_does_not_zero_the_stuck_traffic_penalty, test_small_improvement_does_not_override_staying_at_k_zero |
| `tests/test_clean_air_wiring.py` | 77 | Phase 8 of the broadcast/spatial build (docs/AI_CONTEXT.md section 12):; runtime, connect_group, prime_fuel_and_pace, test_none_without_a_group_connection, test_none_when_connected_but_not_sharing_traffic, test_none_without_a_bound_track_length, test_computes_advice_when_everything_is_available, test_pit_command_appends_clean_air_text |
| `tests/test_commands.py` | 123 | Command catalogue: role × command matrix, and an end-to-end race-control flow through `/api/commands`.; principal, test_catalogue_is_consistent, test_role_command_matrix, test_pending_participants_hold_no_capabilities, test_race_control_flow_through_commands_with_audit, test_graphics_take_and_credential_commands |
| `tests/test_contracts_fresh.py` | 40 | Generated contract docs / frontend registries must match the live Python registries.; load_generator, test_generated_contracts_are_fresh, test_generation_is_deterministic, test_contract_content_is_complete |
| `tests/test_core.py` | 81 | store, test_laps_pause_restart_and_car_change, test_counter_restart_new_epoch, test_fuel_math_partial_lap, test_storage_recovery, test_scheduler_priority_mute_stale_workload, test_scheduler_bounds_and_dedup, test_low_fuel_noisy_and_cooldown, test_rules_pause_suppression, test_intents, test_config_validation_and_persistence, test_downsample_preserves_spike, test_approximate_comparison |
| `tests/test_core_foundation.py` | 332 | core/: registry, errors, lifecycle, events, features, permissions, commands, logging, config migrations.; run, test_registry_rejects_duplicates_and_serialises_without_callables, test_app_error_carries_status_and_maps_codes, Svc, test_lifecycle_orders_by_dependency_and_stops_in_reverse, test_one_failed_service_does_not_stop_others_and_dependents_are_marked, test_lifecycle_rejects_cycles_unknown_deps_and_duplicates, test_stuck_stop_is_bounded, test_event_bus_isolates_handler_failures, test_feature_flags_use_legacy_storage_and_overrides, test_performance_profile_auto_selection, test_role_capability_matrix, test_spectator_workspace_scope, _reg ... |
| `tests/test_domain_annotations_alerts.py` | 116 | test_annotation_fields_and_kinds, test_event_row_round_trip_through_real_store, test_decision_event_mapping, test_alert_center_bounds_dedupe_ack_expiry, test_alert_center_orders_by_severity_then_recency, test_rule_defs_registry_declarative_form, test_domain_and_storage_do_not_import_web_framework |
| `tests/test_domain_insights_training.py` | 84 | test_insight_from_real_improvements_output, test_insight_from_corner_report_item_shape, test_timing_models, lap, test_three_example_achievements_are_pure_evaluators, test_evaluators_do_not_mutate_input_and_registry_is_strict |
| `tests/test_driver_line.py` | 48 | runtime, feed, test_exit_clears_line_and_reference_and_menu_does_not_redraw, test_pause_or_loading_does_not_erase_or_extend_line, test_restart_or_car_change_starts_new_line, test_normal_lap_preserves_line_and_stale_does_not_extend |
| `tests/test_engineer_rules.py` | 147 | Declarative engineer rules: registry shape, per-rule positive/negative/noisy/stale cases and parity with the; load_legacy, frame, test_rule_registry_matches_documented_rules, test_legacy_oracle_has_identical_rules_table, run, test_low_fuel_positive_negative_noisy_and_cooldown, test_fuel_critical_is_priority_zero_and_needs_motion, test_pause_or_off_track_clears_active_conditions, test_c_field_rule_needs_the_feature_flag, test_pit_speed_uses_configured_region_and_limit, random_frames, test_declarative_rules_are_behaviourally_identical_to_the_legacy_implementation |
| `tests/test_foundation_api.py` | 227 | HTTP adapter for the foundation: services, features, capabilities, commands, diagnostics, safe mode.; make, pair, states, test_services_features_capabilities_and_health, test_state_snapshot_carries_services_derived_and_no_safe_mode, test_channels_endpoint_lists_reported_derived_and_unavailable, test_commands_catalogue_dispatch_codes_and_audit, test_settings_update_command_and_route_share_one_implementation, test_control_shim_maps_app_errors_to_http, test_read_only_calls_never_change_service_state, test_diagnostics_bundle_is_redacted, test_client_errors_are_rate_limited_and_logged_redacted, test_export_formats_registry_route, test_forced_safe_mode_blocks_heartbeat_mic_and_ai_until_confirmed ... |
| `tests/test_fuel_scenarios.py` | 102 | Phase 8 of the broadcast/spatial build (docs/AI_CONTEXT.md section 9.1):; prediction, lap, test_sufficient_fuel_reports_no_branches, test_unavailable_prediction_reports_unavailable, test_save_branch_feasible_within_max_percent, test_save_branch_infeasible_beyond_max_percent, test_splash_branch_requires_pit_loss_known, test_splash_omits_refuel_time_when_rate_unknown, test_splash_includes_refuel_time_when_rate_known, test_gap_check_prefers_save_when_splash_would_lose_a_position, test_gap_check_keeps_splash_when_it_holds_the_position, test_cost_per_litre_uses_measured_slope_from_six_clean_laps_with_enough_spread, test_cost_per_litre_falls_back_to_assumed_default_without_enough_laps, test_cost_per_litre_uses_configured_assumption_when_provided ... |
| `tests/test_graphics_registry.py` | 24 | test_registry_and_validated_models_agree, test_invalid_graphic_settings_cannot_reach_renderer, test_graphic_settings_supported |
| `tests/test_group.py` | 243 | Group admission and API boundary regression tests; no LAN listener or GT7 socket.; test_local_group_routes_are_authenticated_and_validate, test_group_admission_revocation_and_public_boundary, test_invitation_rotation_does_not_revoke_member, test_publishing_binding_privacy_delay_and_workspace_isolation, test_entry_reassignment_revokes_the_old_drivers_own_row_access, test_failed_storage_does_not_publish_instruction, test_native_browser_handshake_and_scoped_overlay, test_branding_upload_reencodes_and_rejects_unsafe_input, test_wrapped_zone_uncertainty_and_independent_cancellation, test_league_demo_is_synthetic_and_preserves_existing_group, test_clear_program_preserves_draft, test_new_graphic_templates_and_style_presets_are_valid, test_delayed_take_keeps_previous_program_until_timeline_reaches_change |
| `tests/test_group_graphics_contract.py` | 150 | Graphic template registry (group/graphics.py) and published state models (group/state_models.py).; test_legacy_graphics_table_is_unchanged, test_template_literal_tracks_the_registry, test_every_template_fulfils_the_contract, test_sharing_and_models_match_what_each_graphic_reads, test_public_templates_are_json_safe, test_public_registry_rows_keep_their_shape_and_gain_contract_fields, test_duplicate_template_ids_fail_loudly, build_state, test_published_snapshot_declares_exactly_the_keys_the_service_publishes, test_traffic_and_entry_shapes_match_the_models, test_state_model_groups_partition_the_frame_sensibly |
| `tests/test_group_history.py` | 238 | Phase 1 of the broadcast/spatial build (docs/AI_CONTEXT.md 2.1-2.5): race; test_distance_history_time_at_interpolates_and_clamps_to_range, test_distance_history_decimates_below_min_step, test_distance_history_clamps_small_backward_noise_but_resets_on_a_big_jump, test_distance_history_evicts_samples_older_than_max_age, test_interval_matches_a_known_constant_speed_gap_within_50ms, test_interval_is_none_when_ahead_history_does_not_cover_the_distance, test_gap_uncertainty_combines_both_clocks_in_quadrature, test_is_lapped_flags_beyond_half_a_lap_only, test_common_timeline_uses_offset_when_known_else_falls_back_with_extra_uncertainty, test_detect_heuristic_requires_sustained_slow_speed_near_start_finish, test_detect_prefers_a_surveyed_pit_lane_when_present, drive_pit_stop, test_pit_tracker_records_a_completed_stop_on_exit_after_minimum_duration, test_pit_tracker_ignores_a_brief_slow_roll_through ... |
| `tests/test_group_migrations.py` | 162 | Group document schema versions and upgrades (group/migrations.py).; old_league, insert_raw, raw_payload, test_documents_without_schema_count_as_schema_1_and_upgrade, test_upgrade_is_idempotent_and_ids_are_deterministic, test_ensure_team_ids_keeps_existing_and_survives_rename, test_group_snapshot_and_override_teams_upgrade, test_asset_documents_get_metadata_defaults, test_unknown_types_newer_schemas_and_gaps, test_repository_upgrades_on_load_and_writes_back_lazily, make_service, test_service_loads_an_old_database_and_name_keyed_lookups_still_work, test_new_teams_from_the_editor_get_a_team_id_on_save, test_upload_records_asset_metadata_and_rejects_unknown_kind |
| `tests/test_hands_free.py` | 83 | test_continuous_worker_delivers_two_requests_without_button, test_microphone_discards_speaker_echo_and_old_results, test_hands_free_allows_reply_and_gates_input, test_paused_loading_and_off_track_samples_do_not_accumulate, test_heartbeat_bounds |
| `tests/test_live_analysis.py` | 41 | sample, test_reception_constant_fields_and_gap, test_reception_no_data_and_source_change, test_analysis_derivative_and_bounded_window, test_analysis_pause_missing_and_braking |
| `tests/test_local_ai.py` | 70 | runtime, test_stale_and_paused_briefs_do_not_present_advice, test_bounded_evidence_preserves_fuel_priority, test_model_failure_keeps_calculated_summary, test_memory_pressure_prevents_inference, test_disabled_model_never_starts, test_unmark_pit_clears_reminders_only, test_successful_model_finishes_ready |
| `tests/test_modules_engineer.py` | 115 | Module registry consistency, the EngineerService boundary and the alert centre wiring.; runtime, test_modules_reference_only_things_that_exist, test_every_service_and_command_belongs_to_a_module, test_module_ids_are_unique_and_public_listing_has_no_callables, test_engineer_ask_returns_a_typed_response_with_legacy_fields, test_engineer_ask_goes_through_the_same_path_as_typed_commands, test_engineer_navigation_becomes_a_recommended_action, test_engineer_brief_uses_evidence_summary_when_local_ai_is_off, test_rule_events_become_alerts_and_can_be_acknowledged, test_alert_sources_and_severity_mapping |
| `tests/test_packaging_imports.py` | 45 | PyInstaller collects `backend` with --collect-submodules, so every module must import cleanly on a machine; all_modules, test_every_backend_module_imports, test_new_packages_are_discoverable_by_the_packager, test_packaged_data_files_exist, test_optional_dependencies_are_not_imported_at_module_load |
| `tests/test_permissions_matrix.py` | 224 | Role x action -> allow/deny matrix for the group API.; make_service, World, world, status_of, test_publish_telemetry_matrix, test_lap_event_matrix, test_driver_response_matrix, test_workspace_edit_matrix, test_workspace_take_matrix, test_workspace_overlay_credential_matrix, test_focus_battle_matrix, test_create_workspace_matrix, test_host_local_admin_has_no_workspace_restrictions, test_workspace_from_another_group_is_denied ... |
| `tests/test_projection.py` | 275 | Phase 5 of the broadcast/spatial build (docs/AI_CONTEXT.md section 5): the; test_stops_needed_zero_when_fuel_already_covers_the_distance_with_reserve, test_stops_needed_computes_deficit_and_stop_count, test_stops_needed_multiple_stops_for_a_small_tank, test_stops_needed_none_without_burn_rate_laps_left_or_fuel, test_stop_cost_is_zero_stops_free_and_none_without_pit_loss, test_stop_cost_omits_refuel_time_when_rate_unknown_rather_than_blocking, test_stop_cost_includes_pit_loss_and_refuel_time, test_pit_window_bounds_for_a_one_stop_car, test_pit_window_none_without_burn_rate, entry, test_project_returns_none_for_non_race_formats, test_project_no_stops_needed_reports_a_summary_not_an_order, test_project_orders_by_net_gap_and_reports_position_change, test_project_marks_close_calls_within_combined_uncertainty ... |
| `tests/test_protocol.py` | 93 | test_independent_encrypted_fixtures, test_independent_salsa_known_zero_vector, test_bad_lengths, test_magic_and_finite, test_sequence, test_short_packet_extension_reset, test_pinned_header_layout_independent_sequential_offsets, test_invalid_input_has_classified_error, test_crypto_failure_classified_and_byteslike_supported, test_nonfinite_all_float_offsets_is_json_safe, test_signed_raw_timing_and_packet_id_preserved, test_random_datagrams_never_yield_nonfinite_json |
| `tests/test_protocol_v2.py` | 512 | Group protocol v2: envelope, handshake, reliable delivery, snapshot sharing. No LAN sockets.; test_protocol_constants_come_from_core, test_encode_decode_roundtrip, test_encode_rejects_unknown_type_and_bad_payload, test_legacy_v1_messages_convert_to_envelopes_and_back, test_v1_and_v2_carry_the_same_payload, test_size_cap_applies_to_text_bytes_and_dicts, test_malformed_messages_are_rejected, test_unknown_type_and_unsupported_version, test_type_allowlist_per_role, test_every_existing_message_type_is_registered, test_codec_speaks_v1_until_upgraded_and_maps_acks, test_negotiate_v1_client_without_hello, test_negotiate_v2_client_picks_highest_common, test_negotiate_incompatible_client ... |
| `tests/test_recovery.py` | 59 | test_invalid_settings_can_launch_without_deleting_original, test_recovery_preserves_data_and_origin_access, test_invalid_hosting_edit_keeps_existing_mode_and_stop_is_recoverable, test_bad_http_address_rejected_before_save, test_malformed_origins_are_rejected_without_overwriting_settings |
| `tests/test_reliability.py` | 72 | test_each_rule, test_spatial_alignment_and_divergence, test_crash_recovery_and_bounded_queue, test_database_full_keeps_writer_alive, test_replay_deterministic_rules |
| `tests/test_requests.py` | 63 | runtime, test_catalog_is_one_hundred_distinct_requests, test_each_request_has_three_distinct_replies, test_live_values_stale_gating_and_unknowns, test_resume_enables_speech_and_navigation_is_valid, test_speaker_generates_pcm_and_uses_selected_device, test_speaker_reports_synthesis_failure_and_zero_volume |
| `tests/test_runtime_foundation.py` | 270 | Runtime wiring of the bus, lifecycle events, replay determinism, crash recovery and audio privacy.; runtime, feed, test_subscribers_are_wired_in_the_original_order, test_failing_subscriber_is_isolated_and_counted_as_pipeline_error, test_demo_replay_paths_survive_a_subscriber_failure, test_lifecycle_events_are_emitted_on_the_bus, test_source_switch_emits_source_changed_and_resets_derived_state, test_snapshot_serves_derived_channels_and_services, test_ui_hz_is_lowered_only_in_low_power_profile, summarize, bus_sequence, test_replaying_the_same_frames_gives_identical_bus_events_laps_and_report, test_replay_source_reproduces_the_recorded_laps, test_recorder_recovers_after_abrupt_kill_with_bounded_loss ... |
| `tests/test_spatial_coaching.py` | 178 | Phase 7 of the broadcast/spatial build (docs/AI_CONTEXT.md section 8):; build_lap, reference_profile, test_spatial_lap_time_at_interpolates_and_reports_none_outside_visited_range, test_corner_for_matches_the_braking_zone_and_reports_unassigned_otherwise, test_corner_label_uses_surveyed_name_or_turn_number_for_auto, test_live_braking_tracker_produces_an_episode_with_position, test_live_braking_tracker_ignores_a_brief_low_speed_brake_tap, test_corner_report_detects_a_later_brake_onset_with_correct_sign_and_cause, test_corner_report_gain_case_uses_keep_that_wording, test_corner_report_skips_corners_below_the_minimum_loss_threshold, test_corner_report_returns_nothing_for_a_different_layout, test_corner_report_never_mentions_wear_or_grip_in_any_text |
| `tests/test_steward_cues.py` | 177 | Phase 4 of the broadcast/spatial build (docs/AI_CONTEXT.md section 6):; identity, item, test_cue_text_templates_match_the_spec_table, test_enqueue_skips_private_and_unlisted_kinds, test_enqueue_dedupes_same_decision_and_status, test_enqueue_treats_a_status_change_as_a_new_cue, test_active_cue_plays_cues_back_to_back, test_higher_priority_cue_preempts_and_cuts_the_current_one_short, test_lower_priority_cue_does_not_preempt, build, test_group_service_public_decision_produces_an_overlay_cue, test_group_service_private_decision_produces_no_cue, test_group_service_cancel_removes_a_cue, test_group_service_pausing_auto_steward_suppresses_new_cues ... |
| `tests/test_storage_audit.py` | 68 | store, test_sink_writes_row_through_writer_thread, test_sink_fills_defaults_truncates_and_validates, test_sink_raises_when_queue_is_full, test_dispatch_audits_through_ctx |
| `tests/test_storage_cache.py` | 82 | store, test_put_get_roundtrip_and_key_parts, test_stale_after_new_samples, test_eviction_keeps_under_bound_lru, test_invalidate_clear_and_atomic_writes |
| `tests/test_storage_exports.py` | 109 | store, run, test_registry_lists_formats, test_bundle_v1_is_the_current_exporter_and_round_trips, test_csv_header_units_projection_and_lap_filter, test_csv_neutralises_formula_cells, test_jsonl_full_and_projected, test_html_report_and_errors, test_import_validation_rejects_bad_input |
| `tests/test_storage_layout.py` | 62 | test_layout_matches_what_modules_create, test_ensure_creates_only_dirs_inside_root, test_describe_is_json_safe_and_relative, test_running_marker |
| `tests/test_storage_migrations.py` | 117 | schema_of, make_old_db, test_old_database_upgrades_in_place, test_upgrade_is_idempotent_and_matches_fresh_schema, test_sql_files_mirror_inline_migration, test_session_list_uses_index_not_samples, test_audit_and_annotation_jobs, test_bounded_queue_semantics_unchanged |
| `tests/test_storage_repositories.py` | 135 | seed_session, store, repo, test_list_is_index_only_paged_and_filtered, test_get_has_laps_and_report_but_no_samples, test_samples_projection_paging_and_lap_filter, test_lap_series_keeps_peaks, test_meta_protect_archive_and_purge_rules, test_annotations_passthrough |
| `tests/test_storage_retention.py` | 42 | session, test_age_selection_oldest_first, test_protected_active_archived_favourites_never_selected, test_size_cap_archives_oldest_until_under_cap, test_bad_dates_are_skipped_not_fatal |
| `tests/test_telemetry_bus.py` | 183 | frame_at, Clock, test_every_mode_and_order_and_critical_first, test_rate_mode_decimates_by_frame_time, test_rate_mode_restarts_when_clock_goes_backwards, test_latest_mode_slot_and_freshness, test_subscription_validation_and_cancel, test_handler_exception_never_breaks_others, test_error_logging_rate_limited, test_errors_logged_per_subscriber, test_events_delivery_filter_and_isolation, test_event_kind_constants, test_metrics_and_timing_sampling, test_duration_window_is_bounded ... |
| `tests/test_telemetry_derived.py` | 261 | frame_of, demo_frame, pedal_frame, test_expected_derived_set_registered, test_duplicate_and_public, test_delta_is_external, test_speed_kmh_on_fixture, test_wheel_speed_and_slip_on_demo, test_slip_matches_parser_ratio, test_slip_and_wheel_values_from_locked_wheel, test_slip_suppressed, test_wheel_speed_implausible_radius_is_none, test_missing_dependency_gives_none, test_steering_rate_variants ... |
| `tests/test_telemetry_frame.py` | 112 | test_every_field_registered, test_normalised_keys_registered_and_ids_match_values, test_experimental_flags, test_unavailable_channels_present_with_reason, test_channel_vocabulary, test_public_serialisation_has_no_callables, test_duplicate_registration_detected, test_channel_is_frozen_and_availability_by_variant, test_frame_from_sample, test_from_sample_is_cheap |
| `tests/test_telemetry_scenarios.py` | 143 | fingerprint, test_registry_lists_all_scenarios, test_deterministic_and_synthetic, test_normal_laps_cross_lap_boundary, test_lap_transition, test_fuel_burn_and_refuel_seen_by_derived_engine, test_braking_zones_have_three_brake_applications, test_packet_loss_burst_produces_gaps, test_out_of_order_produces_reorders, test_stream_stale_has_ten_second_silence, test_session_end_finishes_with_none_after_pause, test_variant_switch_A_to_C, test_unknown_scenario_and_source_protocols |
| `tests/test_telemetry_units.py` | 77 | test_speed_round_trip, test_speed_known_values, test_temp_round_trip, test_fuel_round_trip, test_distance_round_trip, test_pressure_round_trip, test_none_passes_through, test_unknown_units_raise, test_labels, test_spoken_speed_both_systems |
| `tests/test_track_gt7tracks.py` | 163 | GT7Tracks ingest: parser traps, lap segmentation, fusion gate and elevation transfer.; circle_points, write_csv, test_column_order_trap_elevation_is_the_fourth_column, test_duplicate_stationary_and_jump_rows_are_dropped, test_non_finite_and_malformed_rows_are_skipped, test_unexpected_column_layout_is_rejected, test_lap_segmentation_closes_on_anchor_return_and_gates_by_length, test_lap_failing_the_length_gate_is_rejected, test_pit_garage_excursion_is_discarded_when_an_existing_model_is_given, test_fit_stats_reports_median_and_p95_and_none_when_too_sparse, test_elevation_attach_medians_and_smooths_then_transfer_stays_within_5m |
| `tests/test_track_memory.py` | 131 | route, drive, clean, test_unknown_confirm_restart_return_and_exit, test_direction_partial_and_identical_geometry, test_reverse_can_match_separate_saved_layout, test_gaps_preserve_saved_map_and_demo_cannot_write, test_atomic_failure_history_restore_and_legacy, test_training_corpus_logs_confirmed_and_matched_laps, test_similarity_no_stretch_or_reflection_and_rate_limit, test_offline_coverage_and_stable_ids, test_group_freezes_library_revision, test_local_api_reference_confirm_and_restore |
| `tests/test_track_service.py` | 312 | Phase 0 of the broadcast/spatial build: TrackService wiring (docs/AI_CONTEXT.md).; circle_model, install_override, drive, test_load_user_models_skips_malformed_and_wrong_frame_files, test_service_locks_on_override_and_project_returns_none_until_locked, test_projected_s_is_monotonic_and_wraps, test_direct_project_call_cost_is_measured_not_asserted, test_manual_select_is_immediately_authoritative, test_reset_clears_lock_but_service_can_relock, test_snapshot_reports_none_source_when_unlocked_and_v3_when_locked, test_track_progress_adapter_matches_projection_contract, test_group_service_prefers_v3_model_over_legacy_when_available, test_group_service_v3_sync_is_a_noop_once_matched, test_group_service_ignores_manual_map_even_when_v3_available ... |
| `tests/test_track_world.py` | 196 | World-frame model, storage and recognizer invariants independent of a PS5.; circle, drive, test_world_model_retains_frame_and_lossless_legacy, test_projection_wrap_direction_and_bridge_elevation, test_direction_lock_unknown_and_manual_override, test_shared_geometry_does_not_guess_or_lock_early, test_teleport_and_provenance_clear_lock, test_storage_migration_is_lossless_and_failure_atomic, test_pack_checksum_merge_history_and_provenance, test_layer_validation_and_independent_history, test_fusion_labels_observed_envelope_and_rejects_reverse, test_streamed_bundle_ids_and_raw_world_coordinates, test_invalid_frame_and_document_hash |
| `tests/test_tracks.py` | 39 | lap, test_complete_lap_saved_but_partial_not_saved, test_pause_and_teleport_do_not_save, test_import_boundaries_and_persistence, test_catalogue_assets_exist |
| `tests/test_traffic_sharing.py` | 123 | Phase 8 of the broadcast/spatial build (docs/AI_CONTEXT.md section 12):; route, build_group, test_traffic_is_none_for_drivers_by_default, test_traffic_is_none_for_non_driver_principals_even_when_shared, test_traffic_is_basic_only_and_present_for_drivers_when_shared, test_traffic_battle_state_reflects_current_battles, test_public_projection_exposes_pit_loss_seconds_but_never_raw_fuel |
| `tests/test_training.py` | 162 | drive, test_opening_partial_lap_is_discarded_and_full_laps_are_saved, test_short_segments_below_minimum_points_are_not_saved, test_paused_or_offtrack_samples_are_ignored, test_inactive_recorder_ignores_samples, test_saved_lap_count_and_status, test_goal_is_incomplete_below_target_and_complete_once_reached, test_list_progress_only_includes_layouts_with_saved_laps, test_preview_points_drain_on_status_read, test_discard_current_lap_drops_unsaved_points_but_keeps_saved_laps, test_discard_current_lap_is_a_noop_when_not_recording, test_restart_layout_deletes_saved_captures_unless_it_is_the_active_one |
| `tests/test_tyre_heat.py` | 195 | Phase 6 of the broadcast/spatial build (docs/AI_CONTEXT.md section 7):; drive, test_no_signal_below_the_driving_speed_threshold, test_positive_case_a_sustained_ramp_produces_a_rising_rate_and_anomaly, test_negative_case_normal_cyclical_corner_heating_cancels_with_a_track_position_baseline, test_noisy_case_random_jitter_does_not_produce_a_false_rate, test_stale_or_paused_samples_produce_no_signal, hot_result, cool_result, warmed_up_rules, test_tyre_heat_fires_after_sustained_entry_and_respects_persist, test_tyre_heat_per_tyre_and_global_cooldowns, test_tyre_heat_suppressed_during_warmup_laps, test_tyre_heat_suppressed_for_one_lap_after_a_detected_pit_exit, test_tyre_heat_suppressed_with_fewer_than_four_finite_tyres ... |
| `tests/test_udp.py` | 92 | Live UDP integration: no PS5 or synthetic demo shortcut is used here.; eventually, free_port, test_actual_udp_heartbeat_parse_record_bad_packets_recover, test_sender_filter_and_parser_failure_diagnostics, test_network_settings_reopen_receiver |
| `THIRD_PARTY_NOTICES.md` | 56 | Third-party notices |
| `TROUBLESHOOTING.md` | 34 | Troubleshooting |
| `vendor/gt7-udp/GT7UDPParser.cpp` | 154 | Configuration, styles, tooling or third-party reference |
| `vendor/gt7-udp/GT7UDPParser.h` | 144 | Configuration, styles, tooling or third-party reference |
| `vendor/gt7-udp/README.md` | 800 | Gran Turismo 7 UDP / Library for use on ESP 32 / ESP8266 devices |
| `VOICE_COMMANDS.md` | 112 | Hands-free operation |
| `windows_app.py` | 112 | Windows desktop/browser launcher. PyInstaller entry point; no console required.; use_project_python, main |
