"""Group admission and API boundary regression tests; no LAN listener or GT7 socket."""
from types import SimpleNamespace
import asyncio
import pytest
from backend.app.core.errors import AppError
from fastapi.testclient import TestClient
from backend.app.group.service import GroupService
from backend.app.group.public import public_app
from backend.app.config import Config
from backend.app.api import create_app


def test_local_group_routes_are_authenticated_and_validate(tmp_path):
 Config(tmp_path).save({'http_port':18320,'hands_free':False,'speech_enabled':False})
 with TestClient(create_app(tmp_path),base_url='http://127.0.0.1:8000') as c:
  assert c.get('/api/group/state').status_code==401
  c.post('/api/pair',json={})
  league=c.post('/api/group/leagues',json={'name':'Test league'}).json()
  group=c.post('/api/group/create',json={'name':'Test race','event_name':'Test event','league_id':league['id']})
  assert group.status_code==200
  assert c.post('/api/group/instructions',json={'flag':'invented'}).status_code==422
  assert c.put('/api/group/map',json={'points':[]}).status_code==422
  assert c.get('/api/group/state').json()['listener']['enabled'] is False
  assert c.post('/api/group/session/start').status_code==200
  assert c.post('/api/group/session/finalize').status_code==409
  assert c.post('/api/group/session/end').status_code==200
  assert c.post('/api/group/session/finalize').status_code==200


def test_group_admission_revocation_and_public_boundary(tmp_path):
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def setup():
  league=await s.league_save({'name':'Synthetic league'})
  await s.create_group({'name':'Synthetic group','event_name':'Test event','league_id':league['id']})
  return await s.invite('driver')
 invite=asyncio.run(setup())
 with TestClient(public_app(s,{'http://testserver'})) as c:
  assert c.get('/api/settings').status_code==404
  assert c.get('/group-api/info',headers={'origin':'http://evil.test'}).status_code==403
  joined=c.post('/group-api/join',json={'credential':invite['credential'],'identity':{'display_name':'Synthetic driver','number':'1'}})
  assert joined.status_code==200,joined.text
  token=joined.json()['token'];pid=joined.json()['participant']['id']
  assert c.get('/group-api/me').json()['participant']['status']=='pending'
  asyncio.run(s.admit(pid,'admitted'))
  assert c.get('/group-api/me').json()['participant']['status']=='admitted'
  assert c.post('/group-api/workspaces',json={},headers={'origin':'http://testserver'}).status_code==403
  asyncio.run(s.admit(pid,'removed'))
  assert c.get('/group-api/me').status_code in (401,403)
  with pytest.raises(AppError):asyncio.run(s.authenticate(token))


def test_invitation_rotation_does_not_revoke_member(tmp_path):
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  league=await s.league_save({'name':'Test'})
  await s.create_group({'name':'Test','event_name':'Test event','league_id':league['id'],'approval':False})
  invitation=await s.invite('driver')
  join=await s.join({'credential':invitation['credential'],'identity':{'display_name':'Driver','number':'7'}})
  s.repo.revoke(invitation['id'],'invite_driver')
  assert (await s.authenticate(join['token']))['kind']=='driver'
  with pytest.raises(AppError):await s.join({'credential':invitation['credential'],'identity':{'display_name':'Other'}})
 asyncio.run(check())

