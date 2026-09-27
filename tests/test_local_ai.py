import asyncio,time
import pytest
from backend.app.config import Config
from backend.app.storage import Store
from backend.app.runtime import Runtime
from backend.app.telemetry import demo_sample
from backend.app.local_ai import evidence,selected_items

@pytest.fixture
def runtime(tmp_path):
 cfg=Config(tmp_path);cfg.save({'hands_free':False,'speech_enabled':False});store=Store(tmp_path/'test.db');r=Runtime(cfg,store);r.consume(demo_sample(5,300))
 yield r
 store.close()

def test_stale_and_paused_briefs_do_not_present_advice(runtime):
 runtime.received_at=time.monotonic()-5;assert not evidence(runtime)['available']
 runtime.received_at=time.monotonic();runtime.sample.values['flags']=3;assert not evidence(runtime)['available']

def test_bounded_evidence_preserves_fuel_priority(runtime):
 runtime.sample.values['fuel']=.2;runtime.box=True
 runtime.live_analysis.result={'available':True,'window_s':30,'coast_percent':40,'overlap_percent':20,'tyre_spread_c':25}
 brief=evidence(runtime);items=selected_items(brief,['made_up','coast','coast'])
 assert len(brief['items'])<=8 and len(items)<=3
 assert items[0]['id']=='low_fuel'
 assert len({i['id'] for i in items})==len(items)
 assert all(i in brief['items'] for i in items)

def test_model_failure_keeps_calculated_summary(runtime,monkeypatch):
 async def scenario():
  runtime.settings.local_ai_enabled=True;runtime.box=True;runtime.sample.values['fuel']=1
  def fail(*args):raise RuntimeError('Unavailable model')
  monkeypatch.setattr(runtime.local_ai,'_rank',fail)
  await runtime.local_ai.refresh(runtime,True);await runtime.local_ai.task
  assert runtime.local_ai.result['items']
  assert runtime.local_ai.result['model_error']=='Unavailable model'
  assert runtime.local_ai.result['engine']=='Evidence summary'
 asyncio.run(scenario())

def test_memory_pressure_prevents_inference(runtime,monkeypatch):
 async def scenario():
  runtime.settings.local_ai_enabled=True
  monkeypatch.setattr('backend.app.local_ai.memory_available_mb',lambda:200)
  await runtime.local_ai.refresh(runtime,True)
  assert runtime.local_ai.task is None
  assert 'memory' in runtime.local_ai.result['reason']
 asyncio.run(scenario())

def test_disabled_model_never_starts(runtime):
 asyncio.run(runtime.local_ai.refresh(runtime,True))
 assert runtime.local_ai.process is None and runtime.local_ai.result['items']

def test_unmark_pit_clears_reminders_only(runtime):
 from backend.app.voice import intent
 runtime.command('box this lap');runtime.event('box','Box this lap.',1);runtime.event('fuel','Keep fuel reminder',1)
 assert runtime.box
 runtime.command('unmark pit intent')
 assert not runtime.box and not any(e.category=='box' for e in runtime.scheduler.pending)
 assert any(e.category=='fuel' for e in runtime.scheduler.pending)
 assert all(intent(p)[0]=='unbox' for p in ['stay out','cancel pit stop','unmark pit intent'])
 runtime.command('stay out');assert not runtime.box


def test_successful_model_finishes_ready(runtime,monkeypatch):
 async def scenario():
  runtime.settings.local_ai_enabled=True;runtime.box=True;runtime.sample.values['fuel']=1
  monkeypatch.setattr(runtime.local_ai,'_rank',lambda *args:['pit_intent'])
  await runtime.local_ai.refresh(runtime,True);await runtime.local_ai.task
  assert runtime.local_ai.result['status']=='ready'
  assert runtime.local_ai.result['engine'].startswith('Qwen')
 asyncio.run(scenario())
