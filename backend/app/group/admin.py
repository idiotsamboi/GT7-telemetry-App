"""Local administration routes. Never mounted on the public group listener."""
import asyncio, socket
from urllib.parse import urlparse
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import ValidationError
from .service import fail
from .assets import Assets, MAX_UPLOAD
from .public import public_app, registry
from .client import MemberClient, address, request as remote_request


def router():
 r=APIRouter(prefix='/api/group')
 def service(request):return request.app.state.runtime.group
 @r.get('/state')
 async def state(request:Request):
  s=service(request);g=s.active()
  return {'group':g,'leagues':list(s.leagues.values()),'workspaces':list(s.workspaces.values()),'snapshot':s.raw_snapshot(g) if g else None,'listener':getattr(s,'hosting',{'enabled':False}),'client':s.client.snapshot() if s.client else None,'graphics':registry(),'demo':{'error':s.demo.get('error'),'paused':s.demo['paused'],'speed':s.demo['speed'],'members':len(s.demo['members']),'disconnected':list(s.demo['disconnected'])} if s.demo else None,'recording_error':s.recording_error,'recording_drops':s.recording_drops,'replay_now':s.replay_snapshot() if s.replay else None}
 @r.post('/demo')
 async def demo(request:Request):
  from .demo import start_demo
  s=service(request);body=await request.json();action=body.get('action','start')
  if action=='start':return await start_demo(s,body.get('members',8))
  if action=='stop' and not s.demo:
   if s.active() and s.active().get('demo_league'):await s.session_action('close')
   return {'ok':True}
  if not s.demo:fail(409,'No running league demo')
  if action=='pause':s.demo['paused']=True
  elif action=='resume':s.demo['paused']=False
  elif action=='speed':
   if body.get('value') not in (1,2,4):fail(422,'Demo speed must be 1, 2 or 4')
   s.demo['speed']=body['value']
  elif action=='disconnect':
   entry=body.get('entry_id')
   if entry not in s.group()['entries']:fail(422,'Unknown demo driver')
   if entry in s.demo['disconnected']:s.demo['disconnected'].remove(entry)
   else:s.demo['disconnected'].add(entry)
  elif action=='acknowledge':
   member=next((m for m in s.demo['members'] if m['entry']==body.get('entry_id')),None)
   if not member:fail(422,'Choose a synthetic driver')
   for receipt in ('delivered','displayed','acknowledged'):await s.response(member['principal'],{'action':receipt,'message_id':body.get('message_id')})
  elif action=='stop':await s.session_action('close');s.demo=None
  else:fail(422,'Unknown demo action')
  return {'ok':True}
 @r.post('/hosting')
 async def hosting(request:Request):
  s=service(request);body=await request.json()
  async def stop_listener():
   if s.listener:
    for ws in list(s.connections.values()):await ws.close(code=1001)
    s.listener.should_exit=True
    try:await asyncio.wait_for(s.listener_task,5)
    except asyncio.TimeoutError:s.listener_task.cancel();await asyncio.gather(s.listener_task,return_exceptions=True)
    s.listener=None;s.listener_task=None
   if s.runtime.host_only:s.runtime.sessions.manual_ended=False
   s.hosting={'enabled':False};s.runtime.host_only=False;s.runtime.source_generation+=1
  if not body.get('enabled'):
   await stop_listener();return s.hosting
  port=body.get('port',8090);host=body.get('bind','0.0.0.0');origins=body.get('origins',[])
  if not isinstance(port,int) or not 1024<=port<=65535 or port in (s.runtime.settings.http_port,s.runtime.settings.http_port+1):fail(422,'Choose a separate group port between 1024 and 65535')
  if host not in ('0.0.0.0','127.0.0.1'):fail(422,'Group bind must be 0.0.0.0 or 127.0.0.1')
  if not isinstance(origins,list) or not 1<=len(origins)<=16:fail(422,'Specify allowed browser origins, including the host address and port')
  for origin in origins:
   p=urlparse(origin)
   if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.path or p.query or p.fragment:fail(422,'Origins must be exact http(s) addresses without paths')
  same_port=s.listener and getattr(s,'hosting',{}).get('port')==port
  if same_port:await stop_listener()
  sock=socket.socket()
  try:
   if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
   sock.bind((host,port));sock.listen(128);sock.setblocking(False)
  except OSError as e:sock.close();fail(409,'Cannot open group listener: '+str(e))
  if not same_port:await stop_listener()
  import uvicorn
  server=uvicorn.Server(uvicorn.Config(public_app(s,set(origins)),host=host,port=port,access_log=False,log_level='warning',ws_max_size=32768,ws_max_queue=8,ws_per_message_deflate=False,timeout_graceful_shutdown=3))
  s.listener=server;s.listener_task=asyncio.create_task(server.serve(sockets=[sock]));s.hosting={'enabled':True,'port':port,'bind':host,'origins':origins,'host_only':bool(body.get('host_only',False))}
  s.runtime.host_only=s.hosting['host_only'];s.runtime.source_generation+=1
  if s.runtime.host_only:
   s.runtime.sessions.end('interrupted');s.runtime.scheduler.cancel('Host-only mode');s.runtime.speaker.stop();await asyncio.to_thread(s.runtime.mic.close)
  return s.hosting
 @r.post('/leagues')
 async def league(request:Request):return await service(request).league_save(await request.json())
 @r.put('/leagues/{id}')
 async def league_update(id:str,request:Request):return await service(request).league_save(await request.json(),id)
 @r.post('/leagues/{id}/assets')
 async def upload(id:str,request:Request):
  s=service(request);raw=bytearray()
  async for chunk in request.stream():
   raw.extend(chunk)
   if len(raw)>MAX_UPLOAD:fail(413,'Image exceeds 5 MiB')
  async with s.asset_lock:return await asyncio.to_thread(Assets(s).upload,id,bytes(raw))
 @r.get('/assets/{id}/{size}.png')
 async def asset(id:str,size:str,request:Request):return FileResponse(Assets(service(request)).path(id,size),media_type='image/png')
 @r.post('/create')
 async def create(request:Request):return await service(request).create_group(await request.json())
 @r.put('/configure')
 async def configure(request:Request):return await service(request).configure(await request.json())
 @r.post('/invitations')
 async def invite(request:Request):
  b=await request.json();return await service(request).invite(b.get('role'),b.get('expires',3600))
 @r.post('/revoke')
 async def revoke(request:Request):
  s=service(request);b=await request.json();kind=b.get('kind');subject=b.get('id')
  if kind not in ('invite_driver','invite_spectator','overlay'):fail(422,'Remove participants through admission controls')
  await asyncio.to_thread(s.repo.revoke,subject,kind);return {'revoked':True}
 @r.post('/participants/{id}')
 async def admit(id:str,request:Request):return await service(request).admit(id,(await request.json()).get('status'))
 @r.put('/entries/{id}')
 async def entry(id:str,request:Request):return await service(request).entry_update(id,await request.json())
 @r.post('/session/{action}')
 async def session(action:str,request:Request):return await service(request).session_action(action)
 @r.put('/map')
 async def map_update(request:Request):
  b=await request.json();return await service(request).set_map(b.get('points'),b.get('zones',[]))
 @r.post('/map/library')
 async def library_map(request:Request):
  s=service(request);await s.sync_track_library(adopt=True);return {'map_model':s.group().get('map_model'),'pending_map':s.group().get('pending_map')}
 @r.post('/instructions')
 async def instruction(request:Request):return await service(request).instruction(await request.json())
 @r.delete('/instructions/{id}')
 async def cancel(id:str,request:Request):return await service(request).cancel_instruction(id)
 @r.post('/messages')
 async def message(request:Request):return await service(request).message(await request.json())
 @r.post('/decisions')
 async def decision(request:Request):return await service(request).decision(await request.json())
 @r.get('/events')
 async def events(request:Request,after:int=0):
  s=service(request);return await asyncio.to_thread(s.repo.events,s.group()['id'],after)
 @r.post('/workspaces')
 async def workspace(request:Request):return await service(request).save_workspace(await request.json())
 @r.put('/workspaces/{id}')
 async def workspace_update(id:str,request:Request):return await service(request).save_workspace(await request.json(),id)
 @r.post('/workspaces/{id}/take')
 async def take(id:str,request:Request):return await service(request).take(id)
 @r.post('/workspaces/{id}/clear')
 async def clear(id:str,request:Request):return await service(request).clear_program(id)
 @r.get('/workspaces/{id}/program')
 async def program(id:str,request:Request):
  s=service(request);w=s.workspace(id);return s.public_state({'kind':'overlay','group_id':w['group_id'],'subject':id},w)
 @r.post('/workspaces/{id}/share')
 async def share(id:str,request:Request):return await service(request).share_workspace(id,(await request.json()).get('participants',[]))
 @r.post('/workspaces/{id}/credential')
 async def credential(id:str,request:Request):return await service(request).overlay_token(id)
 @r.get('/recordings')
 async def recordings(request:Request):return await asyncio.to_thread(service(request).repo.docs,'group_session')
 @r.post('/replay')
 async def replay(request:Request):return await service(request).replay_control(await request.json())
 @r.post('/connection')
 async def connect(request:Request):
  s=service(request);body=await request.json()
  if body.get('action')=='disconnect':
   if s.client:await s.client.close();s.client=None
   return {'status':'disconnected'}
  base=address(body.get('host',''));payload={k:body[k] for k in ('credential','identity','accepted_sharing') if k in body}
  try:joined=await asyncio.to_thread(remote_request,base,'/group-api/join',payload)
  except ValueError as e:fail(422,str(e))
  if s.client:await s.client.close()
  s.client=MemberClient(s.runtime,base,joined,body.get('rate',5));await s.client.start();return s.client.snapshot()
 @r.post('/connection/response')
 async def response(request:Request):
  c=service(request).client
  if not c:fail(409,'Not connected to a group')
  c.response(await request.json());return {'queued':True}
 return r
