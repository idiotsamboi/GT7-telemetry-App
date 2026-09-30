"""Hot-path micro-benchmark: Runtime.ingest_datagram (decrypt+parse+sequence+consume).

Usage: python scripts/bench_ingest.py [--frames 20000] [--output PATH]
Compare before/after any change to the receive -> parse -> record path
(budget: no more than 5% regression; see docs/architecture/PERFORMANCE_BUDGETS.md).
"""
import argparse, json, statistics, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import Config
from backend.app.storage import Store
from backend.app.runtime import Runtime
from tests.fixture_generator import fixtures

def make_packets(n):
    # re-encrypt one variant-A fixture with increasing packet ids (sequence guard needs monotonic ids)
    import struct
    from Crypto.Cipher import Salsa20
    from backend.app.telemetry import decrypt_datagram, KEY, XOR
    raw = bytes.fromhex(fixtures(1)['A']); plain, _ = decrypt_datagram(raw)
    seed = struct.unpack_from('<I', raw, 0x40)[0]; nonce = struct.pack('<II', seed ^ XOR['A'], seed)
    out = []
    for i in range(n):
        b = bytearray(plain); struct.pack_into('<I', b, 112, i + 1)
        c = bytearray(Salsa20.new(key=KEY, nonce=nonce).encrypt(bytes(b))); struct.pack_into('<I', c, 0x40, seed); out.append(bytes(c))
    return out

def main():
    p = argparse.ArgumentParser(); p.add_argument('--frames', type=int, default=20000)
    p.add_argument('--repeat', type=int, default=3); p.add_argument('--output')
    a = p.parse_args()
    runs = []
    for _ in range(a.repeat):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(d); cfg.save({**cfg.settings.model_dump(), 'ps5_ip': '127.0.0.1', 'speech_enabled': False, 'hands_free': False})
            store = Store(Path(d) / 'bench.db'); r = Runtime(cfg, store)
            packets = make_packets(a.frames)
            lat = []; start = time.perf_counter(); addr = ('127.0.0.1', 33740)
            for i in range(a.frames):
                pkt = packets[i]
                t0 = time.perf_counter(); r.ingest_datagram(pkt, addr, time.monotonic()); lat.append((time.perf_counter() - t0) * 1000)
            elapsed = time.perf_counter() - start
            store.flush(); store.close()
            lat.sort()
            runs.append({'frames': a.frames, 'accepted': r.received, 'frames_per_s': a.frames / elapsed, 'p50_ms': lat[len(lat) // 2], 'p95_ms': lat[int(.95 * len(lat))], 'p99_ms': lat[int(.99 * len(lat))]})
    best = min(runs, key=lambda x: x['p95_ms'])
    result = {'runs': runs, 'best_p95_ms': best['p95_ms'], 'median_p50_ms': statistics.median(x['p50_ms'] for x in runs), 'python': sys.version.split()[0], 'platform': sys.platform}
    print(json.dumps(result, indent=2))
    if a.output: Path(a.output).write_text(json.dumps(result, indent=2))
main()
