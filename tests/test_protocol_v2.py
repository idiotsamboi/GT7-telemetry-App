"""Group protocol v2: envelope, handshake, reliable delivery, snapshot sharing. No LAN sockets."""
import asyncio
import json
import logging
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.core.version import PROTOCOL_SUPPORTED, PROTOCOL_VERSION as CORE_PROTOCOL
from backend.app.group import protocol as proto
from backend.app.group.client import MemberClient, ProtocolIncompatible
from backend.app.group.protocol import (ALLOWED_TYPES, MESSAGE_TYPES, Codec, ProtocolError, ReliableChannel,
                                        decode, encode, negotiate, to_legacy)
from backend.app.group.public import public_app
from backend.app.group.service import GroupService
from backend.app.group.snapshots import SnapshotCache

ORIGIN = 'http://testserver'


# ------------------------------------------------------------------ envelope

def test_protocol_constants_come_from_core():
    assert proto.PROTOCOL_VERSION == CORE_PROTOCOL == 2
    assert proto.SUPPORTED == tuple(PROTOCOL_SUPPORTED) == (1, 2)


def test_encode_decode_roundtrip():
    message = encode('lap', {'lap': {'id': 'l1', 'duration_ms': 90000}}, sender='boot-1', session='s1', seq=7)
    assert set(message) == {'v', 'type', 'id', 'ts', 'sender', 'session', 'seq', 'payload'}
    assert message['v'] == 2 and message['seq'] == 7 and message['id']
    decoded = decode(json.dumps(message), max_bytes=4096)
    assert decoded.legacy is False
    assert decoded.envelope.type == 'lap' and decoded.envelope.payload['lap']['id'] == 'l1'
    assert decoded.envelope.sender == 'boot-1' and decoded.envelope.session == 's1'
    assert decode(message, max_bytes=4096).envelope.id == message['id']
    assert decode(json.dumps(message).encode(), max_bytes=4096).envelope.id == message['id']


def test_encode_rejects_unknown_type_and_bad_payload():
    with pytest.raises(ProtocolError):
        encode('nonsense', {})
    with pytest.raises(ProtocolError) as info:
        encode('lap', {'lap': 'not a dict'})
    assert info.value.status_code == 422


def test_legacy_v1_messages_convert_to_envelopes_and_back():
    flat = {'type': 'lap', 'lap': {'id': 'abc', 'duration_ms': 88000}}
    decoded = decode(json.dumps(flat), max_bytes=4096)
    assert decoded.legacy is True
    assert decoded.envelope.v == 1 and decoded.envelope.type == 'lap'
    assert decoded.envelope.id == 'lap:abc'                       # stable id so retransmissions dedupe
    assert decoded.envelope.payload == {'lap': flat['lap']}
    assert to_legacy(decoded.envelope) == flat
    ping = decode({'type': 'ping', 'source': 12.5}, max_bytes=4096)
    assert ping.legacy and ping.envelope.payload == {'source': 12.5}


def test_v1_and_v2_carry_the_same_payload():
    v1 = decode({'type': 'response', 'response': {'action': 'pit_intent'}}, max_bytes=4096).envelope
    v2 = decode(encode('response', {'response': {'action': 'pit_intent'}}, sender='x'), max_bytes=4096).envelope
    assert v1.payload == v2.payload and v1.type == v2.type


def test_size_cap_applies_to_text_bytes_and_dicts():
    big = json.dumps({'type': 'ping', 'pad': 'x' * 5000})
    for raw in (big, big.encode(), json.loads(big)):
        with pytest.raises(ProtocolError) as info:
            decode(raw, max_bytes=1024)
        assert info.value.status_code == 413 and info.value.detail == 'Packet too large'
    assert decode(big, max_bytes=8192).envelope.type == 'ping'


@pytest.mark.parametrize('raw', ['not json', '[1,2]', '{"no_type":1}', '{"type":5}', '"x"'])
def test_malformed_messages_are_rejected(raw):
    with pytest.raises(ProtocolError) as info:
        decode(raw, max_bytes=4096)
    assert info.value.status_code == 400


def test_unknown_type_and_unsupported_version():
    with pytest.raises(ProtocolError) as info:
        decode({'type': 'teleport'}, max_bytes=4096)
    assert (info.value.status_code, info.value.detail) == (422, 'Unknown message')
    with pytest.raises(ProtocolError) as info:
        decode({'v': 9, 'type': 'ping', 'payload': {}}, max_bytes=4096)
    assert info.value.status_code == 426 and info.value.protocol_code == 'protocol_incompatible'


