"""Outbound forwarding of the existing normalized receiver; never opens a GT7 socket."""
import asyncio,json,time,random,urllib.request,urllib.error
from urllib.parse import urlparse
from .repository import uid
from .service import fields_for,fail
from ..engineer import Event

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def request(base,path,body=None,token=None):
 headers={'Content-Type':'application/json'}
 if token:headers['Authorization']='Bearer '+token
 req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect).open(req,timeout=8) as response:
   raw=response.read(2*1024*1024+1)
   if len(raw)>2*1024*1024:raise ValueError('Host response too large')
   return json.loads(raw)
 except urllib.error.HTTPError as error:
  try:detail=json.loads(error.read(4096)).get('detail','Join failed')
  except Exception:detail='Host request failed'
  raise ValueError(str(detail)) from error

def address(url):
 parsed=urlparse(url)
 if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):fail(422,'Enter a reachable http(s) host address and port without a path')
 return url.rstrip('/')

class MemberClient:
 def __init__(self,runtime,base,joined,rate=5):
  self.runtime=runtime;self.base=address(base);self.joined=joined;self.rate=max(1,min(10,int(rate)));self.boot=uid();self.sequence=0;self.running=False;self.task=None;self.state=None;self.error=None;self.status='joining';self.known=set();self.lap_acks=set();self.responses=asyncio.Queue(maxsize=64);self.first=True;self.last_ping=0;self.lap_epoch=None
 async def start(self):self.running=True;self.task=asyncio.create_task(self.loop())
 async def close(self):
  self.running=False
  if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
 def response(self,body):
  try:self.responses.put_nowait(body)
  except asyncio.QueueFull:fail(429,'Driver response queue full')
 async def consume(self,state,ws):
  self.state=state;now=state.get('timeline',time.time());mine=next((e for e in state.get('entries',[]) if e['entry_id']==self.joined['participant']['entry_id']),{})
  notices=[{**i,'text':i['flag'].replace('_',' ')+'. '+i['reason'],'priority':0 if i['flag'] in ('red','black','mechanical') else 1} for i in mine.get('flags',[])]+[m for m in state.get('messages',[]) if m.get('for_you')]
  for item in notices:
   key=state['session_id']+':'+item['id']
   if key in self.known:continue
   self.known.add(key)
   if not self.first and (item.get('expires') is None or item['expires']>now):
    self.runtime.scheduler.offer(Event('group:'+item['id'],item['text'],item['priority'],ttl=min(60,max(1,(item.get('expires') or now+15)-now)),evidence={'source':'host-entered','group_id':state['group_id']},session=None,requested=False))
   if 'acknowledgement' in item:
    await ws.send(json.dumps({'type':'response','response':{'action':'delivered','message_id':item['id']}}));await ws.recv()
  self.first=False
  if len(self.known)>2048:self.known=set(list(self.known)[-1024:])
 async def loop(self):
  from websockets.asyncio.client import connect
  backoff=1
  while self.running:
   try:
    me=await asyncio.to_thread(request,self.base,'/group-api/me',None,self.joined['token']);self.joined.update(me)
    if me['participant']['status']!='admitted':self.status=me['participant']['status'];await asyncio.sleep(2);continue
    url=self.base.replace('https://','wss://',1).replace('http://','ws://',1)+'/group-api/publish'
    async with connect(url,additional_headers={'Authorization':'Bearer '+self.joined['token']},max_size=2*1024*1024,compression=None,ping_interval=5,ping_timeout=10) as ws:
     hello=json.loads(await ws.recv());self.joined['session_id']=hello['session_id'];
     if self.lap_epoch!=hello['session_id']:
      self.lap_epoch=hello['session_id'];self.lap_acks={self.lap_epoch+':'+lap['id'] for lap in self.runtime.sessions.laps if lap['complete']}
     self.status='connected';self.error=None;backoff=1;self.first=True
     while self.running:
      start=time.monotonic()
      if start-self.last_ping>(5 if self.runtime.received_at and start-self.runtime.received_at<2 else 1/self.rate):
       sent=time.time();await ws.send(json.dumps({'type':'ping','source':sent}));pong=json.loads(await ws.recv());received=time.time();await ws.send(json.dumps({'type':'clock','uncertainty_ms':(received-sent)*500,'offset_ms':(pong['host_time']-(sent+received)/2)*1000}));self.last_ping=start
       if pong.get("state"):await self.consume(pong["state"],ws)
      sample=self.runtime.sample
      if sample and self.runtime.received_at and time.monotonic()-self.runtime.received_at<2:
       keys=fields_for(self.joined['participant']['sharing']);values={k:sample.values[k] for k in keys if k in sample.values}
       if 'strategy' in keys:values['strategy']={k:v for k,v in self.runtime.sessions.fuel().items() if k in ('laps_remaining','margin_l','litres_per_lap')}
       self.sequence+=1;packet={'version':1,'group_id':self.joined['group_id'],'session_id':self.joined['session_id'],'participant_id':self.joined['participant']['id'],'entry_id':self.joined['participant']['entry_id'],'boot_id':self.boot,'sequence':self.sequence,'source_mono':sample.mono,'source_utc':time.time()-(time.monotonic()-self.runtime.received_at),'provenance':sample.provenance,'layout_id':self.runtime.track_map.layout_id if self.runtime.track_map.bound else '','local_session_id':self.runtime.sessions.id or 'idle','values':values,'available':[k for k,v in values.items() if v is not None],'quality':sample.quality}
       await ws.send(json.dumps({'type':'telemetry','packet':packet}));response=json.loads(await asyncio.wait_for(ws.recv(),10))
       if response['type']=='error':raise ValueError(response['message'])
       if response['type']=='state':await self.consume(response['state'],ws)
      for lap in self.runtime.sessions.laps[-16:]:
       key=self.joined['session_id']+':'+lap['id']
       if key in self.lap_acks or not lap['complete']:continue
       await ws.send(json.dumps({'type':'lap','lap':{'id':lap['id'],'session_id':self.joined['session_id'],'duration_ms':lap['duration_ms'],'number':lap['number'],'comparable':lap['comparable'],'quality':lap['quality']}}));reply=json.loads(await ws.recv())
       if reply.get('ack')==lap['id']:self.lap_acks.add(key)
      while not self.responses.empty():
       item=self.responses.get_nowait()
       try:
        await ws.send(json.dumps({'type':'response','response':item}));reply=json.loads(await ws.recv())
        if reply.get('type')=='error':self.error=reply['message']
       except Exception:
        self.responses.put_nowait(item);raise
       finally:self.responses.task_done()
      await asyncio.sleep(max(.01,1/self.rate-(time.monotonic()-start)))
   except asyncio.CancelledError:raise
   except Exception as e:
    self.status='reconnecting';self.error=str(e)[:240];await asyncio.sleep(backoff+random.uniform(0,.5));backoff=min(30,backoff*2)
 def snapshot(self):return {'status':self.status,'error':self.error,'host':self.base,'rate_hz':self.rate,'identity':self.joined['participant']['identity'],'state':self.state}
