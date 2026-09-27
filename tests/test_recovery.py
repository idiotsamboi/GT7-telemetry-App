import json
from fastapi.testclient import TestClient
from backend.app.api import create_app
from backend.app.config import Config

def test_invalid_settings_can_launch_without_deleting_original(tmp_path):
 path=tmp_path/'settings.json';path.write_text('{broken json')
 config=Config(tmp_path)
 assert config.recovery_notice and config.settings.ps5_ip is None and not config.settings.hands_free
 assert path.read_text()=='{broken json' and list(tmp_path.glob('settings.invalid-*.json'))

def test_recovery_preserves_data_and_origin_access(tmp_path):
 Config(tmp_path).save({'http_port':18620,'hands_free':False,'speech_enabled':False,'minimal':True,'allowed_origins':[]})
 app=create_app(tmp_path)
 with TestClient(app,base_url='http://127.0.0.1:18620') as c:
  assert c.get('/recovery',headers={'origin':'http://127.0.0.1:18620'}).status_code==200
  assert c.get('/recovery.js').status_code==200
  assert c.post('/api/recovery',json={'action':'live'}).status_code==401
  assert c.post('/api/pair',json={},headers={'origin':'https://evil.example'}).status_code==403
  assert c.post('/api/pair',json={},headers={'origin':'http://127.0.0.1:18620'}).status_code==200
  r=app.state.runtime;r.host_only=True;r.switch('demo');r.sessions.manual_ended=True
  assert c.post('/api/recovery',json={'action':'live'}).status_code==200
  assert not r.host_only and r.source=='live' and not r.sessions.manual_ended
  r.settings.hard_mute=True
  c.post('/api/recovery',json={'action':'display'});assert not r.settings.minimal and r.settings.hard_mute
  c.post('/api/recovery',json={'action':'audio'});assert r.settings.output_device is None and not r.settings.hands_free and not r.settings.hard_mute
  c.post('/api/recovery',json={'action':'connection'});assert r.settings.heartbeat==1 and r.settings.udp_port==33740
  assert (tmp_path/'telemetry.sqlite3').exists()
  assert c.post('/api/recovery',json={'action':'erase_everything'}).status_code==422

def test_invalid_hosting_edit_keeps_existing_mode_and_stop_is_recoverable(tmp_path):
 Config(tmp_path).save({'http_port':18630,'hands_free':False,'speech_enabled':False})
 app=create_app(tmp_path)
 with TestClient(app,base_url='http://127.0.0.1:8000') as c:
  c.post('/api/pair',json={});r=app.state.runtime;r.host_only=True;r.sessions.manual_ended=True
  r.group.hosting={'enabled':True,'host_only':True}
  assert c.post('/api/group/hosting',json={'enabled':True,'port':1,'origins':[]}).status_code==422
  assert r.host_only and r.group.hosting['enabled']
  assert c.post('/api/group/hosting',json={'enabled':False}).status_code==200
  assert not r.host_only and not r.sessions.manual_ended
  assert c.post('/api/group/demo',json={'action':'stop'}).status_code==200


def test_bad_http_address_rejected_before_save(tmp_path):
 Config(tmp_path).save({'http_port':18640,'hands_free':False,'speech_enabled':False})
 app=create_app(tmp_path)
 with TestClient(app,base_url='http://127.0.0.1:8000') as c:
  c.post('/api/pair',json={});settings=c.get('/api/settings').json()
  bad={**settings,'http_host':'192.0.2.254','http_port':18650}
  assert c.put('/api/settings',json=bad).status_code==422
  assert c.get('/api/settings').json()['http_host']==settings['http_host']


def test_malformed_origins_are_rejected_without_overwriting_settings(tmp_path):
 import pytest
 cfg=Config(tmp_path);cfg.save(cfg.settings.model_dump());before=cfg.path.read_bytes()
 for origin in ['http://[','http://localhost:bad','*','http://user:secret@localhost','http://localhost/path']:
  with pytest.raises(ValueError):cfg.save({**cfg.settings.model_dump(),'allowed_origins':[origin]})
  assert cfg.path.read_bytes()==before