def test_type_allowlist_per_role():
    assert {'telemetry', 'lap', 'response', 'ping', 'clock', 'hello', 'ack'} == ALLOWED_TYPES['driver']
    assert 'telemetry' not in ALLOWED_TYPES['spectator'] and 'lap' not in ALLOWED_TYPES['overlay']
    assert {'state', 'pong', 'error', 'instruction', 'message', 'decision', 'workspace_taken'} <= ALLOWED_TYPES['host']
    for role, forbidden in [('spectator', 'telemetry'), ('overlay', 'response'), ('driver', 'state'), ('driver', 'instruction')]:
        with pytest.raises(ProtocolError) as info:
            decode({'type': forbidden, **({'packet': {}} if forbidden == 'telemetry' else {'response': {}} if forbidden == 'response' else {})},
                   max_bytes=4096, role=role)
        assert info.value.status_code == 403
    assert decode({'type': 'ping'}, max_bytes=4096, role='overlay').envelope.type == 'ping'


def test_every_existing_message_type_is_registered():
    v1_types = {'telemetry', 'lap', 'ping', 'pong', 'clock', 'response', 'hello', 'state', 'error'}
    assert v1_types <= set(MESSAGE_TYPES.ids())
    assert {'ack', 'instruction', 'message', 'decision', 'workspace_taken'} <= set(MESSAGE_TYPES.ids())
    reliable = {m.type for m in MESSAGE_TYPES if m.reliability == 'reliable'}
    assert reliable == {'lap', 'response', 'instruction', 'message', 'decision', 'workspace_taken'}
    assert all(m.roles and m.description for m in MESSAGE_TYPES)
    assert all(isinstance(row['roles'], list) for row in MESSAGE_TYPES.to_public())   # JSON-safe listing


def test_codec_speaks_v1_until_upgraded_and_maps_acks():
    codec = Codec(sender='host', session='s1')
    assert codec.out('lap_ack', {'ack': 'l1'}, reply_to='m1') == {'type': 'lap_ack', 'ack': 'l1'}
    codec.v2 = True
    ack = codec.out('lap_ack', {'ack': 'l1'}, reply_to='m1')
    assert ack['type'] == 'ack' and ack['payload'] == {'id': 'm1', 'of': 'lap', 'ack': 'l1'} and ack['seq'] == 1
    assert codec.out('response_ack', {'ok': True}, reply_to='m2')['payload']['of'] == 'response'
    assert codec.out('state', {'state': {}})['seq'] == 3


# ------------------------------------------------------------------ handshake (pure)

def test_negotiate_v1_client_without_hello():
    deal = negotiate(None)
    assert deal.compatible and deal.legacy and deal.protocol == 1


def test_negotiate_v2_client_picks_highest_common():
    deal = negotiate({'protocol': [1, 2], 'capabilities': ['ack', 'reliable', 'telepathy']}, ('ack', 'reliable', 'snapshot-cache'))
    assert deal.compatible and deal.protocol == 2 and not deal.legacy
    assert deal.capabilities == ('ack', 'reliable')
    assert negotiate({'protocol': 2}).protocol == 2
    assert negotiate({'protocol': [1]}).protocol == 1


def test_negotiate_incompatible_client():
    deal = negotiate({'protocol': [3, 4]})
    assert not deal.compatible and deal.protocol is None and 'protocol_incompatible' in deal.reason
    assert not negotiate({'protocol': 'x'}).compatible
    assert not negotiate(None, supported=(2,)).compatible          # v1 dropped by a future host
    body = deal.reply_payload(session_id='s')
    assert body['compatible'] is False and body['protocol'] == 2 and body['session_id'] == 's'


def test_reply_payload_shape():
    body = negotiate({'protocol': [1, 2]}).reply_payload(session_id='sid', host_time=5.0)
    assert {'protocol', 'app_version', 'compatible', 'reason', 'server_capabilities', 'session_id', 'host_time'} <= set(body)


# ------------------------------------------------------------------ reliable channel

