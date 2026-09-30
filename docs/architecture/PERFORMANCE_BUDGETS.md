# Performance budgets

Targets for the hot paths, what has actually been measured, and how to measure again. A budget with no number in the
"measured" column has not been measured; nothing here is estimated. Dev machine: Windows 11, Python 3.12, 8 logical CPUs, shared
with other work while measuring (numbers are noisy; read the caveats).

## 1. Budgets

| # | budget | status | evidence |
|---|---|---|---|
| 1 | Ingest plus bus fan-out: `Runtime.ingest_datagram` at most 0.5 ms p95 on the dev PC | MEASURED, target not met at baseline | Baseline (before the bus refactor, 20 000 frames, 3 runs): p50 0.32 to 0.37 ms, p95 0.58 to 0.74 ms, 2.2 to 2.6 k frames/s (`bench_baseline.json`). The 0.5 ms figure was already exceeded before this pass on the loaded dev PC, so it stays a target; the enforceable guard is relative (row 2) |
| 2 | Regression guard: no more than 5 percent slower than baseline on the same machine | MEASURED, borderline | Interleaved A/B on one `Runtime`, bus fan-out plus `FrameMeta` against the old direct call sequence: +1.0 percent p50, about +5 percent p95, +2.8 percent mean |
| 3 | Derived channels at 20 Hz add no measurable ingest cost | MEASURED | about 0 measurable in the bench; 39 us per frame when evaluated. `TelemetryFrame.from_sample` about 4 us; `publish` to 10 no-op subscribers about 6 us |
| 4 | Recorder: zero drops at 60 Hz for 30 minutes | PARTLY MEASURED | Two 20 s synthetic runs at 60 Hz: 0 drops, 0 failed rows, queue peak 14 and 6 of 8192. The 30 minute run has NOT been done. See section 3 |
| 5 | `/ws` snapshot build at most 2 ms | MEASURED, build within budget, serialization not | `snapshot()` build p50 0.28 to 0.35 ms, p95 0.5 to 1.6 ms. Serializing a full-history payload costs about 3 ms p50 per client per frame (section 4) |
| 6 | Group snapshot served from a shared cache | VERIFIED FUNCTIONALLY, NOT TIMED | `SnapshotCache` (`group/snapshots.py`): entries keyed by view filter, delay, revision and frame; 200 ms max age; 64 entries. Tests assert N subscribers with the same view cause one computation and that different views do not share. No latency comparison has been made |
| 7 | Frontend commits at most 1 per second when idle | NOT YET MEASURED | no React profiler run exists |
| 8 | No unbounded memory growth over 2 hours | NOT YET MEASURED | Structural guard only: `tests/test_architecture.py` requires every `deque` and `Queue` to be bounded. No 2 h soak has been run, and `peak_rss_bytes` is `None` on Windows (`health_loop` imports the POSIX-only `resource` module), so RSS is not visible in `/api/diagnostics` here |

## 2. Ingest benchmark (`scripts/bench_ingest.py`)

What it measures: `Runtime.ingest_datagram` for pre-encrypted packets: decrypt, parse, sequence guard, every bus subscriber, recorder queue.
A fresh temp data dir and `Store` per repeat; speech and microphone off.

```
.venv/Scripts/python.exe scripts/bench_ingest.py --frames 20000 --repeat 3 --output <scratch>/bench_now.json
```

Read `median_p50_ms` and `best_p95_ms` (best of the repeats by p95); each run lists `p50_ms`, `p95_ms`, `p99_ms`, `frames_per_s`.
Compare with `docs/architecture/bench_baseline.json` (best p95 0.585 ms, median p50 0.336 ms).

How to compare honestly on this machine:

- Run on an idle machine; close editors and other test runs. Repeat at least three times.
- Run-to-run spread on the shared dev PC is larger than the 5 percent guard. Runs taken during the refactor spanned best p95 0.85 to
  1.04 ms (`bench_after_1.json`, `bench_after_2.json`), and a run taken while writing this document on a busy machine gave p50 0.67 to 1.39 ms and
  p95 1.5 to 6.1 ms. Do not compare those with the baseline.
- To resolve a small effect, alternate the two code versions in the same process or back to back (A B A B) and compare means and
  percentiles per pair. That is how the +1.0 percent p50 and +5 percent p95 figures in row 2 were obtained; the A/B harness is not
  kept in the repository.

Row 2 is at the edge of the guard for p95. Treat any further per-frame cost on the ingest path as a regression.

## 3. Soak (`scripts/soak.py`)

Feeds demo frames to `Runtime.consume` at `--rate` (default 60), records the `consume` latency, then ends the session and reports storage
health.

```
.venv/Scripts/python.exe scripts/soak.py --seconds 20 --rate 60 --output <scratch>/soak20.json
.venv/Scripts/python.exe scripts/soak.py --hours 0.5 --rate 60 --output <scratch>/soak30m.json      # the 30 minute budget run; not done yet
```