def test_publishing_binding_privacy_delay_and_workspace_isolation(tmp_path):
 import time
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  league=await s.league_save({'name':'Test'})
  g=await s.create_group({'name':'Test','event_name':'Test event','league_id':league['id'],'approval':False})
  invitation=await s.invite('driver')
  joined=await s.join({'credential':invitation['credential'],'identity':{'display_name':'Driver','number':'3'},'accepted_sharing':['basic','fuel']})
  principal=await s.authenticate(joined['token']);p=joined['participant']
  packet={'version':1,'group_id':g['id'],'session_id':g['session_id'],'participant_id':p['id'],'entry_id':p['entry_id'],'boot_id':'test-boot','sequence':1,'source_mono':1,'source_utc':time.time(),'provenance':'live','layout_id':'','local_session_id':'local','values':{'car_id':1,'lap':None,'fuel':31.5,'flags':1}}
  assert s.telemetry(principal,packet)
  assert not s.telemetry(principal,packet)
  with pytest.raises(AppError):s.telemetry(principal,{**packet,'entry_id':'spoofed'})
  spec=await s.invite('spectator');view=await s.join({'credential':spec['credential'],'identity':{'display_name':'Viewer'}});vp=await s.authenticate(view['token'])
  assert 'fuel' not in s.public_state(vp)['entries'][0]['fields']
  assert s.public_state(principal)['entries'][0]['fields']['fuel']['value']==31.5
  own=await s.save_workspace({'name':'Private workspace'},principal=vp)
  with pytest.raises(AppError):s.workspace(own['id'],principal)
  before=own['program_revision'];await s.save_workspace({'name':'Draft change'},own['id'],vp)
  assert s.workspace(own['id'])['program_revision']==before
  assert s.workspace(own['id'])['program']['name']=='Private workspace'
  await s.take(own['id'],vp)
  assert s.workspace(own['id'])['program']['name']=='Draft change'
  await s.configure({'delay_s':10})
  assert s.public_state(vp)['buffering']
  await s.configure({'required_sharing':['basic','telemetry']})
  with pytest.raises(AppError):s.telemetry(principal,{**packet,'sequence':2})
 asyncio.run(check())

def test_entry_reassignment_revokes_the_old_drivers_own_row_access(tmp_path):
 # Regression: entry_update() only updated the NEW participant's entry_id;
 # the driver reassigned AWAY from an entry kept a stale entry_id pointing at
 # it. filter_snapshot()'s "is this row mine" check matched on that stale
 # entry_id, so the old driver's still-valid credential would see the row
 # filtered by the NEW driver's own (broader) sharing consent instead of the
 # group's publication redaction - a privacy leak across a driver swap.
 import time
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  league=await s.league_save({'name':'Test'})
  g=await s.create_group({'name':'Test','event_name':'Test event','league_id':league['id'],'approval':False})
  inv1=await s.invite('driver');old=await s.join({'credential':inv1['credential'],'identity':{'display_name':'Old driver','number':'1'},'accepted_sharing':['basic','fuel']})
  inv2=await s.invite('driver');new=await s.join({'credential':inv2['credential'],'identity':{'display_name':'New driver','number':'2'},'accepted_sharing':['basic','fuel']})
  old_principal=await s.authenticate(old['token']);new_principal=await s.authenticate(new['token'])
  entry_id=old['participant']['entry_id']
  packet={'version':1,'group_id':g['id'],'session_id':g['session_id'],'participant_id':old['participant']['id'],'entry_id':entry_id,'boot_id':'b','sequence':1,'source_mono':1,'source_utc':time.time(),'provenance':'live','layout_id':'','local_session_id':'l','values':{'car_id':1,'lap':None,'fuel':12.3,'flags':1}}
  assert s.telemetry(old_principal,packet)
  def row_fields():return next(r for r in s.public_state(old_principal)['entries'] if r['entry_id']==entry_id)['fields']  # entries[0] isn't reliably this entry - both are equally "unranked" with no position yet
  # Before reassignment this row genuinely is old_principal's own - seeing their
  # own broader personal consent (fuel) here is correct, existing behavior, not
  # the bug; the leak only appears once the row stops being theirs (below).
  assert 'fuel' in row_fields()
  await s.entry_update(entry_id,{'participant_id':new['participant']['id']})
  assert s.member(old_principal)[1]['entry_id'] is None  # old driver's own entry_id was cleared, not left dangling
  # The old driver's credential is still otherwise valid (no revocation on reassignment); it must now
  # be treated exactly like any other viewer - the group's basic-only publication, not the new driver's
  # broader personal consent.
  assert 'fuel' not in row_fields()
 asyncio.run(check())