class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_reliable_retry_backoff_ack_and_expiry():
    clock = Clock()
    channel = ReliableChannel(clock=clock, base_delay=1, max_delay=4, ttl=30)
    assert channel.send('m1', {'n': 1}) and channel.send('m1', {'n': 1})    # idempotent
    assert channel.pending() == 1
    assert channel.due() == [('m1', {'n': 1})]                              # first send is immediate
    assert channel.due() == []
    sent_at = [0.0]
    for expected_gap in (1, 2, 4, 4):                                        # exponential, capped
        clock.now += expected_gap - 0.01
        assert channel.due() == []
        clock.now += 0.01
        assert len(channel.due()) == 1
        sent_at.append(expected_gap)
    assert channel.attempts('m1') == 5
    assert channel.ack('m1') and not channel.ack('m1')
    clock.now += 100
    assert channel.due() == [] and channel.expired() == []                  # acked: nothing expires


def test_reliable_message_expires_unacked():
    clock = Clock()
    channel = ReliableChannel(clock=clock, base_delay=1, ttl=5)
    channel.send('m1', 'x')
    channel.send('m2', 'y', ttl=100)
    assert [i for i, _ in channel.due()] == ['m1', 'm2']
    clock.now += 6
    assert [i for i, _ in channel.due()] == ['m2']
    assert channel.expired() == ['m1'] and channel.expired() == []
    assert channel.pending() == 1


def test_reliable_gives_up_after_max_attempts():
    clock = Clock()
    channel = ReliableChannel(clock=clock, base_delay=1, max_delay=1, ttl=1000, max_attempts=3)
    channel.send('m', 1)
    for _ in range(3):
        assert len(channel.due()) == 1
        clock.now += 1.1
    assert channel.due() == [] and channel.expired() == ['m']


def test_reliable_outbox_and_dedup_windows_are_bounded():
    channel = ReliableChannel(clock=Clock(), outbox_limit=3, dedup_limit=4)
    assert [channel.send(f'm{i}', i) for i in range(5)] == [True, True, True, False, False]
    assert channel.dropped == 2 and channel.pending() == 3
    assert [channel.seen(f'r{i}') for i in range(4)] == [False] * 4
    assert channel.seen('r0') and channel.seen('r3')
    channel.seen('r4')                                                        # evicts the least recently used
    assert not channel.seen('r1')                                             # r1 forgotten: window is bounded
    assert len(channel._seen) <= 4


def test_receiver_dedup_replays_cached_reply():
    channel = ReliableChannel(clock=Clock())
    assert channel.seen('lap:1') is False
    channel.remember('lap:1', {'type': 'ack'})
    assert channel.seen('lap:1') is True and channel.reply_for('lap:1') == {'type': 'ack'}
    assert channel.reply_for('never') is None


def test_reset_backoff_retransmits_immediately_after_reconnect():
    clock = Clock()
    channel = ReliableChannel(clock=clock, base_delay=10)
    channel.send('m', 1)
    channel.due()
    clock.now += 1
    assert channel.due() == []
    channel.reset_backoff()
    assert len(channel.due()) == 1


# ------------------------------------------------------------------ snapshot cache

def test_snapshot_cache_shares_expires_and_is_bounded():
    clock = Clock()
    cache = SnapshotCache(max_entries=2, max_age=0.2, clock=clock)
    calls = []
    compute = lambda tag: (lambda: calls.append(tag) or {'tag': tag})     # noqa: E731
    first = cache.get('a', compute('a'))
    assert cache.get('a', compute('a2')) is first and calls == ['a']
    clock.now += 0.25
    assert cache.get('a', compute('a3'))['tag'] == 'a3'                     # older than max_age: recomputed
    cache.get('b', compute('b'))
    cache.get('c', compute('c'))
    assert len(cache) == 2 and cache.computations == 4 and cache.hits == 1
    cache.clear()
    assert len(cache) == 0


# ------------------------------------------------------------------ service harness

def make_service(tmp_path):
    return GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path / 'db.sqlite'),
                                        config=SimpleNamespace(root=tmp_path)))


