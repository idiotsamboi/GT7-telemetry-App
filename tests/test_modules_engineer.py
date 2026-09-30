"""Module registry consistency, the EngineerService boundary and the alert centre wiring."""
import asyncio
import time

import pytest

from backend.app import modules  # noqa: F401  (registers modules and the command catalogue)
from backend.app.config import Config, Settings
from backend.app.core import commands as cmd
from backend.app.core.commands import COMMANDS
from backend.app.core.features import FEATURES
from backend.app.core.modules import MODULES
from backend.app.core.permissions import CAPABILITIES, Principal
from backend.app.engineer import RULE_SPECS
from backend.app.engineer_service import EngineerResponse, RuntimeEngineer
from backend.app.runtime import Runtime
from backend.app.runtime_services import build_services
from backend.app.storage import Store
from backend.app.telemetry import demo_sample


@pytest.fixture
def runtime(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({**cfg.settings.model_dump(), 'speech_enabled': False, 'hands_free': False})
    store = Store(tmp_path / 't.db')
    r = Runtime(cfg, store)
    yield r
    store.close()


def test_modules_reference_only_things_that_exist(runtime):
    services = set(build_services(runtime).order())
    for m in MODULES:
        assert set(m.services) <= services, m.id
        assert set(m.commands) <= set(COMMANDS.ids()), m.id
        assert set(m.capabilities) <= set(CAPABILITIES.ids()), m.id
        assert set(m.rules) <= set(RULE_SPECS.ids()), m.id
        assert set(m.settings_fields) <= set(Settings.model_fields), m.id
        assert m.feature_flag is None or m.feature_flag in FEATURES, m.id


def test_every_service_and_command_belongs_to_a_module(runtime):
    owned_services = {s for m in MODULES for s in m.services}
    owned_commands = {c for m in MODULES for c in m.commands}
    assert set(build_services(runtime).order()) - owned_services == set()
    orphans = set(COMMANDS.ids()) - owned_commands
    assert orphans <= {'settings.update', 'safe_mode.leave', 'recovery.live', 'recovery.display', 'recovery.connection', 'recovery.audio'}, orphans


def test_module_ids_are_unique_and_public_listing_has_no_callables():
    listing = MODULES.to_public()
    assert len({m['id'] for m in listing}) == len(listing) >= 10
    assert all(not callable(v) for m in listing for v in m.values())


# ---- engineer service ---------------------------------------------------------------------------------------
def test_engineer_ask_returns_a_typed_response_with_legacy_fields(runtime):
    for i in range(30):
        runtime.consume(demo_sample(i / 60, i))
    response = RuntimeEngineer(runtime).ask('how much fuel')
    assert isinstance(response, EngineerResponse)
    assert response.intent == 'fuel' and 'litres' in response.message and response.source in ('rules', 'template')
    assert response.confidence == 'moderate'
    public = response.to_public()
    assert {'message', 'intent', 'severity', 'evidence', 'related_lap', 'related_corner', 'recommended_action', 'confidence', 'source'} <= set(public)


def test_engineer_ask_goes_through_the_same_path_as_typed_commands(runtime):
    for i in range(30):
        runtime.consume(demo_sample(i / 60, i))
    response = RuntimeEngineer(runtime).ask('how much fuel')
    assert runtime.last_answer == response.message                 # one path: Runtime.command -> execute -> catalogue answer
    assert runtime.scheduler.pending[-1].message == response.message and runtime.scheduler.pending[-1].requested


def test_engineer_navigation_becomes_a_recommended_action(runtime):
    response = runtime.engineer.ask('show analysis')
    assert response.navigate == 'Analysis' and response.recommended_action == {'route': 'Analysis'}


def test_engineer_brief_uses_evidence_summary_when_local_ai_is_off(runtime):
    brief = runtime.engineer.brief()
    assert brief.engine == 'Evidence summary' and brief.source == 'template'


# ---- alerts -------------------------------------------------------------------------------------------------
def test_rule_events_become_alerts_and_can_be_acknowledged(runtime):
    for i in range(400):                                   # ~6.7 s of source time: fuel_critical persists after 2 s
        s = demo_sample(i / 60, i)
        s.values['fuel'] = 0.3
        s.values['fuel_capacity'] = 50
        runtime.consume(s)
    assert runtime.alerts.active() == []                   # offered, not yet selected by the speech scheduler
    spoken = runtime.scheduler.next(time.monotonic(), runtime.sessions.id)
    assert spoken is not None and spoken.category == 'fuel_critical'
    alerts = runtime.engineer.alerts()
    assert [(a.source, a.severity, a.title) for a in alerts] == [('telemetry', 'critical', 'Fuel critical')]
    assert runtime.snapshot()['alerts'][0]['title'] == 'Fuel critical'
    ctx = cmd.Ctx(Principal('local', 'me'), services=runtime)
    result = asyncio.run(cmd.dispatch(ctx, 'alerts.acknowledge', {}, limiter=cmd.RateLimiter()))
    assert result.ok and result.data['acknowledged'] == 1 and runtime.alerts.active() == []


def test_alert_sources_and_severity_mapping(runtime):
    runtime._raise_alert({'category': 'connection', 'priority': 1, 'message': 'Telemetry is stale.', 'session': None})
    runtime._raise_alert({'category': 'recording', 'priority': 1, 'message': 'Recording failure.'})
    runtime._raise_alert({'category': 'low_fuel', 'priority': 1, 'message': 'Fuel low.'})
    runtime._raise_alert({'category': 'coaching', 'priority': 3, 'message': 'Brake later at turn 3.'})
    by = {a.title: a for a in runtime.alerts.active()}
    assert by['Connection'].source == 'network' and by['Recording'].source == 'storage'
    assert by['Low fuel'].source == 'telemetry' and by['Coaching'].source == 'engineer'
    assert by['Connection'].severity == 'warning' and by['Coaching'].severity == 'info' and by['Coaching'].expires is not None
    assert runtime.snapshot()['alerts'][0]['severity'] == 'warning'
    assert not asyncio.run(cmd.dispatch(cmd.Ctx(Principal('local', 'me'), services=runtime), 'alerts.acknowledge', {'id': 'nope'})).ok
