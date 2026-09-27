import asyncio,json,queue,threading,time,types
import pytest
from backend.app.voice import mic_worker,Microphone
from backend.app.config import Config,Settings
from backend.app.runtime import Runtime
from backend.app.storage import Store
from backend.app.telemetry import demo_sample
from backend.app.analytics import Accumulator
from backend.app.engineer import Rules
from backend.app.live_analysis import LiveAnalysis


def test_continuous_worker_delivers_two_requests_without_button(monkeypatch,tmp_path):
    commands=queue.Queue();results=queue.Queue();gate=threading.Event()
    class Recognizer:
        def __init__(self,*args):pass
        def SetWords(self,*args):pass
        def Reset(self):pass
        def AcceptWaveform(self,data):return True
        def Result(self):return json.dumps({'text':'radio check','result':[{'conf':1}]})
        def FinalResult(self):return '{}'
    class Stream:
        def __init__(self,**kwargs):self.callback=kwargs['callback']
        def __enter__(self):
            self.callback(bytes(3200),1600,None,None);self.callback(bytes(3200),1600,None,None);return self
        def __exit__(self,*args):pass
    class Results(queue.Queue):
        def put_nowait(self,item):
            super().put_nowait(item)
            if 'result' in item:
                delivered.append(item)
                if len(delivered)==2:commands.put('close')
    delivered=[];results=Results()
    monkeypatch.setitem(__import__('sys').modules,'vosk',types.SimpleNamespace(Model=lambda p:None,KaldiRecognizer=Recognizer,SetLogLevel=lambda x:None))
    monkeypatch.setitem(__import__('sys').modules,'sounddevice',types.SimpleNamespace(query_devices=lambda *a:{'name':'Test microphone','default_samplerate':16000},check_input_settings=lambda **k:None,RawInputStream=Stream,PortAudioError=RuntimeError))
    settings=Settings(vosk_model=str(tmp_path),hands_free=True).model_dump()
    worker=threading.Thread(target=mic_worker,args=(commands,results,settings,gate),daemon=True);worker.start();worker.join(2)
    commands.put('close')
    assert not worker.is_alive()
    assert len(delivered)==2
    assert all(item['result']['text']=='radio check' for item in delivered)


def test_microphone_discards_speaker_echo_and_old_results():
    mic=Microphone();mic.results=queue.Queue()
    mic.set_suppressed(True)
    mic.results.put({'result':{'text':'radio check'},'captured_at':time.monotonic()})
    assert mic.poll()==[]
    cutoff=mic.accept_after;mic.set_suppressed(False)
    mic.results.put({'result':{'text':'old'},'captured_at':cutoff-1})
    mic.results.put({'result':{'text':'fresh'},'captured_at':time.monotonic()})
    assert mic.poll()==[{'text':'fresh'}]


def test_hands_free_allows_reply_and_gates_input(tmp_path,monkeypatch):
    async def scenario():
        cfg=Config(tmp_path);store=Store(tmp_path/'test.db');r=Runtime(cfg,store)
        r.mic.state='listening';r.mic.last_attempt=time.monotonic()
        spoken=[]
        def speak(text,settings,priority):
            spoken.append((text,r.mic.suppressed.is_set()));return True
        monkeypatch.setattr(r.speaker,'speak',speak)
        r.command('radio check');task=asyncio.create_task(r.engine_loop())
        try:
            await asyncio.sleep(.15)
            assert spoken and spoken[0][1]
        finally:r.running=False;task.cancel();await asyncio.gather(task,return_exceptions=True);store.close()
    asyncio.run(scenario())


def test_paused_loading_and_off_track_samples_do_not_accumulate():
    for flags in (0,3,5):
        acc=Accumulator();sample=demo_sample(0,0);sample.values['flags']=flags
        acc.add(sample);sample.mono+=1;acc.add(sample)
        assert acc.samples==0 and acc.elapsed==0
        analysis=LiveAnalysis();analysis.consume(sample);assert analysis.result['available'] is False
        assert Rules(Settings()).evaluate(sample,None)==[]


def test_heartbeat_bounds():
    assert Settings(heartbeat=.25).heartbeat==.25
    with pytest.raises(ValueError):Settings(heartbeat=.01)
    with pytest.raises(ValueError):Settings(heartbeat=float('nan'))
