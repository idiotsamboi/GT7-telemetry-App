from backend.app.live_analysis import ReceptionTest,LiveAnalysis
from backend.app.telemetry import demo_sample

def sample(t):
    s=demo_sample(t,int(t*60));s.mono=t;s.provenance='live';return s

def test_reception_constant_fields_and_gap():
    check=ReceptionTest(0,{'gaps':0},1)
    for i in range(900):check.observe(sample(i/60),i/60)
    result=check.snapshot(15,{'gaps':0},1)
    assert result['status']=='healthy' and result['rate_hz']==60
    assert result['fields_seen']>20
    assert check.snapshot(30,{'gaps':40},1)==result
    check=ReceptionTest(0,{'gaps':10},1)
    check.observe(sample(1),1)
    assert check.snapshot(15,{'gaps':11},1)['status']=='degraded'

def test_reception_no_data_and_source_change():
    assert ReceptionTest(0,{},1).snapshot(15,{},1)['status']=='no_data'
    assert ReceptionTest(0,{},1).snapshot(2,{},2)['status']=='cancelled'

def test_analysis_derivative_and_bounded_window():
    analysis=LiveAnalysis()
    for i in range(1000):
        s=sample(i*.2);s.values.update(lap=1,speed=20+i*.2,throttle=.2,brake=.2,flags=1)
        analysis.consume(s)
    assert len(analysis.window)<=150
    assert abs(analysis.result['longitudinal_g']-.1)<.02
    assert analysis.result['overlap_percent']==100
    s=sample(201);s.values['lap']=2;analysis.consume(s)
    assert analysis.result['longitudinal_g'] is None

def test_analysis_pause_missing_and_braking():
    analysis=LiveAnalysis()
    for i in range(10):
        s=sample(i*.25);s.values.update(flags=1,brake=.5 if i<8 else 0);analysis.consume(s)
    assert len(analysis.episodes)==1
    s=sample(3);s.values['flags']=3;analysis.consume(s)
    assert not analysis.result['available']
    s=sample(4);s.values.update(flags=1,speed=None);analysis.consume(s)
    assert not analysis.result['available']
