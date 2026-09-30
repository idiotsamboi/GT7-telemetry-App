"""Dedicated LAN surface. Deliberately contains no local administration routes."""
import asyncio,json,time,secrets,logging
from pathlib import Path
from fastapi import FastAPI,Request,WebSocket
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from .graphics import GRAPHIC_TEMPLATES,describe
from ..core.errors import AppError
from .service import fail
from .principals import allowed,principal_from_dict
from ..core.permissions import capabilities_for
from .protocol import Codec,ReliableChannel,RELIABLE_TYPES,SERVER_CAPABILITIES,CLOSE_PROTOCOL_INCOMPATIBLE,decode,negotiate,encode,PROTOCOL_VERSION
from ..core.version import APP_VERSION
log=logging.getLogger('network')
from .assets import Assets
ROOT=Path(__file__).resolve().parents[3]

def public_app(service,origins):
 app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);assets=Assets(service);browser_connections=set()
 @app.exception_handler(ValidationError)
 async def invalid(request,error):return JSONResponse({'detail':'Invalid request: '+str(error)[:400]},422)
 @app.exception_handler(AppError)
 async def app_error(request,error):return JSONResponse({'detail':error.detail},error.status_code)
 @app.middleware('http')
 async def guard(request,call_next):
  origin=request.headers.get('origin');host=request.headers.get('host','')
  if origin and origin not in origins:return JSONResponse({'detail':'Origin not permitted'},403)
  if host not in {o.split('://',1)[-1] for o in origins}:return JSONResponse({'detail':'Host not permitted'},403)
  if request.method not in ('GET','HEAD','OPTIONS') and request.url.path!='/group-api/join' and not origin and not request.headers.get('authorization'):return JSONResponse({'detail':'Origin or native credential required'},403)
  length=request.headers.get('content-length','0')
  if not length.isdigit():return JSONResponse({'detail':'Invalid content length'},400)
  if int(length)>65536:return JSONResponse({'detail':'Payload too large'},413)
  try:service.limit(('http',request.client.host),300,10)
  except AppError as error:return JSONResponse({'detail':error.detail},error.status_code)
  response=await call_next(request);response.headers['Referrer-Policy']='no-referrer';response.headers['X-Content-Type-Options']='nosniff';response.headers['Cache-Control']='no-store';response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'";return response
 async def principal(request,overlay=False):
  token=request.headers.get('authorization','').removeprefix('Bearer ') or request.cookies.get('group_session')
  return await service.authenticate(token,('overlay',) if overlay else ('driver','spectator'))
 @app.get('/group-api/info')
 async def info():
  g=service.active();return {'version':1,'enabled':bool(g),'name':g['name'] if g else None,'required_sharing':g['required_sharing'] if g else [],'policy_revision':g['policy_revision'] if g else None,'locked':g['join_locked'] if g else True,'graphics':registry()}
 @app.post('/group-api/join')
 async def join(request:Request):
  service.limit(('join',request.client.host),10,60);result=await service.join(await request.json());response=JSONResponse(result);response.set_cookie('group_session',result['token'],httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=7*86400,path='/');return response
 @app.get('/group-api/me')
 async def me(request:Request):
  p=await principal(request);g,member=service.member(p);return {'participant':member,'group_id':g['id'],'session_id':g['session_id'],'required_sharing':g['required_sharing'],'policy_revision':g['policy_revision'],'layout_id':g['layout_id'],'provenance':g['provenance'],'capabilities':sorted(capabilities_for(principal_from_dict(p,member,g)))}
 @app.get('/group-api/state')
 async def state(request:Request):return service.public_state(await principal(request))
 @app.post('/group-api/consent')
 async def consent(request:Request):return await service.consent(await principal(request),(await request.json()).get('categories',[]))
 @app.post('/group-api/response')
 async def response(request:Request):return await service.response(await principal(request),await request.json())
 @app.get('/group-api/workspaces')
 async def workspaces(request:Request):
  p=await principal(request);_,member=service.member(p)
  if not allowed(p,'graphics.view',member=member):fail(403,'Broadcaster required')
  return [w for w in service.workspaces.values() if w['group_id']==p['group_id'] and p['subject'] in [w['owner'],*w['shared_with']]]
 @app.post('/group-api/workspaces')
 async def create_workspace(request:Request):return await service.save_workspace(await request.json(),principal=await principal(request))
 @app.put('/group-api/workspaces/{id}')
 async def update_workspace(id:str,request:Request):return await service.save_workspace(await request.json(),id,await principal(request))
 @app.post('/group-api/workspaces/{id}/take')
 async def take(id:str,request:Request):return await service.take(id,await principal(request))
 @app.post('/group-api/workspaces/{id}/focus-battle')
 async def focus_battle_public(id:str,request:Request):
  body=await request.json();return await service.focus_battle(body.get('battle_id'),id,body.get('take',False),body.get('ensure_graphics',True),await principal(request))
 @app.post('/group-api/workspaces/{id}/credential')
 async def output_token(id:str,request:Request):return await service.overlay_token(id,await principal(request))
 @app.post('/group-api/ticket')
 async def ticket(request:Request):
  body=await request.json();p=await principal(request,body.get('overlay',False));id=body.get('workspace_id')
  if p['kind']=='overlay':
   if not allowed(p,'overlay.read',{'id':id}):fail(403,'Overlay scope mismatch')
   service.workspace(id)
  elif id:service.workspace(id,p)
  key=secrets.token_urlsafe(24);service.tickets={k:v for k,v in service.tickets.items() if v['expires']>time.time()}
  if len(service.tickets)>=512:fail(429,'Too many pending tickets')
  token=request.headers.get('authorization','').removeprefix('Bearer ') or request.cookies.get('group_session')
  service.tickets[key]={'principal':p,'expires':time.time()+20,'workspace':id,'token':token};return {'ticket':key}
 @app.websocket('/group-api/subscribe')
 async def subscribe(ws:WebSocket):
  if ws.headers.get('origin') not in origins:await ws.close(code=1008);return
  if len(browser_connections)>=64:await ws.close(code=1013);return
  browser_connections.add(ws)
  await ws.accept()
  try:
   message=await asyncio.wait_for(ws.receive_json(),5);ticket=service.tickets.pop(message.get('ticket',''),None);v2=message.get('protocol')==2;seq=0
   if not ticket or ticket['expires']<=time.time():await ws.close(code=1008);return
   while True:
    p=await service.authenticate(ticket['token']);w=service.workspace(ticket['workspace'],None if p['kind']=='overlay' else p) if ticket['workspace'] else None
    frame=service.public_state(p,w);seq+=1
    await asyncio.wait_for(ws.send_json(encode('state',{'state':frame},sender='host',session=frame.get('session_id'),seq=seq) if v2 else frame),1);await asyncio.sleep(.2)
  except Exception:
   try:await ws.close(code=1008)
   except Exception:pass
  finally:browser_connections.discard(ws)
 @app.websocket('/group-api/publish')
 async def publish(ws:WebSocket):
  # Native clients do not send Origin. Browser clients cannot impersonate this channel.
  if ws.headers.get('origin') is not None:await ws.close(code=1008);return
  token=ws.headers.get('authorization','').removeprefix('Bearer ')
  try:p=await service.authenticate(token,('driver',));g,member=service.member(p)
  except Exception:await ws.close(code=1008);return
  if not allowed(p,'telemetry.publishOwn',member=member) or p['subject'] in service.connections:await ws.close(code=1008);return
  await ws.accept();service.connections[p['subject']]=ws
  codec=Codec(session=g['session_id']);channel=ReliableChannel()
  try:
   # Greeting stays a flat v1 message so old clients work; the extra keys advertise v2.
   await ws.send_json({'type':'hello','session_id':g['session_id'],'host_time':time.time(),'protocol':PROTOCOL_VERSION,'app_version':APP_VERSION,'server_capabilities':list(SERVER_CAPABILITIES)})
   while True:
    raw=await asyncio.wait_for(ws.receive_text(),15)
    decoded=decode(raw,max_bytes=32768,role='driver');env=decoded.envelope;body=env.payload
    if decoded.legacy:
     if not codec.v2:service.legacy_clients.note('driver:'+p['subject'],role='driver')
    else:codec.v2=True
    service.limit(('native',p['subject']),160,10);await service.authenticate(token,('driver',));kind=env.type
    if not decoded.legacy and kind in RELIABLE_TYPES and channel.seen(env.id):
     cached=channel.reply_for(env.id)
     if cached is not None:await ws.send_json(cached)
     continue
    reply=None
    if kind=='hello':
     deal=negotiate(body)
     if not deal.compatible:
      log.warning('group client rejected: protocol incompatible',extra={'event':'protocol_incompatible','details':{'role':'driver','reason':deal.reason[:120]}})
      await ws.send_json(codec.out('error',{'message':deal.reason,'code':'protocol_incompatible'}));await ws.close(code=CLOSE_PROTOCOL_INCOMPATIBLE);return
     codec.v2=(deal.protocol or 1)>=2;reply=codec.out('hello',deal.reply_payload(session_id=g['session_id'],host_time=time.time()))
    elif kind=='telemetry':accepted=service.telemetry(p,body['packet']);reply=codec.out('state',{'accepted':accepted,'state':service.public_state(p)})
    elif kind=='lap':reply=codec.out('lap_ack',await service.lap_event(p,body['lap']),reply_to=env.id)
    elif kind=='response':reply=codec.out('response_ack',await service.response(p,body['response']),reply_to=env.id)
    elif kind=='ping':reply=codec.out('pong',{'source':body.get('source'),'host_time':time.time(),'state':service.public_state(p)})
    elif kind=='clock':
     uncertainty=body.get('uncertainty_ms')
     if isinstance(uncertainty,(int,float)) and 0<=uncertainty<=60000:service.boots[p['subject']]={'uncertainty_ms':uncertainty,'offset_ms':body.get('offset_ms')}
    elif kind=='ack':channel.ack(str(body.get('id','')))
    else:fail(422,'Unknown message')
    if reply is not None:
     if not decoded.legacy and kind in RELIABLE_TYPES:channel.remember(env.id,reply)
     await ws.send_json(reply)
  except Exception as error:
   try:await ws.send_json(codec.out('error',{'message':str(getattr(error,'detail','Connection ended'))[:300]}));await ws.close(code=1008)
   except Exception:pass
  finally:
   if service.connections.get(p['subject']) is ws:service.connections.pop(p['subject'],None)
 @app.get('/media/{id}/{size}.png')
 async def asset(id:str,size:str,request:Request):
  token=request.query_params.get('access') or request.cookies.get('group_session');p=await service.authenticate(token);g=service.group(p['group_id']);item=service.repo.get('asset',id)
  if p['kind']!='overlay':
   _,member=service.member(p)
   if member['status']!='admitted':fail(403,'Admission required')
  if not item or item['league_id']!=g['league_id']:fail(404,'Asset not found')
  return FileResponse(assets.path(id,size),media_type='image/png',headers={'Cache-Control':'private,max-age=3600'})
 dist=ROOT/'frontend/dist'
 @app.get('/')
 async def index():return RedirectResponse('/group')
 @app.get('/group')
 @app.get('/overlay/{id}')
 async def shell(id:str=''):return FileResponse(dist/'index.html')
 for name in ('assets','cars','brands','tracks'):
  if (dist/name).is_dir():app.mount('/'+name,StaticFiles(directory=dist/name),name=name)
 return app

def registry():
 # Rows come from the template registry (group/graphics.py); the keys are unchanged plus category, required_models and lifecycle.
 return [describe(t) for t in GRAPHIC_TEMPLATES]
