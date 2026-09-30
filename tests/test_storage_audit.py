import asyncio

import pytest
from pydantic import BaseModel

from backend.app.core.commands import CommandDef, CommandResult, Ctx, dispatch
from backend.app.core.errors import ResultCode
from backend.app.core.permissions import Principal
from backend.app.core.registry import Registry
from backend.app.storage import Store
from backend.app.storage.audit import AuditSink


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / 'db')
    yield s
    s.close()


ROW = {'id': 'r1', 'utc': 5.0, 'actor': 'user:me', 'capability': 'race_control', 'command_id': 'raceControl.setFlag',
       'target': 'yellow', 'payload_hash': 'abc', 'result_code': 'ok', 'message': 'done', 'session_id': 's1'}


def test_sink_writes_row_through_writer_thread(store):
    AuditSink(store)(dict(ROW))
    store.flush()
    assert store.audit() == [ROW]


def test_sink_fills_defaults_truncates_and_validates(store):
    sink = AuditSink(store)
    sink({**ROW, 'id': None, 'utc': None, 'message': 'x' * 500})
    store.flush()
    row = store.audit()[0]
    assert len(row['id']) == 32 and row['utc'] > 0 and len(row['message']) == 200
    with pytest.raises(ValueError):
        sink({**ROW, 'actor': ''})


def test_sink_raises_when_queue_is_full(tmp_path):
    store = Store(tmp_path / 'db', capacity=1)
    try:
        full = 0
        sink = AuditSink(store)
        for i in range(2000):
            try:
                sink({**ROW, 'id': f'r{i}'})
            except RuntimeError:
                full += 1
        assert full == store.drops
    finally:
        store.close()


def test_dispatch_audits_through_ctx(store):
    class Payload(BaseModel):
        target: str = ''

    registry = Registry('test_commands')
    registry.register(CommandDef('test.audited', 'raceControl.setFlag', Payload,
                                 lambda ctx, p: CommandResult(ResultCode.OK, 'fine'), audited=True))
    ctx = Ctx(principal=Principal(kind='host', subject='sam'), audit=AuditSink(store), session_id='s1')
    result = asyncio.run(dispatch(ctx, 'test.audited', {'target': 'x'}, registry=registry))
    store.flush()
    rows = store.audit(session='s1')
    assert result.audit_id == rows[0]['id'] and rows[0]['command_id'] == 'test.audited' and rows[0]['target'] == 'x'
    assert rows[0]['actor'] == 'host:sam' and rows[0]['result_code'] == 'ok'
