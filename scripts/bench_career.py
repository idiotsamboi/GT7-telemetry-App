"""Synthetic finalized-session/writer benchmark; never touches user recordings.

Run separately from test suites. Measures bounded event enqueue and transactional
career evaluation/acknowledgement, including writer batching delay. Hardware is
not involved, and these timings do not establish PS5 recording reliability.
"""
import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import Config
from backend.app.runtime import Runtime
from backend.app.storage import Store
from backend.app.telemetry import demo_sample


async def run():
    latencies = []
    with tempfile.TemporaryDirectory() as directory:
        config = Config(directory)
        config.save({'speech_enabled': False, 'hands_free': False})
        store = Store(Path(directory)/'bench.db')
        runtime = Runtime(config, store)
        runtime.track.locked = object()
        runtime.track.locked_layout_id = 'synthetic-benchmark-layout'
        await runtime.career.start()
        for iteration in range(5):
            runtime.sessions.manual_ended = False
            for i in range(91):
                sample = demo_sample(i/10, i)
                sample.provenance = 'live'  # explicit test fixture, temporary isolated database only
                sample.values.update(lap=i//30+1, last_ms=3000+iteration*10, car_id=42, flags=1)
                t = time.perf_counter()
                runtime.sessions.consume(sample)
                latencies.append((time.perf_counter()-t)*1000)
            t = time.perf_counter()
            runtime.sessions.end()
            await runtime.career.queue.join()
            print(json.dumps({'iteration': iteration, 'finalization_ack_ms': (time.perf_counter()-t)*1000}))
        health = store.health()
        result = {'source': 'isolated_synthetic_fixture', 'sessions': 5, 'samples': len(latencies),
                  'session_consume_p50_ms': statistics.median(latencies),
                  'session_consume_p95_ms': sorted(latencies)[int(len(latencies)*.95)],
                  'career_last_job_ms': runtime.career.last_duration_ms,
                  'queue_drops': health['application_drops'], 'failed_rows': health['failed_rows'],
                  'pending_jobs': runtime.career.queue.qsize(), 'career_errors': runtime.career.failed_events}
        await runtime.career.close()
        store.close()
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    args = parser.parse_args()
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
