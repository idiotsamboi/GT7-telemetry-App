"""Live UDP integration: no PS5 or synthetic demo shortcut is used here.
A local emulated console sends independently encrypted wire datagrams.
"""
import asyncio,json,socket,time
import pytest
from backend.app.config import Config
from backend.app.runtime import Runtime
from backend.app.storage import Store
from tests.fixture_generator import fixtures

async def eventually(predicate,timeout=3):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        await asyncio.sleep(.01)
    raise AssertionError('Condition was not reached')

def free_port():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]

def test_actual_udp_heartbeat_parse_record_bad_packets_recover(tmp_path,monkeypatch):
    async def scenario():
        peer=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);peer.bind(('127.0.0.1',0));peer.setblocking(False)
        local=free_port();cfg=Config(tmp_path);cfg.save({'ps5_ip':'127.0.0.1','udp_port':local,'remote_port':peer.getsockname()[1],'heartbeat':1})
        db=Store(tmp_path/'udp.db');r=Runtime(cfg,db);await r.start();loop=asyncio.get_running_loop()
        try:
            heartbeat,addr=await asyncio.wait_for(loop.sock_recvfrom(peer,1024),3)
            assert heartbeat==b'A' and addr[1]==local
            await loop.sock_sendto(peer,b'not-a-GT7-packet',addr)
            await loop.sock_sendto(peer,bytes(296),addr)
            await loop.sock_sendto(peer,bytes.fromhex(fixtures(10)['C']),addr)
            await eventually(lambda:r.sample is not None)
            assert r.sample.variant=='C' and r.sample.values['current_ms']==12345
            for pid in (11,11,9,13):
                await loop.sock_sendto(peer,bytes.fromhex(fixtures(pid)['A']),addr)
                await asyncio.sleep(.01)
            await eventually(lambda:r.sample.values['packet_id']==13)
            assert r.sample.variant=='A' and r.sample.values['current_ms'] is None
            assert r.seq.counts['duplicates']==1 and r.seq.counts['reordered']==1 and r.seq.counts['gaps']==1
            assert r.parse_errors==2 and r.receiver['error_counts']=={'bad_length':1,'bad_magic':1}
            import backend.app.runtime as module
            original=module.parse
            def fail_once(*args,**kwargs):
                monkeypatch.setattr(module,'parse',original)
                raise RuntimeError('injected parser failure')
            monkeypatch.setattr(module,'parse',fail_once)
            await loop.sock_sendto(peer,bytes.fromhex(fixtures(14)['A']),addr)
            await eventually(lambda:r.parse_errors==3)
            await loop.sock_sendto(peer,bytes.fromhex(fixtures(15)['B']),addr)
            await eventually(lambda:r.sample.values['packet_id']==15)
            assert r.receiver['error_counts']['parser_exception']==1
            assert not r.tasks[0].done()
            await asyncio.to_thread(db.flush)
            rows=db.samples(r.sessions.id)
            assert [x['values']['packet_id'] for x in rows]==[10,11,13,15]
            assert db.drops==0 and db.failed_rows==0
            # Actual heartbeat is repeated on the configured interval.
            heartbeat,_=await asyncio.wait_for(loop.sock_recvfrom(peer,1024),2)
            assert heartbeat==b'A' and r.receiver['heartbeats']>=2
            r.switch('demo');await eventually(lambda:r.receiver['phase']=='demo_no_network')
            assert r.transport is None
        finally:
            await r.close();peer.close()
    asyncio.run(scenario())

def test_sender_filter_and_parser_failure_diagnostics(tmp_path):
    cfg=Config(tmp_path);cfg.save({'ps5_ip':'192.0.2.10'})
    store=Store(tmp_path/'db');r=Runtime(cfg,store)
    try:
        assert not r.ingest_datagram(bytes.fromhex(fixtures()['A']),('192.0.2.11',33739))
        assert r.unexpected==1 and r.parse_errors==0 and r.sample is None
        assert not r.ingest_datagram(bytes(344),('192.0.2.10',33739))
        assert r.receiver['last_error']['code']=='bad_magic'
        assert r.ingest_datagram(bytes.fromhex(fixtures()['~']),('192.0.2.10',33739))
        assert r.receiver['last_error'] is None and r.sample.variant=='~'
    finally:store.close()

def test_network_settings_reopen_receiver(tmp_path):
    async def scenario():
        first=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);first.bind(('127.0.0.1',0));first.setblocking(False)
        second=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);second.bind(('127.0.0.1',0));second.setblocking(False)
        cfg=Config(tmp_path);cfg.save({'ps5_ip':'127.0.0.1','udp_port':free_port(),'remote_port':first.getsockname()[1]})
        db=Store(tmp_path/'db');r=Runtime(cfg,db);await r.start();loop=asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.sock_recvfrom(first,100),3)
            settings=cfg.settings.model_dump();settings.update(remote_port=second.getsockname()[1],variant='C')
            r.update_settings(settings)
            data,_=await asyncio.wait_for(loop.sock_recvfrom(second,100),3)
            assert data==b'C' and r.receiver['heartbeats']>=2
        finally:await r.close();first.close();second.close()
    asyncio.run(scenario())
