import time,json,io,zipfile
import subprocess,sys
from fastapi.testclient import TestClient
from backend.app.api import create_app
from backend.app.exporting import inspect_bundle,safe_cell

def test_backend_import_has_no_filesystem_initialization():
    code="from backend.app.config import Config\ndef forbidden(*args,**kwargs): raise AssertionError('Import created configuration')\nConfig.__init__=forbidden\nimport backend.app.api\n"
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

def test_request_catalog_and_speaker_only_test(tmp_path,monkeypatch):
    from backend.app.config import Config
    from backend.app.voice import Speaker
    Config(tmp_path).save({'http_port':18120,'speech_enabled':False,'hard_mute':True,'voice_volume':0})
    spoken=[]
    monkeypatch.setattr(Speaker,'speak',lambda self,text,settings,priority=2:spoken.append((text,settings.output_device)) or True)
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1:8000') as client:
        client.post('/api/pair',json={})
        catalog=client.get('/api/engineer/requests').json()
        assert catalog['count']==100 and len(catalog['requests'])==100
        assert client.post('/api/control',json={'action':'speaker_test'}).status_code==200
        settings=client.get('/api/settings').json()
        assert settings['speech_enabled'] and not settings['hard_mute'] and settings['voice_volume']==80
        assert len(spoken)==1 and spoken[0][1] is None

def test_api_demo_record_report_export_replay(tmp_path):
    from backend.app.config import Config
    Config(tmp_path).save({'http_port':18000,'speech_enabled':False})
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

def test_track_selection_and_map_api(tmp_path):
 from backend.app.config import Config
 Config(tmp_path).save({'http_port':18140,'hands_free':False,'speech_enabled':False})
 with TestClient(create_app(tmp_path),base_url='http://127.0.0.1:8000') as c:
  assert c.get('/api/tracks').status_code==401
  c.post('/api/pair',json={})
  assert len(c.get('/api/tracks').json())==41
  settings=c.get('/api/settings').json();settings['track_id']='10'
  result=c.put('/api/settings',json=settings)
  assert result.status_code==200 and result.json()['settings']['layout']=='Suzuka Circuit'
  points=[[i,i*2] for i in range(20)]
  assert c.put('/api/track-map',json={'layout_id':'10','points':points}).status_code==200
  assert c.get('/api/track-map').json()['complete']
  assert c.put('/api/track-map',json={'layout_id':'../escape','points':points}).status_code==422
  settings['track_id']='nonsense';assert c.put('/api/settings',json=settings).status_code==422
