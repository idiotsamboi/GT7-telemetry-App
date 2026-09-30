"""`AuditSink` is the `Ctx.audit` callable: it enqueues audit rows on the store's writer thread."""
import time
import uuid
from typing import Mapping

from .store import Store

COLUMNS = ('id', 'utc', 'actor', 'capability', 'command_id', 'target', 'payload_hash', 'result_code', 'message', 'session_id')


class AuditSink:
    def __init__(self, store: Store):
        self.store = store

    def __call__(self, row: Mapping) -> None:
        """Raises if the writer queue is full so core.commands can log `audit_write_failed` (no silent loss)."""
        values = {**row}
        values['id'] = values.get('id') or uuid.uuid4().hex
        values['utc'] = time.time() if values.get('utc') is None else values['utc']
        for key in ('actor', 'capability', 'command_id', 'result_code'):
            if not values.get(key):
                raise ValueError(f'audit row missing {key}')
        message = values.get('message')
        values['message'] = str(message)[:200] if message is not None else None
        for key in ('actor', 'capability', 'command_id', 'result_code', 'target', 'payload_hash', 'session_id'):
            if values.get(key) is not None and not isinstance(values[key], str):
                values[key] = str(values[key])[:200]          # a bind error would roll back the writer's whole batch
        values['utc'] = float(values['utc'])
        if not self.store.put('audit', tuple(values.get(c) for c in COLUMNS)):
            raise RuntimeError('Storage queue full; audit row dropped')
