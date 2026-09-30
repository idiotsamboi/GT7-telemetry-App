import pytest,time,json,math
from backend.app.telemetry import demo_sample
from backend.app.engineer import Rules,RULES,Event,Scheduler
from backend.app.config import Settings,Config
from backend.app.storage import Store
from backend.app.analytics import align_laps

# All declared telemetry rules: positive, negative, noisy, stale scheduler evidence.
@pytest.mark.parametrize('name',list(RULES))
def test_each_rule(name):
    cfg=Settings(tyre_limit_c=90,trust_c_fields=True,pit_region=[-1000,-1000,1000,1000],pit_limit_kmh=50,mode='Coaching')
    def sample(trigger):
        s=demo_sample(0,1);v=s.values;v['speed']=15;v['speed_kmh']=54;v['throttle']=0;v['brake']=0;v['tyres']=[75]*4;v['position']=[5000,0,5000]
        if name=='low_fuel':v['fuel']=2 if trigger else 50
        if name=='fuel_critical':v['fuel']=.1 if trigger else 50
        if name=='tyre_hot':v['tyres']=[100 if trigger else 75]*4
        if name=='tyre_imbalance':v['tyres']=[100,70,70,70] if trigger else [75]*4
        if name=='limiter':v['flags']=41 if trigger else 9
        if name=='handbrake':v['flags']=73 if trigger else 9
        if name=='off_surface':v['surface']='DDTT' if trigger else 'TTTT'
        if name=='pedal_overlap':v['throttle']=v['brake']=.5 if trigger else 0
        if name=='pit_speed':v['position']=[0,0,0] if trigger else [5000,0,5000]
        return s
    # tyre_heat_rate isn't in the generic conditions dict - it needs an explicit
    # tyre_heat= argument built from TyreHeatMonitor's own output shape - and it
    # has its own extra warm-up-laps suppression, skipped here to exercise the
    # same persist/cooldown/noise shape every other rule is held to.
    def extra(trigger):
        if name!='tyre_heat_rate':return {}
        return {'tyre_heat':{'rates':[.3 if trigger else 0.]*4,'anomalies':[6. if trigger else 0.]*4,'method':'time baseline'}}
    rule=Rules(cfg);rule.laps_since_start=5;s=sample(False);assert not any(e.category==name for e in rule.evaluate(s,'s',**extra(False)));s.mono=20;assert not any(e.category==name for e in rule.evaluate(s,'s',**extra(False)))
    s=sample(True);s.mono=21;rule.evaluate(s,'s',**extra(True));s.mono=21+RULES[name]['persist']+.1;events=rule.evaluate(s,'s',**extra(True));event=next(e for e in events if e.category==name)
    s.mono+=1;assert not any(e.category==name for e in rule.evaluate(s,'s',**extra(True)))
    noisy=Rules(cfg);noisy.laps_since_start=5
    for i in range(30):
        s=sample(i%2==0);s.mono=i*.1;assert not any(e.category==name for e in noisy.evaluate(s,'s',**extra(i%2==0)))
    log=[];scheduler=Scheduler(cfg,log.append);scheduler.offer(event);assert scheduler.next(event.timestamp+30,'s') is None
    assert any(x['decision']=='expired' for x in log)

def test_spatial_alignment_and_divergence():
    a=[]
    for i in range(400):
        s=demo_sample(i*30/399,i);a.append(s.json())
    result=align_laps(a,a);assert result['available'];assert max(abs(r['delta_s']) for r in result['delta'])<.0001
    b=json.loads(json.dumps(a))
    for s in b:s['values']['position'][1]+=50
    assert not align_laps(a,b)['available']

def test_crash_recovery_and_bounded_queue(tmp_path):
    db=tmp_path/'db';s=Store(db,capacity=4)
    s.put('session',('active','now',None,'driving','live','{}','{}'));s.flush();s.close();s=Store(db)
    assert s.detail('active')['status']=='interrupted';s.close()
    # Deterministic full producer queue, no invisible overwrite.
    import queue
    s=Store.__new__(Store);s.q=queue.Queue(1);s.drops=0
    assert s.put('sample',1);assert not s.put('sample',2);assert s.drops==1 and s.q.get()[1]==1

def test_database_full_keeps_writer_alive(tmp_path):
    s=Store(tmp_path/'db')
    # Inject an actual sqlite failure via wrong binding; same transaction recovery path.
    s.put('sample',('wrong',));s.flush();assert s.error and s.failed_rows==1 and s.thread.is_alive()
    s.put('session',('ok','now','now','completed','demo','{}','{}'));s.flush();assert s.detail('ok') and s.error is None;s.close()

def test_replay_deterministic_rules():
    cfg=Settings();outputs=[]
    for _ in range(2):
        rules=Rules(cfg);events=[]
        for i in range(600):
            s=demo_sample(i/60,i);s.values['fuel']=.1
            events.extend((e.category,e.message) for e in rules.evaluate(s,'s'))
        outputs.append(events)
    assert outputs[0]==outputs[1]
