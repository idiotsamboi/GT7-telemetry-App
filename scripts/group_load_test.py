"""Load-check for the Race Control / Broadcast group pipeline.

Standalone diagnostic, not part of the shipped application. Starts the real
app as a subprocess, enables the LAN group listener, runs the built-in
synthetic league demo (4/8/16 drivers), and opens increasing numbers of
concurrent overlay WebSocket subscribers (what OBS Browser Sources or
spectator pages actually look like) against it. Reports real CPU/RSS of the
running process, snapshot delivery latency, and any recording drops.

Requires (test-only, not added to the app's own requirements):
    pip install psutil websockets httpx

Usage:
    .venv/Scripts/python.exe scripts/group_load_test.py
"""
import asyncio, json, os, statistics, subprocess, sys, tempfile, time
from pathlib import Path

import httpx
import psutil
import websockets

ROOT = Path(__file__).resolve().parents[1]
HTTP_PORT = 8971
GROUP_PORT = 8990
BASE = f'http://127.0.0.1:{HTTP_PORT}'
GROUP_BASE = f'http://127.0.0.1:{GROUP_PORT}'
ORIGIN = f'http://127.0.0.1:{GROUP_PORT}'


async def wait_ready(client, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = await client.get(BASE + '/api/health', timeout=2)
            if r.status_code == 200:
                return
        except Exception:
            pass
        await asyncio.sleep(.3)
    raise RuntimeError('Server did not become ready in time')


async def viewer_task(workspace_id, credential, duration, latencies, errors):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                GROUP_BASE + '/group-api/ticket',
                json={'overlay': True, 'workspace_id': workspace_id},
                headers={'Authorization': 'Bearer ' + credential},
            )
            r.raise_for_status()
            ticket = r.json()['ticket']
        ws_url = GROUP_BASE.replace('http', 'ws') + '/group-api/subscribe'
        async with websockets.connect(ws_url, origin=ORIGIN, max_size=2 ** 20) as ws:
            await ws.send(json.dumps({'ticket': ticket}))
            end = time.monotonic() + duration
            while time.monotonic() < end:
                t0 = time.monotonic()
                await asyncio.wait_for(ws.recv(), 5)
                latencies.append(time.monotonic() - t0)
    except Exception as e:
        errors.append(str(e)[:200])


_tracked = {}  # pid -> psutil.Process, kept alive across calls so cpu_percent() has a baseline


def process_tree(proc):
    """This sandbox launches subprocesses through a shim, so the real interpreter
    doing the work is a child of the PID we spawned, not the PID itself.
    Reuses Process objects across calls: psutil.cpu_percent() reports 0.0 on a
    brand-new Process instance's first call, so a fresh object every tick would
    always read zero."""
    _tracked.setdefault(proc.pid, proc)
    try:
        for child in proc.children(recursive=True):
            if child.pid not in _tracked:
                _tracked[child.pid] = child
                try:child.cpu_percent()  # prime this new process's baseline
                except psutil.Error:pass
    except psutil.Error:
        pass
    live = []
    for pid, p in list(_tracked.items()):
        if not p.is_running():
            _tracked.pop(pid, None)
            continue
        live.append(p)
    return live


def tree_rss(proc):
    total = 0
    for p in process_tree(proc):
        try:
            total += p.memory_info().rss
        except psutil.Error:
            pass
    return total


def tree_cpu_percent(proc):
    total = 0.0
    for p in process_tree(proc):
        try:
            total += p.cpu_percent()
        except psutil.Error:
            pass
    return total


async def run_case(client, proc, drivers, viewers, duration):
    demo = (await client.post(BASE + '/api/group/demo', json={'action': 'start', 'members': drivers})).json()
    if 'workspace_id' not in demo:
        raise RuntimeError(f'Demo did not start: {demo}')
    workspace_id = demo['workspace_id']
    credential = (await client.post(BASE + f'/api/group/workspaces/{workspace_id}/credential', json={})).json()['credential']

    for p in process_tree(proc):
        try:p.cpu_percent()  # prime the interval counter
        except psutil.Error:pass
    latencies, errors = [], []
    tasks = [asyncio.create_task(viewer_task(workspace_id, credential, duration, latencies, errors)) for _ in range(viewers)]

    samples = []

    async def monitor():
        end = time.monotonic() + duration + 1
        while time.monotonic() < end:
            samples.append((tree_cpu_percent(proc), tree_rss(proc)))
            await asyncio.sleep(1)

    await asyncio.gather(monitor(), *tasks)
    state = (await client.get(BASE + '/api/group/state')).json()
    await client.post(BASE + '/api/group/demo', json={'action': 'stop'})

    cpu = [s[0] for s in samples if s[0] is not None][1:] or [0]
    rss = [s[1] for s in samples]
    return {
        'drivers': drivers,
        'viewers': viewers,
        'duration_s': duration,
        'cpu_percent_avg_one_core': round(statistics.mean(cpu), 1),
        'cpu_percent_max_one_core': round(max(cpu), 1),
        'rss_mb_avg': round(statistics.mean(rss) / 1e6, 1),
        'rss_mb_max': round(max(rss) / 1e6, 1),
        'snapshot_interval_ms_p50': round(statistics.median(latencies) * 1000, 1) if latencies else None,
        'snapshot_interval_ms_p95': round(sorted(latencies)[int(len(latencies) * .95)] * 1000, 1) if latencies else None,
        'frames_received_total': len(latencies),
        'viewer_errors': errors[:5],
        'recording_drops': state.get('recording_drops'),
        'recording_error': state.get('recording_error'),
    }


async def main():
    data_dir = Path(tempfile.mkdtemp(prefix='gt7-load-'))
    server = subprocess.Popen(
        [sys.executable, str(ROOT / 'run.py'), 'run', '--data', str(data_dir), '--host', '127.0.0.1', '--port', str(HTTP_PORT)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    proc = psutil.Process(server.pid)
    results = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await wait_ready(client)
            (await client.post(BASE + '/api/pair', json={})).raise_for_status()
            hosting = await client.post(BASE + '/api/group/hosting', json={
                'enabled': True, 'port': GROUP_PORT, 'bind': '127.0.0.1',
                'origins': [ORIGIN], 'host_only': True,
            })
            hosting.raise_for_status()
            driver_levels = [int(x) for x in os.environ.get('LOAD_TEST_DRIVERS', '4,8,16').split(',')]
            viewer_levels = [int(x) for x in os.environ.get('LOAD_TEST_VIEWERS', '1,8,32,60').split(',')]
            duration = float(os.environ.get('LOAD_TEST_DURATION', '20'))
            for drivers in driver_levels:
                for viewers in viewer_levels:
                    print(f'--- {drivers} drivers, {viewers} viewers ---', flush=True)
                    result = await run_case(client, proc, drivers, viewers, duration=duration)
                    print(json.dumps(result, indent=2), flush=True)
                    results.append(result)
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
    out = ROOT / 'docs' / 'group-load-test-validation.json'
    out.write_text(json.dumps({
        'platform': sys.platform, 'cpu_count': psutil.cpu_count(), 'total_ram_mb': round(psutil.virtual_memory().total / 1e6),
        'note': 'Laptop/desktop measurement, not the original Orange Pi 4 GB target; Orange Pi hardware-fit constraint was dropped by the user in favor of general lightweight operation.',
        'cases': results,
    }, indent=2))
    print('Wrote', out)


if __name__ == '__main__':
    asyncio.run(main())
