import pytest,tempfile,time,json
from backend.app.config import Settings,Config
from backend.app.telemetry import demo_sample
from backend.app.sessions import Sessions
from backend.app.storage import Store
from backend.app.analytics import fuel_prediction,lap_statistics,downsample,approximate_compare
from backend.app.engineer import Scheduler,Rules,Event,RULES
from backend.app.voice import intent

@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'test.db');yield s;s.close()

def test_laps_pause_restart_and_car_change(store):
    sessions=Sessions(store,Settings())
    for i in range(6001):sessions.consume(demo_sample(i/60,i))
    assert len(sessions.laps)==3
    assert sessions.laps[0]['partial'] and not sessions.laps[0]['comparable']
    assert sessions.laps[1]['comparable'] and sessions.laps[1]['duration_ms']==30000
    original=sessions.id;s=demo_sample(101,6100);s.values['car_id']=456;sessions.consume(s)
    assert sessions.id!=original and sessions.last_report['status']=='interrupted'
    s=demo_sample(102,6101);s.values['car_id']=456;s.values['flags']=3;sessions.consume(s);assert sessions.status=='paused'
    report=sessions.end();assert report['status']=='completed' and not report['laps'][-1]['complete']
    sessions.consume(s);assert sessions.id is None
    store.flush();assert store.health()['written']==6003

def test_counter_restart_new_epoch(store):
    s=Sessions(store,Settings());s.consume(demo_sample(70,0));old=s.id;s.consume(demo_sample(1,1));assert s.id!=old

def test_fuel_math_partial_lap():
    p=fuel_prediction(12,[2,2,2],2,4.5)
    assert p['needed_l']==11 and p['margin_l']==1 and p['save_percent']==0
    assert not fuel_prediction(10,[0,0,0])['available']
    assert not fuel_prediction(10,[2,2])['available']
    assert fuel_prediction(5,[2,2,2],2,3)['save_percent']==50

def test_storage_recovery(store):
    store.put('session',('x','now',None,'driving','live','{}','{}'));store.flush()
    assert store.detail('x')['status']=='driving'

def test_scheduler_priority_mute_stale_workload():
    logs=[];settings=Settings();s=Scheduler(settings,logs.append)
    s.offer(Event('coach','coach',3,timestamp=0,session='one'));s.offer(Event('fuel','fuel',0,timestamp=0,session='one'))
    assert s.next(1,'one',True).priority==0
    settings.mode='Coaching';assert s.next(2,'one',True) is None
    settings.hard_mute=True;assert s.next(3,'one') is None;assert logs[-1]['decision']=='muted'
    settings.hard_mute=False;s.offer(Event('a','a',timestamp=0));assert s.next(20,'one') is None
    s.offer(Event('b','b',timestamp=30,session='old'));assert s.next(30,'new') is None

def test_scheduler_bounds_and_dedup():
    logs=[];s=Scheduler(Settings(),logs.append)
    for i in range(100):s.offer(Event(str(i),'text'))
    assert len(s.pending)==16
    for i in range(10):s.offer(Event('critical'+str(i),'urgent',0))
    assert len(s.pending)==20
    s.offer(Event('critical0','new',0));assert len(s.pending)==20 and any(x['decision']=='merged' for x in logs)

def test_low_fuel_noisy_and_cooldown():
    r=Rules(Settings());s=demo_sample(0,1);s.values['fuel']=2
    assert not r.evaluate(s,'s');s.mono=3;assert any(e.category=='low_fuel' for e in r.evaluate(s,'s'))
    s.mono=4;assert not r.evaluate(s,'s');s.values['fuel']=4;r.evaluate(s,'s');s.values['fuel']=2;s.mono=61;assert not r.evaluate(s,'s');s.mono=64;assert any(e.category=='low_fuel' for e in r.evaluate(s,'s'))

def test_rules_pause_suppression():
    r=Rules(Settings());s=demo_sample(0,1);s.values['fuel']=.1;r.evaluate(s,'s');s.values['flags']=3;s.mono=10;assert not r.evaluate(s,'s')

@pytest.mark.parametrize('text,expected',[('How much fuel?','fuel'),('stop talking','stop'),('mute','mute'),('delete all sessions','unknown'),('Set target lap time 1:32.500','target'),('set target lap time one minute thirty two seconds','target'),('save a note tyres cold','note'),('please box maybe','unknown')])
def test_intents(text,expected):assert intent(text)[0]==expected

def test_config_validation_and_persistence(tmp_path):
    c=Config(tmp_path);c.save({'reserve_l':3});assert Config(tmp_path).settings.reserve_l==3
    with pytest.raises(ValueError):c.save({'ps5_ip':'192.168.88.21','udp_bind':'192.168.88.21'})
    with pytest.raises(ValueError):Settings(heartbeat=0)
    with pytest.raises(ValueError):Settings(voice='en;rm -rf /')

def test_downsample_preserves_spike():
    rows=[{'mono':i,'values':{'speed_kmh':999 if i==511 else 0}} for i in range(2000)]
    out=downsample(rows,200);assert len(out)<=200 and any(r['values']['speed_kmh']==999 for r in out)

def test_approximate_comparison():
    a=[{'mono':i,'values':{'speed':10}} for i in range(100)]
    r=approximate_compare(a,a);assert r['available'] and 'approximate' in r['quality']
