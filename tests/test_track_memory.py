import asyncio,json,math
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from backend.app.tracks import TrackMap,LAYOUTS,REFERENCES
from backend.app.track_geometry import Fingerprint,shape_fit,transform
from backend.app.telemetry import demo_sample
from backend.app.group.service import GroupService

def route(reverse=False,scale=1):
 points=[[scale*(220*math.cos(i*math.tau/180)+35*math.cos(3*i*math.tau/180)),scale*150*math.sin(i*math.tau/180)] for i in range(181)]
 return points[::-1] if reverse else points

def drive(m,number,start,reverse=False,provenance='live',gap=False):
 points=route(reverse)
 for i,p in enumerate(points):
  s=demo_sample(start+i*.2+(2 if gap and i>90 else 0),i);s.provenance=provenance
  s.values.update(position=[p[0],0,p[1]],lap=number+(i==180),flags=1);s.quality=[];m.consume(s)

def clean(m,reverse=False,provenance='live'):
 drive(m,1,0,reverse,provenance);drive(m,2,36.2,reverse,provenance);m.flush()

def test_unknown_confirm_restart_return_and_exit(tmp_path):
 m=TrackMap(tmp_path);clean(m)
 assert m.snapshot()['status']=='Needs confirmation' and len(m.candidates)==1 and not m.library
 m=TrackMap(tmp_path);assert len(m.candidates)==1
 m.confirm(m.candidates[0]['id'],'10');old=m.library['10']['revision']
 m.leave();assert not m.points and not m.bound and m.library['10']['revision']==old
 m=TrackMap(tmp_path);m.select('11',manual=False);clean(m)
 assert m.bound and m.layout_id=='10' and m.snapshot()['status']=='Saved map'

def test_direction_partial_and_identical_geometry(tmp_path):
 m=TrackMap(tmp_path);m.import_map('10',route());m.import_map('11',route())
 assert not m._distinct(m._matches(route(),True))
 assert not m._matches(route(True),True)
 m.leave();drive(m,1,0);m.maintenance(0);assert not m.bound
 assert not Fingerprint(route()).match(route()[:50],True)

def test_reverse_can_match_separate_saved_layout(tmp_path):
 m=TrackMap(tmp_path);m.import_map('11',route());m.import_map('450',route(True))
 hits=m._matches(route(True),True);assert [h['layout_id'] for h in hits]==['450']

def test_gaps_preserve_saved_map_and_demo_cannot_write(tmp_path):
 m=TrackMap(tmp_path);m.import_map('10',route());m.select('10');old=(m.root/'10.json').read_bytes()
 drive(m,1,0);drive(m,2,36.2,gap=True);m.flush();assert (m.root/'10.json').read_bytes()==old
 m.leave();clean(m,provenance='demo');assert not m.queue and not m.candidates
 assert (m.root/'10.json').read_bytes()==old and m.snapshot()['provenance']=='demo'
 m.leave();clean(m,provenance='replay');assert (m.root/'10.json').read_bytes()==old

def test_atomic_failure_history_restore_and_legacy(tmp_path):
 root=tmp_path/'track-maps';root.mkdir();points=route()
 (root/'10.json').write_text(json.dumps({'layout_id':'10','points':points,'kind':'learned driving line'}))
 m=TrackMap(tmp_path);assert json.loads((root/'10.json').read_text())['schema']==2
 original=m.library['10']['revision'];old=(root/'10.json').read_bytes()
 with patch('backend.app.tracks.atomic',side_effect=OSError('disk full')):
  with pytest.raises(OSError):m.import_map('10',route(scale=1.01))
 assert m.library['10']['revision']==original and (root/'10.json').read_bytes()==old
 m.import_map('10',route(scale=1.01));assert m.library['10']['versions'][0]['revision']==original
 m.restore('10',original);assert m.library['10']['revision']==original and m.library['10']['restored_from']==original

def test_similarity_no_stretch_or_reflection_and_rate_limit(tmp_path):
 p=route();world=[[2*x+90,2*y-160] for x,y in p];fit=shape_fit(p,world)
 assert fit['error_m']<.001 and fit['reflected'] is False
 assert max(math.dist(a,b) for a,b in zip(transform(p,fit),world))<.001
 assert shape_fit(p,[[2*x,y] for x,y in p])['error_m']>10
 asymmetric=[[x+20*math.sin(i/7),y+30*math.cos(i/11)] for i,(x,y) in enumerate(p)]
 assert shape_fit(asymmetric,[[-x,y] for x,y in asymmetric])['error_m']>3
 m=TrackMap(tmp_path)
 for now in [0,.1,.2,.49,.5,.7,.99,1]:m.maintenance(now)
 assert m.scan_count==3

def test_offline_coverage_and_stable_ids():
 assert set(REFERENCES)==set(LAYOUTS)
 assert any(v['status']=='unavailable' for v in REFERENCES.values())
 for key,item in REFERENCES.items():
  assert item['layout_id']==key and item['revision'] and item['source_url'].startswith('https://')
  if item['status']=='verified':assert item['approximate'] and len(item['points'])>=20

def test_group_freezes_library_revision(tmp_path):
 tracker=TrackMap(tmp_path);tracker.import_map('10',route())
 service=GroupService(SimpleNamespace(track_map=tracker,store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  league=await service.league_save({'name':'Test'})
  await service.create_group({'name':'Test','event_name':'Test','league_id':league['id'],'layout_id':'10'})
  await service.session_action('start');old=service.active()['map_revision'];assert old
  tracker.import_map('10',route(scale=1.01));await service.sync_track_library()
  assert service.active()['map_revision']==old and service.active()['pending_map']['revision']!=old
  await service.session_action('end');await service.sync_track_library();assert service.active()['map_revision']==old
  await service.session_action('start');assert service.active()['map_revision']!=old and not service.active()['pending_map']
 asyncio.run(check())


def test_local_api_reference_confirm_and_restore(tmp_path):
 from fastapi.testclient import TestClient
 from backend.app.api import create_app
 from backend.app.config import Config
 Config(tmp_path).save({'http_port':18570,'hands_free':False,'speech_enabled':False})
 app=create_app(tmp_path)
 with TestClient(app,base_url='http://127.0.0.1:8000') as c:
  assert c.post('/api/track-map/select',json={'layout_id':'10'}).status_code==401
  c.post('/api/pair',json={})
  preview=c.post('/api/track-map/select',json={'layout_id':'10'}).json()
  assert preview['status']=='Reference outline' and preview['reference']['approximate'] and not preview['points']
  tracker=app.state.runtime.track_map;tracker.leave();clean(tracker)
  candidate=tracker.candidates[0]['id']
  saved=c.post('/api/track-map/confirm',json={'candidate_id':candidate,'layout_id':'10'}).json()
  assert saved['status']=='Saved map' and saved['revision']
  assert c.post('/api/track-map/confirm',json={'candidate_id':candidate,'layout_id':'10'}).status_code==422
  tracker.import_map('10',route(scale=1.01))
  assert c.post('/api/track-map/restore',json={'layout_id':'10','revision':saved['revision']}).status_code==200
  assert c.get('/api/track-map/library').json()['layouts'][0]['layout_id']=='10'