class Rig:
    def __init__(self, tmp_path, spectators=0):
        self.s = make_service(tmp_path)
        asyncio.run(self.build(spectators))

    async def build(self, spectators):
        s = self.s
        league = await s.league_save({'name': 'Proto'})
        self.group = await s.create_group({'name': 'P', 'event_name': 'E', 'league_id': league['id'], 'approval': False})
        invite = await s.invite('driver')
        self.driver = await s.join({'credential': invite['credential'], 'identity': {'display_name': 'D', 'number': '1'}})
        self.spectators = []
        for n in range(spectators):
            invite = await s.invite('spectator')
            joined = await s.join({'credential': invite['credential'], 'identity': {'display_name': f'S{n}'}})
            self.spectators.append(await s.authenticate(joined['token'], ('spectator',)))
        self.workspace = await s.save_workspace({'name': 'Output'})
        self.overlay = await s.overlay_token(self.workspace['id'])

    def headers(self):
        return {'authorization': 'Bearer ' + self.driver['token']}

    def packet(self, sequence=1):
        p = self.driver['participant']
        g = self.s.active()
        return {'version': 1, 'group_id': g['id'], 'session_id': g['session_id'], 'participant_id': p['id'],
                'entry_id': p['entry_id'], 'boot_id': 'b', 'sequence': sequence, 'source_mono': 1,
                'source_utc': time.time(), 'provenance': 'live', 'layout_id': '', 'local_session_id': 'l',
                'values': {'car_id': 1, 'lap': None, 'flags': 1}}

    def lap(self, lap_id='lap-1'):
        return {'session_id': self.s.active()['session_id'], 'id': lap_id, 'duration_ms': 91000, 'number': 1,
                'comparable': True, 'quality': []}

    def lap_events(self):
        return [e for e in self.s.repo.events(self.group['id']) if e['kind'] == 'completed_lap']


@pytest.fixture()
def rig(tmp_path):
    return Rig(tmp_path)


def env(type, payload, **extra):
    return {'v': 2, 'type': type, 'id': extra.pop('id', type + '-1'), 'ts': time.time(), 'sender': 'test-client',
            'session': None, 'seq': None, 'payload': payload, **extra}


def hello(protocols=(1, 2)):
    return env('hello', {'protocol': list(protocols), 'app_version': 'test', 'capabilities': ['ack'], 'boot_id': 'b'})


# ------------------------------------------------------------------ WebSocket end to end

def test_v1_client_keeps_working_and_is_flagged_once(rig, caplog):
    with caplog.at_level(logging.WARNING, logger='network'), TestClient(public_app(rig.s, {ORIGIN}), base_url=ORIGIN) as c:
        for attempt in (1, 2):                                                 # same client connects twice
            with c.websocket_connect('/group-api/publish', headers=rig.headers()) as ws:
                greeting = ws.receive_json()
                assert greeting['type'] == 'hello' and greeting['session_id'] and 'host_time' in greeting
                ws.send_json({'type': 'ping', 'source': 1})
                pong = ws.receive_json()
                assert pong['type'] == 'pong' and 'state' in pong and pong['source'] == 1     # flat, as before
                ws.send_json({'type': 'lap', 'lap': rig.lap()})
                assert ws.receive_json() == {'type': 'lap_ack', 'ack': 'lap-1'}
                ws.send_json({'type': 'response', 'response': {'action': 'pit_intent'}})
                assert ws.receive_json() == {'type': 'response_ack', 'ok': True}
                ws.send_json({'type': 'telemetry', 'packet': rig.packet(attempt)})
                reply = ws.receive_json()
                assert reply['type'] == 'state' and reply['accepted'] is True
                ws.send_json({'type': 'bogus'})
                assert ws.receive_json() == {'type': 'error', 'message': 'Unknown message'}
    flagged = [r for r in caplog.records if getattr(r, 'event', '') == 'protocol_v1_client']
    assert len(flagged) == 1
    assert 'token' not in json.dumps(flagged[0].details).lower() and rig.driver['token'] not in caplog.text


