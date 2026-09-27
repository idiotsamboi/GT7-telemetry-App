import pytest
from backend.app.config import Config
from backend.app.storage import Store
from backend.app.runtime import Runtime
from backend.app.telemetry import demo_sample

@pytest.fixture
def runtime(tmp_path):
    config=Config(tmp_path);config.save({'speech_enabled':False})
    store=Store(tmp_path/'test.db');runtime=Runtime(config,store)
    yield runtime
    store.close()

def feed(runtime,flags=1,lap=3,car=82):
    sample=demo_sample(5,300)
    sample.values.update(flags=flags,lap=lap,car_id=car)
    runtime.consume(sample)
    runtime.record_driver_position(False)

def test_exit_clears_line_and_reference_and_menu_does_not_redraw(runtime):
    feed(runtime)
    runtime.live_delta.manual_reference=([(0,[0,0,0])],20)
    assert runtime.trace
    feed(runtime,flags=0)
    assert not runtime.trace and runtime.live_delta.manual_reference is None
    feed(runtime,flags=0)
    assert not runtime.trace
    feed(runtime)
    assert len(runtime.trace)==1

@pytest.mark.parametrize('flags',[3,5])
def test_pause_or_loading_does_not_erase_or_extend_line(runtime,flags):
    feed(runtime);before=list(runtime.trace)
    feed(runtime,flags=flags)
    assert list(runtime.trace)==before

@pytest.mark.parametrize('change',[{'lap':1},{'car':83}])
def test_restart_or_car_change_starts_new_line(runtime,change):
    feed(runtime);feed(runtime)
    assert len(runtime.trace)==2
    feed(runtime,**change)
    assert len(runtime.trace)==1

def test_normal_lap_preserves_line_and_stale_does_not_extend(runtime):
    feed(runtime);feed(runtime,lap=4)
    assert len(runtime.trace)==2
    runtime.record_driver_position(True)
    assert len(runtime.trace)==2