def test_failed_storage_does_not_publish_instruction(tmp_path,monkeypatch):
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  league=await s.league_save({'name':'Test'})
  await s.create_group({'name':'Test','event_name':'Test','league_id':league['id']})
  def broken(*a,**k):raise OSError('Disk unavailable')
  monkeypatch.setattr(s.repo,'commit',broken)
  with pytest.raises(OSError):await s.instruction({'flag':'red','reason':'Synthetic test'})
  assert s.group()['instructions']==[]
 asyncio.run(check())


def test_native_browser_handshake_and_scoped_overlay(tmp_path):
 from starlette.websockets import WebSocketDisconnect
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def setup():
  league=await s.league_save({'name':'Test'})
  await s.create_group({'name':'Test','event_name':'Test','league_id':league['id'],'approval':False})
  invite=await s.invite('driver');joined=await s.join({'credential':invite['credential'],'identity':{'display_name':'Driver'}})
  w=await s.save_workspace({'name':'Output'});output=await s.overlay_token(w['id']);return joined,w,output
 joined,w,output=asyncio.run(setup())
 with TestClient(public_app(s,{'http://testserver'})) as c:
  with pytest.raises(WebSocketDisconnect):
   with c.websocket_connect('/group-api/publish',headers={'origin':'http://testserver','authorization':'Bearer '+joined['token']}):pass
  with c.websocket_connect('/group-api/publish',headers={'authorization':'Bearer '+joined['token']}) as ws:
   assert ws.receive_json()['type']=='hello'
   ws.send_json({'type':'ping','source':1})
   assert 'state' in ws.receive_json()
  headers={'origin':'http://testserver','authorization':'Bearer '+output['credential']}
  assert c.post('/group-api/ticket',headers=headers,json={'overlay':True,'workspace_id':'wrong'}).status_code==403
  ticket=c.post('/group-api/ticket',headers=headers,json={'overlay':True,'workspace_id':w['id']}).json()['ticket']
  with c.websocket_connect('/group-api/subscribe',headers={'origin':'http://testserver'}) as ws:
   ws.send_json({'ticket':ticket});assert ws.receive_json()['workspace']['name']=='Output'
  assert c.post('/group-api/response',headers=headers,json={'action':'assistance'}).status_code==401

def test_branding_upload_reencodes_and_rejects_unsafe_input(tmp_path):
 import io
 from PIL import Image
 from backend.app.group.assets import Assets
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 league=asyncio.run(s.league_save({'name':'Raster tests'}));assets=Assets(s)
 raw=io.BytesIO();Image.new('RGBA',(20,10),(255,0,0,0)).save(raw,format='PNG')
 asset=assets.upload(league['id'],raw.getvalue())
 with Image.open(assets.path(asset['id'])) as image:assert image.mode=='RGBA' and image.size==(20,10)
 with pytest.raises(AppError):assets.upload(league['id'],b'<svg xmlns="http://www.w3.org/2000/svg"/>')
 with pytest.raises(AppError):assets.path('../../secret')
 with pytest.raises(AppError):assets.upload(league['id'],b'x'*(5*1024*1024+1))


def test_wrapped_zone_uncertainty_and_independent_cancellation():
 from backend.app.group.timing import applicable_flags,in_zone
 zone={'id':'z','start':.9,'end':.1}
 assert in_zone(.95,zone) and in_zone(.05,zone) and not in_zone(.5,zone)
 common={'version':1,'scope':'zone','target':'z','cancelled':False,'expires':None}
 flags=[{**common,'id':'yellow','flag':'yellow'},{**common,'id':'double','flag':'double_yellow'},{**common,'scope':'global','id':'red','flag':'red'}]
 visible=applicable_flags(flags,'driver',None,[zone],1)
 assert visible[0]['flag']=='red'
 assert next(f for f in visible if f['id']=='double')['applicability']=='uncertain'
 flags[1]['cancelled']=True
 assert {f['id'] for f in applicable_flags(flags,'driver',.95,[zone],1)}=={'yellow','red'}