def test_v2_client_handshake_reliable_ack_and_dedup(rig, caplog):
    with caplog.at_level(logging.WARNING, logger='network'), TestClient(public_app(rig.s, {ORIGIN}), base_url=ORIGIN) as c:
        with c.websocket_connect('/group-api/publish', headers=rig.headers()) as ws:
            greeting = ws.receive_json()
            assert greeting['protocol'] == 2 and 'server_capabilities' in greeting
            ws.send_json(hello())
            reply = ws.receive_json()
            assert reply['v'] == 2 and reply['type'] == 'hello'
            assert reply['payload']['compatible'] is True and reply['payload']['protocol'] == 2
            assert reply['payload']['session_id'] == greeting['session_id']
            assert 'ack' in reply['payload']['server_capabilities']

            ws.send_json(env('ping', {'source': 3.0}))
            pong = ws.receive_json()
            assert pong['type'] == 'pong' and pong['payload']['source'] == 3.0 and pong['seq'] == 2

            lap = env('lap', {'lap': rig.lap()}, id='m-lap-1')
            ws.send_json(lap)
            ack = ws.receive_json()
            assert ack['type'] == 'ack' and ack['payload']['id'] == 'm-lap-1' and ack['payload']['ack'] == 'lap-1'
            ws.send_json(lap)                                                  # retransmission (ack was "lost")
            again = ws.receive_json()
            assert again['type'] == 'ack' and again['payload']['id'] == 'm-lap-1'
            assert len(rig.lap_events()) == 1                                  # processed once

            ws.send_json(env('response', {'response': {'action': 'assistance'}}, id='m-resp-1'))
            answer = ws.receive_json()
            assert answer['type'] == 'ack' and answer['payload']['of'] == 'response'

            ws.send_json(env('telemetry', {'packet': rig.packet()}))
            state = ws.receive_json()
            assert state['type'] == 'state' and state['payload']['accepted'] is True and 'state' in state['payload']
    assert not [r for r in caplog.records if getattr(r, 'event', '') == 'protocol_v1_client']


def test_incompatible_client_is_told_and_closed(rig):
    with TestClient(public_app(rig.s, {ORIGIN}), base_url=ORIGIN) as c:
        with c.websocket_connect('/group-api/publish', headers=rig.headers()) as ws:
            ws.receive_json()
            ws.send_json(env('hello', {'protocol': [7, 8]}))
            error = ws.receive_json()
            assert error['type'] == 'error' and error['payload']['code'] == 'protocol_incompatible'
            assert 'protocol_incompatible' in error['payload']['message']
            with pytest.raises(WebSocketDisconnect) as info:
                ws.receive_json()
            assert info.value.code == proto.CLOSE_PROTOCOL_INCOMPATIBLE


def test_publish_rejects_oversize_and_disallowed_types(rig):
    with TestClient(public_app(rig.s, {ORIGIN}), base_url=ORIGIN) as c:
        with c.websocket_connect('/group-api/publish', headers=rig.headers()) as ws:
            ws.receive_json()
            ws.send_text(json.dumps({'type': 'ping', 'pad': 'x' * 40000}))
            assert ws.receive_json() == {'type': 'error', 'message': 'Packet too large'}
        with c.websocket_connect('/group-api/publish', headers=rig.headers()) as ws:
            ws.receive_json()
            ws.send_json({'type': 'state', 'state': {}})                      # host-only type from a driver
            assert ws.receive_json()['message'] == 'Message type not permitted'


def test_subscribe_defaults_to_the_unchanged_frame_and_v2_is_opt_in(rig):
    with TestClient(public_app(rig.s, {ORIGIN}), base_url=ORIGIN) as c:
        headers = {'origin': ORIGIN, 'authorization': 'Bearer ' + rig.overlay['credential']}
        def ticket():
            return c.post('/group-api/ticket', headers=headers, json={'overlay': True, 'workspace_id': rig.workspace['id']}).json()['ticket']
        with c.websocket_connect('/group-api/subscribe', headers={'origin': ORIGIN}) as ws:
            ws.send_json({'ticket': ticket()})
            frame = ws.receive_json()
            assert frame['workspace']['name'] == 'Output' and 'v' not in frame
        with c.websocket_connect('/group-api/subscribe', headers={'origin': ORIGIN}) as ws:
            ws.send_json({'ticket': ticket(), 'protocol': 2})
            message = ws.receive_json()
            assert message['v'] == 2 and message['type'] == 'state'
            assert message['payload']['state']['workspace']['name'] == 'Output'


# ------------------------------------------------------------------ member client codec (fake socket)

class FakeSocket:
    def __init__(self, replies):
        self.sent, self.replies = [], list(replies)

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        return json.dumps(self.replies.pop(0))


def make_client():
    joined = {'token': 't', 'group_id': 'g', 'session_id': 's', 'participant': {'id': 'p', 'entry_id': 'e', 'identity': {}, 'sharing': []}}
    return MemberClient(SimpleNamespace(), 'http://127.0.0.1:8090', joined)


