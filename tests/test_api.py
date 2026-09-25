import time,json,io,zipfile
from fastapi.testclient import TestClient
from backend.app.api import create_app
from backend.app.exporting import inspect_bundle,safe_cell

def test_api_demo_record_report_export_replay(tmp_path):
    from backend.app.config import Config
    Config(tmp_path).save({'http_port':18000})
    app=create_app(tmp_path)
    with TestClient(app,base_url="http://127.0.0.1:8000") as c:
        assert c.get('/api/state').status_code==401
        assert c.post('/api/pair',json={},headers={'origin':'https://evil.example'}).status_code==403
        assert c.post('/api/pair',json={}).status_code==200
        assert c.post('/api/control',json={'action':'demo'}).status_code==200
        time.sleep(.5);state=c.get('/api/state').json();assert state['source']=='demo' and state['session_id'];sid=state['session_id']
        assert c.post('/api/command',json={'text':'how much fuel'}).json()['intent']=='fuel'
        assert c.post('/api/control',json={'action':'end'}).status_code==200
        sessions=c.get('/api/sessions').json();assert sessions[0]['status']=='completed'
        detail=c.get(f'/api/sessions/{sid}').json();assert detail['laps'][0]['partial']
        bundle=c.get(f'/api/sessions/{sid}/export');assert bundle.status_code==200
        meta,rows=inspect_bundle(bundle.content);assert len(rows)>5
        assert c.post('/api/import',content=bundle.content).status_code==200
        assert c.post('/api/control',json={'action':'replay','value':sid}).status_code==200
        time.sleep(.1);assert c.get('/api/state').json()['source']=='replay'
        assert c.get('/api/sessions/../../secret').status_code!=200
        assert c.put('/api/settings',json={'heartbeat':0}).status_code==422

def test_bad_bundle_and_csv():
    import pytest
    for value in ['=SUM(A1)','+cmd','@evil','-1']:
        assert safe_cell(value).startswith("'")
    with pytest.raises(Exception):inspect_bundle(b'not zip')
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('../outside','bad')
    with pytest.raises(ValueError):inspect_bundle(b.getvalue())


def test_equal_timestamp_records_export_without_loss(tmp_path):
    from backend.app.storage import Store
    from backend.app.telemetry import demo_sample
    from backend.app.exporting import export_bundle,inspect_bundle
    s=Store(tmp_path/'db');s.put('session',('same','2026-01-01T00:00:00+00:00','2026-01-01T00:01:00+00:00','completed','demo','{}','{}'))
    for i in range(30):
        sample=demo_sample(1,i);s.put('sample',('same','lap',1,i,json.dumps(sample.json())))
    s.flush();p=export_bundle(s,'same',tmp_path);meta,rows=inspect_bundle(p.read_bytes());assert len(rows)==30
    first=s.samples('same',-1e30,10,0);second=s.samples('same',1,10,first[-1]['record_id']);assert second[0]['values']['packet_id']==10
    s.close()