Always pass `--output`: the default is `docs/benchmark.json`, a committed file. `--hours` overrides `--seconds`.
Fields to read: `application_drops`, `failed_rows` and `written` under `storage`, `queue_peak`, `samples_per_s` (should be near `--rate`),
`ingest_p95_ms` (this is `consume` only, sampled while paced), `cpu_seconds`.

Measured today (two 20 s runs, machine busy with other work): 1200 and 1053 samples fed, 0 application drops, 0 failed rows,
queue peak 14 and 6. The second run reached only about 53 Hz and `ingest_p95_ms` was 20.3 and 9.6 ms, so those latency figures reflect a
loaded machine and are not a valid measurement of the code; the zero-loss result is the usable part. An older committed run
(`docs/benchmark.json`, 2026-09-23, before this pass): 12 000 samples, 0 drops, queue peak 61, `ingest_p95_ms` 1.27.

## 4. `/ws` snapshot cost

Method: build a `Runtime` as `tests/test_runtime_foundation.py` does (demo source, speech off), feed 600 frames through `consume`, 20
warm-up calls, then time 200 calls of `runtime.snapshot()` and of `json.dumps` on its result with `time.perf_counter`. Two setups, each run
twice; per-call figures in ms.

| setup | payload | `snapshot()` p50 / p95 | `json.dumps` p50 / p95 | both p50 / p95 |
|---|---|---|---|---|
| after 600 frames, background loops not running (history empty) | 6.2 KB | 0.34 to 0.35 / 1.3 to 1.6 | 0.36 / 0.9 to 1.3 | 0.73 to 0.78 / 2.4 to 2.7 |
| plus 600 history entries and 600 trace points (their caps) | 64 KB | 0.28 / 0.48 | 2.9 / 5.0 | 3.2 / 5.3 |

The history (`engine_loop`, 10 Hz) and trace are filled by the loops, which the test setup does not run, so the second row approximates a live
payload by appending synthetic entries to the two deques. Findings: building the snapshot is well inside the 2 ms budget; serializing it is
the expensive part. `api.py` calls `ws.send_json(runtime.snapshot())` per client per tick, so each connected browser pays build plus
serialization at `effective_ui_hz` (12 Hz default). One browser is comfortable; the cost scales linearly with tabs. Sharing one serialized
frame across `/ws` clients is a possible optimisation (the group side already shares snapshots); it has not been done.

Group listener load (older, before the snapshot cache; `docs/group-load-test-validation.json`, 2026-09-27, 8 CPUs, 4 demo drivers, 20 s
each): 1 viewer 12 percent of one core average, 8 viewers 41 percent, 32 viewers 129 percent; snapshot interval p95 281, 344 and 406 ms; 0
recording drops. Not re-run after the cache landed; `scripts/group_load_test.py` re-measures it (needs `psutil websockets httpx`).

## 5. Performance profiles (ADR 0010)

`Settings.performance_profile` is `AUTO`, `DESKTOP` or `LOW_POWER`. `core/platform.resolve_performance_profile` maps `AUTO` to `LOW_POWER`
when the CPU count is 4 or fewer or total RAM is 4 GB or less, else `DESKTOP`; an explicit value wins. `Runtime.performance_profile` is
resolved at start and again on every settings update.

The rule is that a profile may change only what is shown or sent, never what is recorded. The recorder queue, batch size, loss accounting,
derived-channel maths and lap, fuel and timing accuracy are profile-independent, so recordings from any machine are comparable.

What is implemented: `Runtime.effective_ui_hz()` returns `min(Settings.ui_hz, UI_HZ_LOW_POWER)` (8) under `LOW_POWER`, else `Settings.ui_hz`
(default 12, allowed 2 to 20). The `/ws` loop sleeps `1 / effective_ui_hz()` between pushes, or `1/4` s when the runtime is `degraded`
(`health_loop` sets it after 3 s of queue backlog above 4096, loop lag above 200 ms, or SoC temperature above 80 C, and clears it after 20 s of
health). A user-set `ui_hz` below 8 is respected. Tests: `tests/test_runtime_foundation.py::test_ui_hz_is_lowered_only_in_low_power_profile`,
`tests/test_core_foundation.py::test_performance_profile_auto_selection`.

Not implemented: the ADR also allows lowering group publish Hz (`GROUP_PUBLISH_HZ_LOW_POWER` = 5 exists in `core/defaults.py` but nothing reads
it), shortening history, reducing ambient motion and deferring heavy analysis to lap or session end. Only the UI rate is wired.

## 6. Where the numbers live

- `docs/architecture/bench_baseline.json`: the pre-refactor ingest baseline.
- `docs/architecture/bench_after_1.json`, `bench_after_2.json`: post-refactor runs (noisy, see section 2).
- `docs/benchmark.json`: older soak (overwritten by `soak.py` without `--output`).
- `docs/group-load-test-validation.json`: older group load run.

When a budget is measured, add the method and date to its row above; if it cannot be measured on the dev PC, say why.