def test_client_handshake_against_v1_host_stays_flat():
    client = make_client()
    ws = FakeSocket([{'type': 'pong', 'host_time': 1.0}])
    asyncio.run(client.handshake(ws, {'type': 'hello', 'session_id': 's'}))
    assert client.v2 is False and ws.sent == []
    reply = asyncio.run(client.exchange(ws, 'ping', {'source': 1}))
    assert ws.sent[-1] == {'type': 'ping', 'source': 1} and reply['type'] == 'pong'


def test_client_handshake_upgrades_and_normalises_replies():
    client = make_client()
    server_hello = encode('hello', {'protocol': 2, 'app_version': 'x', 'compatible': True, 'reason': '',
                                    'server_capabilities': ['ack'], 'session_id': 's'}, sender='host')
    ws = FakeSocket([server_hello, encode('ack', {'id': 'lap:l1', 'of': 'lap', 'ack': 'l1'}, sender='host')])
    asyncio.run(client.handshake(ws, {'type': 'hello', 'session_id': 's', 'protocol': 2}))
    assert client.v2 is True
    assert ws.sent[0]['v'] == 2 and ws.sent[0]['type'] == 'hello' and ws.sent[0]['payload']['protocol'] == [1, 2]
    reply = asyncio.run(client.exchange(ws, 'lap', {'lap': {'id': 'l1'}}, id='lap:l1'))
    assert ws.sent[1]['id'] == 'lap:l1' and reply['ack'] == 'l1'         # v1-style checks keep working


def test_client_surfaces_incompatible_host():
    client = make_client()
    error = encode('error', {'message': 'protocol_incompatible: host supports [3]', 'code': 'protocol_incompatible'}, sender='host')
    with pytest.raises(ProtocolIncompatible) as info:
        asyncio.run(client.handshake(FakeSocket([error]), {'type': 'hello', 'session_id': 's', 'protocol': 2}))
    assert 'protocol_incompatible' in str(info.value)


# ------------------------------------------------------------------ snapshot sharing in the service

def test_n_subscribers_share_one_snapshot_computation(tmp_path):
    rig = Rig(tmp_path, spectators=6)
    s = rig.s
    calls = []
    original = s.filter_snapshot
    s.filter_snapshot = lambda *a, **k: calls.append(1) or original(*a, **k)
    workspace = s.workspace(rig.workspace['id'])
    states = [s.public_state(p, workspace) for p in rig.spectators]
    assert len(calls) == 1                                                      # six subscribers, one computation
    assert all(state['workspace']['name'] == 'Output' for state in states)
    assert all(state['entries'] == states[0]['entries'] for state in states)
    s.public_state(rig.spectators[0], workspace)
    assert len(calls) == 1
    # A revision bump (any group commit) invalidates the shared snapshot.
    asyncio.run(s.configure({'name': 'Renamed'}))
    [s.public_state(p, workspace) for p in rig.spectators]
    assert len(calls) == 2
    assert s.public_state(rig.spectators[0], workspace)['name'] == 'Renamed'


def test_shared_snapshot_does_not_change_what_subscribers_receive(tmp_path):
    rig = Rig(tmp_path, spectators=2)
    s = rig.s
    g = s.active()
    raw = s.raw_snapshot(g)
    expected = s.filter_snapshot(raw, g, rig.spectators[0])
    expected['delay_s'] = 0
    got = s.public_state(rig.spectators[0])
    got.pop('timeline', None)
    expected.pop('timeline', None)
    assert got.keys() == expected.keys()
    assert {k: got[k] for k in got if k not in ('loss',)} == {k: expected[k] for k in expected if k not in ('loss',)}


def test_drivers_do_not_share_each_others_snapshot(tmp_path):
    rig = Rig(tmp_path)
    s = rig.s
    invite = asyncio.run(s.invite('driver'))
    other = asyncio.run(s.join({'credential': invite['credential'], 'identity': {'display_name': 'D2', 'number': '2'},
                                'accepted_sharing': ['basic']}))
    calls = []
    original = s.filter_snapshot
    s.filter_snapshot = lambda *a, **k: calls.append(1) or original(*a, **k)
    p1 = asyncio.run(s.authenticate(rig.driver['token'], ('driver',)))
    p2 = asyncio.run(s.authenticate(other['token'], ('driver',)))
    s.public_state(p1)
    s.public_state(p2)
    s.public_state(p1)
    assert len(calls) == 2
