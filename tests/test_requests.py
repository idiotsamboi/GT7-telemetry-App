import time,wave
import numpy as np
import pytest
from backend.app.requests import CATALOG
from backend.app.voice import intent,Speaker
from backend.app.config import Config,Settings
from backend.app.storage import Store
from backend.app.runtime import Runtime
from backend.app.telemetry import demo_sample

@pytest.fixture
def runtime(tmp_path):
    cfg=Config(tmp_path);cfg.save({'speech_enabled':False});store=Store(tmp_path/'test.db');r=Runtime(cfg,store)
    r.consume(demo_sample(5,300));yield r
    r.speaker.stop();r.mic.close();store.close()

def test_catalog_is_one_hundred_distinct_requests():
    assert len(CATALOG)==100
    assert len({c['request'] for c in CATALOG.values()})==100
    for key,c in CATALOG.items():
        assert len(set(c['answers']))==3
        assert intent(c['request'])[0]==key

@pytest.mark.parametrize('key',list(CATALOG))
def test_each_request_has_three_distinct_replies(runtime,key):
    answers=[runtime.command(CATALOG[key]['request']) for _ in range(3)]
    assert [a['variation'] for a in answers]==[0,1,2]
    assert len({a['answer'] for a in answers})==3
    assert all(a['intent']==key and '{' not in a['answer'] for a in answers)

def test_live_values_stale_gating_and_unknowns(runtime):
    runtime.sample.values['speed_kmh']=123.4
    assert '123.4' in runtime.command('what is my speed')['answer']
    runtime.received_at=time.monotonic()-30
    assert 'fresh telemetry' in runtime.command('what is my speed')['answer']
    assert 'does not provide' in runtime.command('what flags are out')['answer']
    assert '2' in runtime.command('what is my fuel reserve')['answer']

def test_resume_enables_speech_and_navigation_is_valid(runtime):
    runtime.command('mute');runtime.command('resume engineer')
    assert runtime.settings.speech_enabled and not runtime.settings.hard_mute
    assert runtime.command('show live')['navigate']=='Live Race'

def test_speaker_generates_pcm_and_uses_selected_device(monkeypatch):
    import sounddevice as sd
    speaker=Speaker();calls=[]
    def render(text,settings,path):
        with wave.open(str(path),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(np.full(1600,1000,dtype=np.int16).tobytes())
    monkeypatch.setattr(speaker,'_render',render)
    monkeypatch.setattr(sd,'query_devices',lambda device,kind:{'name':'Selected speaker'})
    monkeypatch.setattr(sd,'play',lambda samples,rate,**kwargs:calls.append((len(samples),rate,kwargs)))
    speaker.speak('Test',Settings(output_device=7));speaker.thread.join(3)
    assert speaker.state=='completed' and speaker.frames==1600
    assert calls==[(1600,16000,{'device':7,'blocking':True})]

def test_speaker_reports_synthesis_failure_and_zero_volume(monkeypatch):
    speaker=Speaker()
    monkeypatch.setattr(speaker,'_render',lambda *args:(_ for _ in ()).throw(RuntimeError('Engine missing')))
    speaker.speak('Test',Settings());speaker.thread.join(3)
    assert speaker.state=='error' and speaker.error=='Engine missing'
    speaker.speak('Test',Settings(voice_volume=0));speaker.thread.join(3)
    assert 'volume is zero' in speaker.error
