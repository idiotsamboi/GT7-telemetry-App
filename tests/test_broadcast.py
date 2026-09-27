import math
from backend.app.live_delta import LiveDelta
from backend.app.telemetry import demo_sample
from backend.app.cars import identify

def circle(t,lap,progress):
    s=demo_sample(t,int(t*60));s.mono=t;s.values.update(lap=lap,flags=1,position=[100*math.cos(progress*math.tau),0,100*math.sin(progress*math.tau)]);return s

def test_reference_and_gain_loss():
    delta=LiveDelta()
    for lap in range(1,3):
        for i in range(100):delta.consume(circle((lap-1)*20+i*.2,lap,i/100))
    assert delta.reference is None # opening lap is partial; lap 2 not finished
    delta.consume(circle(40,3,0));assert delta.reference is not None
    for i in range(1,40):delta.consume(circle(40+i*.2,3,i/90))
    assert delta.result['available'] and delta.result['delta_s']<0 and delta.result['trend']==1
    delta.consume(circle(60,4,0))
    for i in range(1,40):delta.consume(circle(60+i*.2,4,i/110))
    assert delta.result['available'] and delta.result['delta_s']>0 and delta.result['trend']==-1

def test_paused_and_wrong_car_have_no_delta():
    delta=LiveDelta();s=circle(0,1,0);s.values['flags']=3;delta.consume(s)
    assert not delta.result['available']
    s=circle(1,1,.1);s.values['car_id']=999999;delta.consume(s)
    assert delta.reference is None
    assert identify(999999)['manufacturer']=='Unknown manufacturer'
    assert identify(82)['manufacturer']=='Toyota'

def test_manual_reference_is_applied_on_next_lap_and_reset_safely():
    delta=LiveDelta();assert not delta.select_last_reference()
    for lap in range(1,3):
        for i in range(100):delta.consume(circle((lap-1)*20+i*.2,lap,i/100))
    delta.consume(circle(40,3,0));assert delta.select_last_reference()
    chosen=delta.manual_reference
    for i in range(1,100):delta.consume(circle(40+i*.2,3,i/100))
    delta.consume(circle(60,4,0));assert delta.reference is chosen[0]
    delta.consume(circle(60.2,1,0));assert delta.manual_reference is None and delta.partial
