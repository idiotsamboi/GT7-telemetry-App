import json
import subprocess
import sys
from dataclasses import fields

import pytest

from backend.app.domain.alerts import RULE_DEFS, Alert, AlertCenter, RuleDef
from backend.app.domain.annotations import KINDS, Annotation, from_decision_event
from backend.app.engineer import RULES, Event
from backend.app.storage import Store
from dataclasses import asdict


def test_annotation_fields_and_kinds():
    assert [f.name for f in fields(Annotation)] == ['id', 'session_id', 'kind', 'mono', 'utc', 'lap', 'distance_m',
                                                    'severity', 'source', 'message', 'metadata']
    assert KINDS == ('incident', 'flag', 'pit', 'radio', 'user_marker', 'engineer_alert', 'system', 'race_control',
                     'lap_boundary', 'bookmark')
    with pytest.raises(ValueError):
        Annotation('a', 's', 'nonsense')
    with pytest.raises(ValueError):
        Annotation('a', 's', 'flag', severity='loud')


def test_event_row_round_trip_through_real_store(tmp_path):
    store = Store(tmp_path / 'db')
    try:
        store.put('session', ('s', '2026-01-01T00:00:00+00:00', None, 'driving', 'live', '{}', '{}'))
        note = Annotation.new('s', 'incident', 'Contact at T1', mono=12.5, lap=3, distance_m=410.0, severity='warning',
                              source='steward', metadata={'cars': [4, 9]})
        store.put('annotation', note.to_event_row())
        store.put('event', ('s', '2026-01-01T00:00:01+00:00', json.dumps({'category': 'fuel', 'message': 'old', 'priority': 1})))
        store.flush()
        [item] = store.annotations('s')
        assert Annotation.from_event_row(item) == note
        rows = store.query('SELECT payload,kind,session,utc FROM events ORDER BY id')
        assert Annotation.from_event_row(rows[0]) == note
        legacy = Annotation.from_event_row(rows[1])                        # NULL kind: converted as an engineer decision
        assert legacy.kind == 'engineer_alert' and legacy.severity == 'warning' and legacy.session_id == 's'
    finally:
        store.close()


def test_decision_event_mapping():
    cases = {'annotation': 'user_marker', 'lap': 'lap_boundary', 'box': 'pit', 'connection': 'system', 'disk': 'system',
             'recording': 'system', 'answer': 'radio', 'fuel_deficit': 'engineer_alert', 'low_fuel': 'engineer_alert',
             'coaching': 'engineer_alert', 'race_control': 'race_control'}
    for category, kind in cases.items():
        event = {**asdict(Event(category, 'msg', priority=0, session='s', evidence={'lap': 4})), 'decision': 'selected',
                 'reason': 'ok', 'utc': '2026-01-01T00:00:00+00:00'}
        a = from_decision_event(event)
        assert a.kind == kind and a.severity == 'critical' and a.lap == 4 and a.utc == 1767225600.0
        assert a.metadata['decision'] == 'selected' and a.source == 'engineer' and a.session_id == 's'
    assert from_decision_event({'category': 'x', 'priority': 3}).severity == 'info'
    assert from_decision_event({'category': 'x', 'priority': 99}).severity == 'notice'


def test_alert_center_bounds_dedupe_ack_expiry():
    now = [1000.0]
    center = AlertCenter(maxlen=3, clock=lambda: now[0])
    a = center.raise_alert('network', 'warning', 'Telemetry lost', dedupe_key='net')
    b = center.raise_alert('network', 'warning', 'Telemetry lost', 'again', dedupe_key='net')
    assert a is b and b.count == 2 and len(center) == 1 and b.message == 'again'
    assert center.acknowledge(a.id) and not center.active()
    center.raise_alert('network', 'critical', 'Telemetry lost', dedupe_key='net')       # more severe: re-opens
    assert [x.severity for x in center.active()] == ['critical']
    short = center.raise_alert('storage', 'notice', 'Disk 90%', ttl_s=5, action={'command_id': 'storage.archive', 'payload': {}})
    now[0] += 6
    assert short.id not in [x.id for x in center.active()]                               # expired
    for i in range(6):
        center.raise_alert('session', 'info', f'n{i}')
    assert len(center) == 3 and {x.title for x in center.active()} == {'n3', 'n4', 'n5'}     # bounded: oldest fall off
    assert center.acknowledge_all() == 3
    assert not center.acknowledge('missing')
    json.dumps(center.to_public(include_acknowledged=True))
    with pytest.raises(ValueError):
        Alert('i', 0.0, 'bogus', 'info', 't')
    with pytest.raises(ValueError):
        Alert('i', 0.0, 'network', 'nope', 't')


def test_alert_center_orders_by_severity_then_recency():
    now = [0.0]
    center = AlertCenter(clock=lambda: now[0])
    center.raise_alert('session', 'info', 'old-info')
    now[0] = 1
    center.raise_alert('session', 'critical', 'crit')
    now[0] = 2
    center.raise_alert('session', 'info', 'new-info')
    assert [a.title for a in center.active()] == ['crit', 'new-info', 'old-info']
    assert center.acknowledge_all() == 3 and center.active() == [] and len(center.active(True)) == 3


def test_rule_defs_registry_declarative_form():
    rule = RuleDef('low_fuel', 1, 'meaningful fuel capacity', 'fuel < low_fuel_l', 'fuel > low_fuel_l + 0.5', 3, 90,
                   'Low fuel', ('fuel',))
    try:
        RULE_DEFS.register(rule)
        assert RULE_DEFS.require('low_fuel').persist_s == 3
        assert RULE_DEFS.to_public()[0]['evidence'] == ['fuel']
    finally:
        RULE_DEFS._items.pop('low_fuel', None)
    assert set(RuleDef.__dataclass_fields__) == {'id', 'priority', 'prerequisites', 'entry', 'exit', 'persist_s',
                                                 'cooldown_s', 'message', 'evidence'}
    assert 'low_fuel' in RULES                                                          # shape mirrors engineer.RULES


def test_domain_and_storage_do_not_import_web_framework():
    code = ('import sys, backend.app.domain.annotations, backend.app.domain.alerts, backend.app.domain.insights, '
            'backend.app.domain.timing_models, backend.app.domain.training_defs, backend.app.storage, '
            'backend.app.storage.repositories, backend.app.storage.exports, backend.app.storage.retention, '
            'backend.app.storage.layout, backend.app.storage.audit, backend.app.analysis_cache; '
            'bad=[m for m in sys.modules if m.split(".")[0] in ("fastapi","starlette","uvicorn")]; '
            'assert not bad, bad')
    subprocess.run([sys.executable, '-c', code], check=True, cwd=str(__import__('pathlib').Path(__file__).resolve().parents[1]))