@pytest.mark.parametrize('count',[4,8,16])
def test_league_demo_is_synthetic_and_preserves_existing_group(tmp_path,count):
 from backend.app.group.demo import start_demo,tick
 import time
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  result=await start_demo(s,count);g=s.group()
  assert g['provenance']=='demo' and g['demo_league']
  assert len(g['entries'])==count and len(g['zones'])==2
  assert len(s.workspaces[result['workspace_id']]['program']['graphics'])==10
  assert all('[DEMO]' in r['identity']['display_name'] for r in s.raw_snapshot()['entries'])
  assert all(r['progress'] is not None for r in s.raw_snapshot()['entries'])
  original=s.demo['elapsed'];s.demo['paused']=True;await tick(s);assert s.demo['elapsed']==original
  s.demo['paused']=False;s.demo['last']=time.monotonic()-.5;await tick(s);assert s.demo['elapsed']>original
  await s.session_action('close');await tick(s);assert s.demo is None
  league=await s.league_save({'name':'Live league'});await s.create_group({'name':'Real event','event_name':'Race','league_id':league['id']})
  with pytest.raises(AppError):await start_demo(s,8)
  assert s.group()['name']=='Real event'
 asyncio.run(check())


def test_clear_program_preserves_draft(tmp_path):
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  league=await s.league_save({'name':'Test'});await s.create_group({'name':'Test','event_name':'Race','league_id':league['id']})
  w=await s.save_workspace({'graphics':[{'id':'tower','template':'timing'}]});await s.take(w['id']);cleared=await s.clear_program(w['id'])
  assert cleared['draft']['graphics'][0]['visible'] and not cleared['program']['graphics'][0]['visible']
  assert cleared['program_revision']==2
 asyncio.run(check())

def test_new_graphic_templates_and_style_presets_are_valid(tmp_path):
 from pydantic import ValidationError
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  league=await s.league_save({'name':'Test'});await s.create_group({'name':'Test','event_name':'Race','league_id':league['id']})
  new_templates=['fastest_lap','class_leader','penalty','podium','sponsor']
  w=await s.save_workspace({'graphics':[{'id':t,'template':t} for t in new_templates]})
  assert {g['template'] for g in w['draft']['graphics']}==set(new_templates)
  with pytest.raises(ValidationError):await s.save_workspace({'graphics':[{'id':'bad','template':'not_a_template'}]},w['id'])
  for preset in ('formula','endurance','minimal','neon','vintage','rally','oval','carbon','heritage','holo'):
   saved=await s.save_workspace({'preset':preset},w['id'])
   assert saved['draft']['preset']==preset
  with pytest.raises(ValidationError):await s.save_workspace({'preset':'not_a_style'},w['id'])
 asyncio.run(check())


def test_delayed_take_keeps_previous_program_until_timeline_reaches_change(tmp_path,monkeypatch):
 import time
 s=GroupService(SimpleNamespace(store=SimpleNamespace(path=tmp_path/'db.sqlite'),config=SimpleNamespace(root=tmp_path)))
 async def check():
  league=await s.league_save({'name':'Test'});g=await s.create_group({'name':'Test','event_name':'Race','league_id':league['id']})
  w=await s.save_workspace({'name':'First scene','graphics':[{'id':'tower','template':'timing'}]});await s.take(w['id']);past=s.raw_snapshot()
  await asyncio.sleep(.005)
  await s.save_workspace({'name':'Second scene','graphics':[{'id':'map','template':'map'}]},w['id']);await s.take(w['id'])
  monkeypatch.setattr(s,'delayed_snapshot',lambda group,delay:past)
  result=s.public_state({'kind':'overlay','group_id':g['id'],'subject':w['id']},s.workspace(w['id']))
  assert result['program_revision']==1 and result['workspace']['name']=='First scene'
 asyncio.run(check())
