"""Dedicated LAN surface. Deliberately contains no local administration routes."""
import asyncio,json,time,secrets
from pathlib import Path
from fastapi import FastAPI,Request,WebSocket,HTTPException
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from .models import GRAPHICS
from .service import fail
from .assets import Assets
ROOT=Path(__file__).resolve().parents[3]

def public_app(service,origins):
 app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);assets=Assets(service);browser_connections=set()
 @app.exception_handler(ValidationError)
 async def invalid(request,error):return JSONResponse({'detail':'Invalid request: '+str(error)[:400]},422)
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
  except HTTPException as error:return JSONResponse({'detail':error.detail},error.status_code)
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
  p=await principal(request);g,member=service.member(p);return {'participant':member,'group_id':g['id'],'session_id':g['session_id'],'required_sharing':g['required_sharing'],'policy_revision':g['policy_revision'],'layout_id':g['layout_id'],'provenance':g['provenance']}
 @app.get('/group-api/state')
 async def state(request:Request):return service.public_state(await principal(request))
 @app.post('/group-api/consent')
 async def consent(request:Request):return await service.consent(await principal(request),(await request.json()).get('categories',[]))
 @app.post('/group-api/response')
 async def response(request:Request):return await service.response(await principal(request),await request.json())
 @app.get('/group-api/workspaces')
 async def workspaces(request:Request):
  p=await principal(request);_,member=service.member(p)
  if member['role']!='spectator' or member['status']!='admitted':fail(403,'Broadcaster required')
  return [w for w in service.workspaces.values() if w['group_id']==p['group_id'] and p['subject'] in [w['owner'],*w['shared_with']]]
 @app.post('/group-api/workspaces')
 async def create_workspace(request:Request):return await service.save_workspace(await request.json(),principal=await principal(request))
 @app.put('/group-api/workspaces/{id}')
 async def update_workspace(id:str,request:Request):return await service.save_workspace(await request.json(),id,await principal(request))
 @app.post('/group-api/workspaces/{id}/take')
 async def take(id:str,request:Request):return await service.take(id,await principal(request))
 @app.post('/group-api/workspaces/{id}/credential')
 async def output_token(id:str,request:Request):return await service.overlay_token(id,await principal(request))
 @app.post('/group-api/ticket')
 async def ticket(request:Request):
  body=await request.json();p=await principal(request,body.get('overlay',False));id=body.get('workspace_id')
  if p['kind']=='overlay':
   if p['subject']!=id:fail(403,'Overlay scope mismatch')
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
   message=await asyncio.wait_for(ws.receive_json(),5);ticket=service.tickets.pop(message.get('ticket',''),None)
   if not ticket or ticket['expires']<=time.time():await ws.close(code=1008);return
   while True:
    p=await service.authenticate(ticket['token']);w=service.workspace(ticket['workspace'],None if p['kind']=='overlay' else p) if ticket['workspace'] else None
    await asyncio.wait_for(ws.send_json(service.public_state(p,w)),1);await asyncio.sleep(.2)
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
  if member['status']!='admitted' or p['subject'] in service.connections:await ws.close(code=1008);return
  await ws.accept();service.connections[p['subject']]=ws
  try:
   await ws.send_json({'type':'hello','session_id':g['session_id'],'host_time':time.time()})
   while True:
    raw=await asyncio.wait_for(ws.receive_text(),15)
    if len(raw)>32768:fail(413,'Packet too large')
    message=json.loads(raw);service.limit(('native',p['subject']),160,10);await service.authenticate(token,('driver',));kind=message.get('type')
    if kind=='telemetry':accepted=service.telemetry(p,message['packet']);await ws.send_json({'type':'state','accepted':accepted,'state':service.public_state(p)})
    elif kind=='lap':await ws.send_json({'type':'lap_ack',**await service.lap_event(p,message['lap'])})
    elif kind=='response':await ws.send_json({'type':'response_ack',**await service.response(p,message['response'])})
    elif kind=='ping':await ws.send_json({'type':'pong','source':message.get('source'),'host_time':time.time(),'state':service.public_state(p)})
    elif kind=='clock':
     uncertainty=message.get('uncertainty_ms')
     if isinstance(uncertainty,(int,float)) and 0<=uncertainty<=60000:service.boots[p['subject']]={'uncertainty_ms':uncertainty,'offset_ms':message.get('offset_ms')}
    else:fail(422,'Unknown message')
  except Exception as error:
   try:await ws.send_json({'type':'error','message':str(getattr(error,'detail','Connection ended'))[:300]});await ws.close(code=1008)
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
 return [{'id':id,'name':v[0],'width':v[1],'height':v[2],'status':'implemented; OBS validation pending','data':'permitted group data','unavailable':'label unavailable or hide','slots':['primary','a','b'] if id in ('driver','telemetry','comparison') else []} for id,v in GRAPHICS.items()]
