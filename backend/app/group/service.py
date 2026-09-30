import asyncio,time,json,copy,math,statistics
from collections import deque,defaultdict
from ..core.errors import AppError
from .principals import allowed as permitted_by
from .protocol import LegacyClientTracker
from .snapshots import SnapshotCache
from .migrations import ensure_team_ids
from .models import *
from .repository import GroupRepository,uid,encode
from .timing import Projection,TrackProgressAdapter,applicable_flags
from .history import DistanceHistory,common_timeline,interval,gap_uncertainty
from .pit import PitTracker,MAX_STOPS_PER_SESSION,learned_pit_loss,learned_refuel_rate
from .battles import BattleEngine,DEFAULT_WEIGHTS
from .steward import enqueue_steward_cue,active_cue
from .projection import project as project_stops,FuelBurnTracker
from ..cars import identify
from ..tracks import LAYOUTS
BASIC={'position','lap','last_ms','best_ms','flags','car_id'}
CATEGORIES={'basic':BASIC,'telemetry':{'speed_kmh','rpm','gear','throttle','brake','clutch','tyres','current_ms'},'fuel':{'fuel','fuel_capacity'},'strategy':{'strategy'}}
def fields_for(categories):return set().union(*(CATEGORIES.get(c,set()) for c in categories))
def fail(status,message):raise AppError.from_status(status,message)
def clone(x):return copy.deepcopy(x)
class GroupService:
 def __init__(self,runtime):
  self.runtime=runtime;self.repo=GroupRepository(runtime.store.path);self.lock=asyncio.Lock();self.asset_lock=asyncio.Lock()
  self.groups={g['id']:g for g in self.repo.docs('group')};self.leagues={l['id']:l for l in self.repo.docs('league')};self.workspaces={w['id']:w for w in self.repo.docs('workspace')}
  self.live={};self.retired_streams=defaultdict(set);self.projectors={};self.history=deque(maxlen=650);self.history_bytes=0;self.boots={};self.connections={};self.tickets={};self.rate=defaultdict(deque)
  self.histories={};self.pit=PitTracker();self.pending_pit_stops=[]
  self.battle_tasks={};self.battles={};self.battle_engines={};self.desk_alerts={}
  self.fuel_burn=FuelBurnTracker();self.projections={};self.projection_tasks={}
  self.demo=None;self.running=False;self.task=None;self.listener=None;self.listener_task=None;self.recording_drops=0;self.recording_error=None;self.frame_queue=asyncio.Queue(maxsize=32);self.writer_task=None;self.replay=None;self.client=None;self._snapshot_cache=None
  self.revision=0;self.snapshots=SnapshotCache();self.legacy_clients=LegacyClientTracker()
  for g in self.groups.values():
   if g.get('state')=='running':g['state']='interrupted'
   if g.get('map_source')=='v3' and g.get('layout_id'):
    from ..track_catalogue import bundled_document
    from ..track_model import TrackProgress
    v3=bundled_document(g['layout_id'])
    if v3:self.projectors[g['id']]=TrackProgressAdapter(TrackProgress(v3))
   elif g.get('map'):
    try:self.projectors[g['id']]=Projection(g['map'])
    except ValueError:pass
 def active(self):return next((g for g in self.groups.values() if not g.get('closed')),None)
 def group(self,id=None):
  g=self.groups.get(id) if id else self.active()
  if not g:fail(404,'Group not found')
  return g
 async def commit_group(self,g,kind,body,actor='host',documents=()):
  seq=await asyncio.to_thread(self.repo.commit,[('group',g['id'],'',g),*documents],(g['id'],g['session_id'],actor,kind,body));self.groups[g['id']]=g;self._snapshot_cache=None;self.revision+=1;self.snapshots.clear();return seq
 def limit(self,key,maximum=30,period=10):
  now=time.monotonic();q=self.rate[key]
  while q and now-q[0]>period:q.popleft()
  if len(q)>=maximum:fail(429,'Rate limit reached')
  q.append(now)
  if len(self.rate)>4096:
   for k in list(self.rate):
    if not self.rate[k] or now-self.rate[k][-1]>120:self.rate.pop(k,None)
 def member(self,principal):
  g=self.group(principal['group_id']);p=g['participants'].get(principal['subject'])
  if not p or p['status']=='removed':fail(403,'Participant removed')
  return g,p
 async def authenticate(self,token,kinds=('driver','spectator','overlay')):
  principal=await asyncio.to_thread(self.repo.auth,token,kinds)
  if not principal:fail(401,'Credential expired or revoked')
  if principal['kind'] in ('driver','spectator'):self.member(principal)
  return principal
 def check_assets(self,branding,league):
  refs=list(branding.get('logos',{}).values())+[s.get('asset','') for s in branding.get('sponsors',[])]+[t.get('asset','') for t in branding.get('teams',[])]
  for id in filter(None,refs):
   asset=self.repo.get('asset',id)
   if not asset or asset['league_id']!=league:fail(422,'Logo does not belong to league')
  for row in branding.get('sponsors',[])+branding.get('teams',[]):
   if set(row)-{'id','team_id','name','asset','enabled','slot','color'} or len(encode(row))>1000:fail(422,'Unsupported sponsor/team settings')
 async def league_save(self,body,id=None):
  b=Branding.model_validate(body).model_dump();id=id or uid();ensure_team_ids(b['teams'],id)
  async with self.lock:
   item={'id':id,'revision':self.leagues.get(id,{}).get('revision',0)+1,'branding':b};self.check_assets(b,id)
   await asyncio.to_thread(self.repo.commit,[('league',id,'',item),('league_revision',uid(),id,item)]);self.leagues[id]=item
  return item
 def brand_override(self,body,league):
  if not isinstance(body,dict) or set(body)-set(Branding.model_fields):fail(422,'Unsupported branding override')
  valid=Branding.model_validate({**self.leagues[league]['branding'],**body}).model_dump();ensure_team_ids(valid['teams'],league);self.check_assets(valid,league);return {k:valid[k] for k in body}
 async def create_group(self,body):
  config=GroupConfig.model_validate(body).model_dump()
  async with self.lock:
   if self.active():fail(409,'Close current group first')
   league=self.leagues.get(config['league_id'])
   if not league:fail(422,'Create a league first')
   if config['layout_id'] and config['layout_id'] not in LAYOUTS:fail(422,'Unknown layout')
   config['branding']=self.brand_override(config['branding'],config['league_id'])
   g={**config,'id':uid(),'event_id':uid(),'session_id':uid(),'state':'draft','closed':False,'created':time.time(),'started':None,'ended':None,'policy_revision':1,'participants':{},'entries':{},'instructions':[],'messages':[],'decisions':[],'zones':[],'map':None,'map_revision':None,'branding_snapshot':clone(league),'final_results':None,'results_revision':0,'pit_stops':[],'steward_cues':[],'cued':[]}
   await self.commit_group(g,'group_created',config);return g
 async def invite(self,role,expires=3600):
  if role not in ('driver','spectator'):fail(422,'Invalid invitation role')
  g=self.group();id=uid();expires=max(60,min(int(expires),86400));token=await asyncio.to_thread(self.repo.token,'invite_'+role,id,g['id'],expires)
  await asyncio.to_thread(self.repo.commit,[('invitation',id,g['id'],{'id':id,'role':role,'expires':time.time()+expires})],(g['id'],g['session_id'],'host','invitation_created',{'id':id,'role':role}));return {'id':id,'credential':token,'expires_in':expires,'role':role}
 async def join(self,body):
  join=Join.model_validate(body);credential=await self.authenticate(join.credential,('invite_driver','invite_spectator'))
  async with self.lock:
   g=clone(self.group(credential['group_id']))
   if g['closed'] or g['join_locked']:fail(403,'Joining locked')
   role=credential['kind'].removeprefix('invite_')
   if role=='driver' and not set(g['required_sharing'])<=set(join.accepted_sharing):fail(409,{'message':'Accept event sharing policy','required_sharing':g['required_sharing'],'policy_revision':g['policy_revision']})
   count=sum(p['role']==role and p['status']!='removed' for p in g['participants'].values())
   if count>=(g['capacity'] if role=='driver' else 32):fail(409,'Group full')
   id=uid();entry=uid() if role=='driver' else None;identity=join.identity.model_dump();identity['driver_id']=identity['driver_id'] or uid()
   p={'id':id,'role':role,'identity':identity,'entry_id':entry,'status':'pending' if g['approval'] else 'admitted','sharing':join.accepted_sharing if role=='driver' else [],'policy_revision':g['policy_revision']};g['participants'][id]=p
   if entry:g['entries'][entry]={'id':entry,'participant_id':id,'identity':identity,'baseline':None,'baseline_source':None,'joined':time.time(),'grid':None,'notes':''}
   await self.commit_group(g,'participant_joined',{'participant_id':id,'entry_id':entry,'status':p['status']},id)
   token=await asyncio.to_thread(self.repo.token,role,id,g['id'],7*86400)
   return {'token':token,'participant':p,'group_id':g['id'],'session_id':g['session_id'],'required_sharing':g['required_sharing'],'policy_revision':g['policy_revision'],'provenance':g['provenance']}
 async def admit(self,id,status):
  if status not in ('admitted','removed'):fail(422,'Invalid admission state')
  async with self.lock:
   g=clone(self.group());p=g['participants'].get(id)
   if not p:fail(404,'Participant not found')
   p['status']=status;await self.commit_group(g,'admission_changed',{'participant_id':id,'status':status})
   if status=='removed':
    await asyncio.to_thread(self.repo.revoke,id)
    if id in self.connections:await self.connections[id].close(code=1008)
   return p
 async def configure(self,body):
  async with self.lock:
   g=clone(self.group());config=GroupConfig.model_validate({**{k:g[k] for k in GroupConfig.model_fields},**body}).model_dump()
   if config['league_id']!=g['league_id']:fail(409,'Create another event to switch leagues')
   if g['state']=='running' and any(config[k]!=g[k] for k in ('layout_id','format','provenance')):fail(409,'Session geometry and format are frozen')
   if not set(config['required_sharing'])<=set(g['required_sharing']):g['policy_revision']+=1
   config['branding']=self.brand_override(config['branding'],g['league_id']);g.update(config);await self.commit_group(g,'configuration_changed',config);return g
 async def consent(self,principal,categories):
  async with self.lock:
   original,p=self.member(principal);g=clone(original)
   if not set(g['required_sharing'])<=set(categories) or set(categories)-set(CATEGORIES):fail(422,'Required categories not accepted')
   p=g['participants'][p['id']];p['sharing']=categories;p['policy_revision']=g['policy_revision'];await self.commit_group(g,'sharing_accepted',{'categories':categories},p['id']);return p
 async def session_action(self,action):
  if action=='start':await self.sync_track_library(starting=True)
  async with self.lock:
   g=clone(self.group())
   if action=='start':
    if g['state']=='running':fail(409,'Session already running')
    g.update(session_id=uid(),state='running',started=time.time(),ended=None,instructions=[],messages=[],decisions=[],pit_stops=[],steward_cues=[],cued=[],final_results=None,results_revision=0,branding_snapshot=clone(self.leagues[g['league_id']]))
    for entry in g['entries'].values():
     sample=self.live.get(entry['id']);entry['baseline']=sample['values'].get('lap') if sample and time.time()-sample['received']<2 else None;entry['baseline_source']='start snapshot' if entry['baseline'] is not None else None
    self.history.clear();self.history_bytes=0;self.replay=None;self.histories.clear();self.pit=PitTracker();self.pending_pit_stops=[]
   elif action in ('end','close'):g['state']='completed';g['ended']=time.time();g['closed']=action=='close'
   elif action=='finalize':
    if g['state'] not in ('completed','interrupted'):fail(409,'End session before finalizing')
    g['final_results']=self.classification(g,time.time());g['results_revision']+=1
   else:fail(422,'Unknown session action')
   await self.commit_group(g,'session_'+action,{'session_id':g['session_id'],'results_revision':g['results_revision']},documents=[('group_session',g['session_id'],g['id'],g)])
  if action=='start':
   old=self.battle_tasks.pop(g['id'],None)
   if old:old.cancel()
   self.battles[g['id']]=[];self.desk_alerts[g['id']]=deque(maxlen=32);self.battle_engines[g['id']]=BattleEngine()
   self.battle_tasks[g['id']]=asyncio.create_task(self.battle_loop(g['id']))
   old_projection=self.projection_tasks.pop(g['id'],None)
   if old_projection:old_projection.cancel()
   self.projections[g['id']]=None;self.fuel_burn=FuelBurnTracker()
   self.projection_tasks[g['id']]=asyncio.create_task(self.projection_loop(g['id']))
  elif action in ('end','close'):
   task=self.battle_tasks.pop(g['id'],None)
   if task:task.cancel()
   task=self.projection_tasks.pop(g['id'],None)
   if task:task.cancel()
  return g
 async def set_map(self,points,zones):
  try:projector=Projection(points)
  except (ValueError,TypeError):fail(422,'Invalid continuous track map')
  validated=[Zone.model_validate(z).model_dump() for z in zones]
  if len(validated)>32:fail(422,'At most 32 control zones')
  async with self.lock:
   g=clone(self.group())
   if g['state']=='running':fail(409,'Map and zones are frozen while running')
   g['map']=points;g['map_model']=None;g['pending_map']=None;g['map_source']='manual';g['map_revision']=projector.revision;g['zones']=[{**z,'id':uid()} for z in validated];await self.commit_group(g,'map_changed',{'revision':projector.revision,'zones':g['zones']});self.projectors[g['id']]=projector
   return {'revision':projector.revision,'zones':g['zones']}
 async def sync_track_library(self,adopt=False,starting=False):
  original=self.active()
  if not original or not original['layout_id'] or original.get('demo_league'):return
  if original.get('map_source')=='manual' and not adopt and not original.get('pending_map'):return
  key=original['layout_id']
  from ..track_catalogue import bundled_document
  from ..track_model import TrackProgress
  v3=bundled_document(key)
  if v3:
   if original['state']=='running' or (original.get('map_source')=='v3' and original.get('map_revision')==v3['revision']):return
   async with self.lock:
    g=clone(self.group())
    if g['id']!=original['id'] or g['layout_id']!=key or g['state']=='running':return
    if g.get('map_source')=='v3' and g.get('map_revision')==v3['revision']:return
    old_revision=g.get('map_revision');g['map_model']=None;g['map_source']='v3';g['map_revision']=v3['revision'];g['map']=None;g['pending_map']=None
    if old_revision!=v3['revision']:g['zones']=[]
    await self.commit_group(g,'v3_map_loaded',{'revision':v3['revision']})
   self.projectors[g['id']]=TrackProgressAdapter(TrackProgress(v3));return
  tracker=getattr(self.runtime,'track_map',None)
  if not tracker:return
  await asyncio.to_thread(tracker.alignment,key);model=tracker.map_for(key)
  if not model['points'] and not model['reference']:return
  async with self.lock:
   g=clone(self.group())
   if g['id']!=original['id'] or g['layout_id']!=key:return
   current=g.get('map_model')
   if current and current['revision']==model['revision'] and current.get('reference')==model.get('reference'):return
   if g['state']=='running' or (g['state'] in ('completed','interrupted') and not starting):
    if g.get('pending_map')==model:return
    g['pending_map']=model;await self.commit_group(g,'map_revision_queued',{'revision':model['revision']});return
   old_revision=g.get('map_revision');g['map_model']=model;g['map_source']='library';g['pending_map']=None
   if model['complete']:
    projector=Projection(model['points']);g['map']=model['points'];g['map_revision']=model['revision']
   else:projector=None;g['map']=None;g['map_revision']=None
   # Zones refer to a particular map; changing geometry requires new zone approval.
   if old_revision!=model['revision']:g['zones']=[]
   await self.commit_group(g,'library_map_loaded',{'revision':model['revision']})
   if projector:self.projectors[g['id']]=projector
   else:self.projectors.pop(g['id'],None)
 def telemetry(self,principal,body):
  packet=Packet.model_validate(body);g,p=self.member(principal)
  if not permitted_by(principal,'telemetry.publishOwn',member=p,group=g):fail(403,'Admitted driver credential required')
  if p['policy_revision']!=g['policy_revision']:fail(409,'Sharing policy changed; renew consent')
  if packet.group_id!=g['id'] or packet.session_id!=g['session_id'] or packet.participant_id!=p['id'] or packet.entry_id!=p['entry_id']:fail(403,'Identity or session mismatch')
  if g['entries'][p['entry_id']]['participant_id']!=p['id']:fail(403,'Publishing lease reassigned')
  if packet.provenance!=g['provenance']:fail(409,'Live and synthetic sources cannot mix')
  self.limit(('telemetry',p['id']),120,10);old=self.live.get(p['entry_id']);stream=(packet.boot_id,packet.local_session_id,g['session_id'])
  retired=self.retired_streams[p['entry_id']]
  if stream in retired:fail(409,'Retired publisher stream')
  if old and old['stream']!=stream:
   if old['stream'][2]!=g['session_id']:retired.clear()
   elif len(retired)>=64:fail(409,'Too many publisher changes; start a new session')
   else:retired.add(old['stream'])
  if old and old['stream']==stream and packet.sequence<=old['sequence']:return False
  values={k:v for k,v in packet.values.items() if k in fields_for(p['sharing'])};now=time.time();progress=None;projector=self.projectors.get(g['id']);compatible=packet.layout_id==g['layout_id'] and bool(g['layout_id'])
  if projector and compatible and values.get('flags',0)&1 and not values.get('flags',0)&6 and not packet.quality:progress=projector.project(values.get('position'),old.get('progress') if old and old['stream']==stream and now-old['received']<2 else None)
  reset=bool(old and (old['stream'][:2]!=stream[:2] or (values.get('lap') is not None and old['values'].get('lap') is not None and values['lap']<old['values']['lap'])))
  self.live[p['entry_id']]={'values':values,'sequence':packet.sequence,'source_mono':packet.source_mono,'source_utc':packet.source_utc,'received':now,'stream':stream,'provenance':packet.provenance,'quality':packet.quality,'available':packet.available,'progress':progress,'layout_compatible':compatible,'counter_reset':reset or bool(old and old.get('counter_reset')),'clock_uncertainty_ms':self.boots.get(p['id'],{}).get('uncertainty_ms'),'completed_laps':old.get('completed_laps',[]) if old and old['stream']==stream else []}
  if compatible and values.get('flags',0)&1 and not values.get('flags',0)&6 and not packet.quality:
   from ..track_catalogue import bundled_document
   length=projector.length if projector else None;s=progress*length if progress is not None and length else None
   document=bundled_document(g['layout_id']) if g['layout_id'] else None
   T,_=common_timeline(packet.source_utc,now,self.boots.get(p['id'],{}).get('offset_ms'))
   stop=self.pit.consume(p['entry_id'],T,position=values.get('position'),speed_kmh=values.get('speed_kmh'),s=s,length=length,lap=values.get('lap'),fuel=values.get('fuel'),pit_points=(document or {}).get('pit',{}).get('points'),corners=(document or {}).get('corners'))
   if stop and stop['entry_id'] in g['entries']:self.pending_pit_stops.append((g['id'],stop))
  if values.get('fuel') is not None:self.fuel_burn.observe(p['entry_id'],values.get('lap'),values['fuel'])
  return True
 async def lap_event(self,principal,body):
  g,p=self.member(principal)
  if not permitted_by(principal,'telemetry.publishOwn',member=p,group=g):fail(403,'Driver required')
  if body.get('session_id')!=g['session_id']:fail(409,'Old session event')
  if p['policy_revision']!=g['policy_revision']:fail(409,'Sharing consent must be renewed')
  if g['entries'][p['entry_id']]['participant_id']!=p['id']:fail(403,'Publishing lease reassigned')
  if not isinstance(body.get('quality',[]),list) or any(not isinstance(q,str) or len(q)>160 for q in body.get('quality',[])):fail(422,'Invalid lap quality')
  id=body.get('id');duration=body.get('duration_ms')
  if not isinstance(id,str) or not id or len(id)>100 or not isinstance(duration,(int,float)) or not math.isfinite(duration) or not 1000<duration<86400000:fail(422,'Invalid completed lap')
  event={'id':id,'entry_id':p['entry_id'],'duration_ms':duration,'comparable':body.get('comparable') is True,'number':body.get('number'),'quality':body.get('quality',[])[:32]}
  async with self.lock:
   if self.repo.get('lap_event',p['id']+':'+id):return {'ack':id}
   await asyncio.to_thread(self.repo.commit,[('lap_event',p['id']+':'+id,g['session_id'],event)],(g['id'],g['session_id'],p['id'],'completed_lap',event))
   if p['entry_id'] in self.live:self.live[p['entry_id']]['completed_laps']=(self.live[p['entry_id']]['completed_laps']+[event])[-2000:]
  return {'ack':id}
 async def entry_update(self,id,body):
  async with self.lock:
   g=clone(self.group());entry=g['entries'].get(id)
   if not entry:fail(404,'Entry not found')
   if set(body)-{'identity','baseline','grid','notes','participant_id'}:fail(422,'Unknown entry property')
   if 'identity' in body:entry['identity']=Identity.model_validate(body['identity']).model_dump()
   for field in ('baseline','grid'):
    if field in body:
     value=body[field]
     if value is not None and (not isinstance(value,int) or not 0<=value<=100000):fail(422,'Invalid lap/grid value')
     entry[field]=value
   if 'baseline' in body:
    entry['baseline_source']='host correction'
   if 'notes' in body:entry['notes']=str(body['notes'])[:2000]
   if 'participant_id' in body:
    p=g['participants'].get(body['participant_id'])
    if not p or p['role']!='driver' or p['status']!='admitted':fail(422,'Choose an admitted driver')
    old=entry['participant_id'];entry['participant_id']=p['id'];p['entry_id']=id
    # Clear the outgoing driver's own entry_id so a still-valid credential of
    # theirs can no longer match this entry as "own" in filter_snapshot() once
    # it's been reassigned - a stale match would leak the new driver's own
    # sharing-consent fields (broader than the group publication) to them.
    if old!=p['id'] and old in g['participants']:g['participants'][old]['entry_id']=None
   await self.commit_group(g,'entry_corrected',{'entry_id':id,'changes':body})
   if 'baseline' in body and id in self.live:self.live[id]['counter_reset']=False
   if 'participant_id' in body and old in self.connections:await self.connections[old].close(code=1008)
   return entry
 async def instruction(self,body):
  item=Instruction.model_validate(body).model_dump()
  async with self.lock:
   g=clone(self.group())
   if len(g['instructions'])>=256:fail(409,'Instruction limit reached')
   if item['scope']=='entry' and item['target'] not in g['entries']:fail(422,'Unknown entry')
   if item['scope']=='zone' and item['target'] not in {z['id'] for z in g['zones']}:fail(422,'Unknown control zone')
   if item['flag'] in ('safety_car','fcy','vsc'):
    if item['scope']!='global':fail(422,'Safety-car modes must be global')
    for previous in g['instructions']:
     if previous['flag'] in ('safety_car','fcy','vsc'):previous['cancelled']=True
   item.update(id=uid(),issuer='host',effective=time.time(),expires=time.time()+item['expires_in'] if item['expires_in'] else None,cancelled=False,version=len(g['instructions'])+1)
   g['instructions'].append(item);await self.commit_group(g,'instruction_issued',item);return item
 async def cancel_instruction(self,id):
  async with self.lock:
   g=clone(self.group());item=next((i for i in g['instructions'] if i['id']==id),None)
   if not item:fail(404,'Instruction not found')
   item['cancelled']=True;await self.commit_group(g,'instruction_cancelled',{'id':id});return item
 async def message(self,body):
  item=Message.model_validate(body).model_dump()
  async with self.lock:
   g=clone(self.group())
   if len(g['messages'])>=256:fail(409,'Message limit reached')
   targets=[e['id'] for e in g['entries'].values() if item['scope']=='all' or item['scope']=='entry' and e['id']==item['target'] or item['scope'] in ('team','class') and e['identity']['team' if item['scope']=='team' else 'class_name']==item['target']]
   if not targets:fail(422,'No matching entries')
   item.update(id=uid(),issuer='host',effective=time.time(),expires=time.time()+item['expires_in'],targets=targets,receipts={});g['messages'].append(item);await self.commit_group(g,'message_issued',item);return item
 async def response(self,principal,body):
  async with self.lock:
   original,p=self.member(principal);g=clone(original)
   if not permitted_by(principal,'driver.respond',member=p,group=g):fail(403,'Admitted driver required')
   action=body.get('action')
   if action in ('delivered','displayed','acknowledged'):
    message=next((m for m in g['messages'] if m['id']==body.get('message_id')),None)
    if not message or p['entry_id'] not in message['targets']:fail(404,'Message not found')
    if message['expires']<time.time():fail(409,'Message expired')
    receipt=message['receipts'].setdefault(p['entry_id'],{})
    if action in receipt:return receipt
    receipt[action]=time.time()
   elif action not in ('pit_intent','staying_out','assistance','incident'):fail(422,'Unknown driver response')
   await self.commit_group(g,'driver_response',{'entry_id':p['entry_id'],'action':action,'message_id':body.get('message_id')},p['id']);return {'ok':True}
 async def decision(self,body):
  item=Decision.model_validate(body).model_dump()
  async with self.lock:
   g=clone(self.group())
   if item['entry_id'] not in g['entries']:fail(422,'Unknown entry')
   if len(g['decisions'])>=1000:fail(409,'Decision limit reached')
   if item['supersedes'] and not any(d['id']==item['supersedes'] for d in g['decisions']):fail(422,'Unknown superseded decision')
   item.update(id=uid(),issuer='host',utc=time.time());g['decisions'].append(item)
   if g['final_results'] is not None:g['final_results']=None
   if not g.get('auto_steward_paused') and self.flag('steward_auto_cues'):
    cued={tuple(x) for x in g.get('cued') or []};cues=g.get('steward_cues') or []
    enqueue_steward_cue(cues,item,g['entries'][item['entry_id']]['identity'],set(g.get('steward_popup_kinds') or []),cued,time.time())
    g['steward_cues']=cues;g['cued']=[list(x) for x in cued]
   await self.commit_group(g,'steward_decision',item);return item
 async def cancel_steward_cue(self,id):
  async with self.lock:
   g=clone(self.group());cues=g.get('steward_cues') or []
   if not any(c['id']==id for c in cues):fail(404,'Cue not found')
   g['steward_cues']=[c for c in cues if c['id']!=id]
   await self.commit_group(g,'steward_cue_cancelled',{'id':id});return g['steward_cues']
 async def set_steward_paused(self,paused):
  async with self.lock:
   g=clone(self.group());g['auto_steward_paused']=bool(paused)
   await self.commit_group(g,'steward_paused_set',{'paused':g['auto_steward_paused']});return {'paused':g['auto_steward_paused']}
 def classification(self,g,now):
  rows=[];superseded={d['supersedes'] for d in g['decisions'] if d['supersedes']}
  projector=self.projectors.get(g['id']);length=projector.length if projector else None
  for e in g['entries'].values():
   p=g['participants'].get(e['participant_id'])
   if not p or p['status']!='admitted' or p['entry_id']!=e['id']:continue
   sample=self.live.get(e['id'],{});v=sample.get('values',{});stale=now-sample.get('received',0)>2;laps=sample.get('completed_laps',[]);best=min((l['duration_ms'] for l in laps if l['comparable']),default=None)
   comparable_ms=[l['duration_ms'] for l in laps if l['comparable']];median_lap_ms=statistics.median(comparable_ms) if comparable_ms else None
   base=e['baseline'];completed=max(0,v['lap']-base) if base is not None and v.get('lap') is not None and not sample.get('counter_reset') else None
   penalties=[d for d in g['decisions'] if d['entry_id']==e['id'] and d['id'] not in superseded and d['status']!='withdrawn'];penalty_laps=sum(int(d['value']) for d in penalties if d['kind']=='laps');penalty_ms=sum(d['value']*1000 for d in penalties if d['kind']=='time')
   elapsed=sum(l['duration_ms'] for l in laps) if laps and all(l['comparable'] for l in laps) else None;order=next((int(d['value']) for d in reversed(penalties) if d['kind']=='order'),None)
   # D (race distance, metres): completed_laps*L+s. Only trusted while not stale,
   # on-layout, unreset and progress-bearing; a >150m backward s jump on the same
   # lap (no genuine lap boundary) is treated as a bad projection, not real motion.
   D=None;history=self.histories.setdefault(e['id'],DistanceHistory())
   if not stale and sample.get('layout_compatible') and sample.get('progress') is not None and not sample.get('counter_reset') and completed is not None and length:
    s_m=sample['progress']*length
    if history.last_completed_laps==completed and history.d:
     if s_m-(history.d[-1]-completed*length)<-150:s_m=None
    if s_m is not None:
     D=completed*length+s_m;boot=self.boots.get(p['id']) or {}
     T,_extra=common_timeline(sample.get('source_utc'),sample.get('received'),boot.get('offset_ms'))
     history.add(T,D);history.last_completed_laps=completed
   rows.append({'entry_id':e['id'],'identity':e['identity'],'car':identify(v.get('car_id')),'car_id':v.get('car_id'),'stale':stale,'received':sample.get('received'),'last_ms':v.get('last_ms'),'best_ms':best,'reported_best_ms':v.get('best_ms'),'completed_laps':completed,'progress':None if stale else sample.get('progress'),'D':D,'median_lap_ms':median_lap_ms,'in_pit':self.pit.is_in_pit(e['id']),'clock_uncertainty_ms':sample.get('clock_uncertainty_ms'),'quality':sample.get('quality',[]),'adjusted_laps':max(0,completed-penalty_laps) if completed is not None else None,'penalty_ms':penalty_ms,'adjusted_elapsed_ms':elapsed+penalty_ms if elapsed is not None else None,'disqualified':any(d['kind']=='disqualification' for d in penalties),'manual_order':order,'position':None,'gap_s':None,'lap_separation':None,'classification_source':'host correction' if order is not None else 'derived estimate','baseline_source':e['baseline_source']})
  if g['format'] in ('practice','qualifying'):rows.sort(key=lambda r:(r['disqualified'],r['best_ms'] is None,r['best_ms'] or math.inf,r['entry_id']))
  else:rows.sort(key=lambda r:(r['disqualified'],r['manual_order'] is None,r['manual_order'] or math.inf,r['adjusted_laps'] is None,-(r['adjusted_laps'] or 0),r['adjusted_elapsed_ms'] if g['state']!='running' and r['adjusted_elapsed_ms'] is not None else -(r['progress'] or 0),r['entry_id']))
  for i,r in enumerate(rows):
   usable=r['best_ms'] is not None if g['format'] in ('practice','qualifying') else r['completed_laps'] is not None and not r['stale'] and r['progress'] is not None
   if r['manual_order'] is not None:usable=True
   if usable and not r['disqualified']:r['position']=i+1
   if rows and r['completed_laps'] is not None and rows[0]['completed_laps'] is not None:r['lap_separation']=rows[0]['completed_laps']-r['completed_laps']
  return rows
 @staticmethod
 def _alert_text(a,identities):
  ia=identities.get(a['ahead'],{});ib=identities.get(a['behind'],{})
  gap='gap unknown' if a.get('gap_s') is None else f"{a['gap_s']:.1f}s"
  closing='' if a.get('closing_per_lap_s') is None else f", closing {abs(a['closing_per_lap_s']):.1f}s/lap"
  return f"P{a['position']} battle: #{ia.get('number') or '?'} {ia.get('display_name') or '?'} vs #{ib.get('number') or '?'} {ib.get('display_name') or '?'} — {gap}{closing}"
 def flag(self,flag_id):
  """Feature flag state from the host runtime (True when the runtime has no settings, e.g. in unit tests)."""
  from ..core.features import is_enabled
  settings=getattr(self.runtime,'settings',None)
  if settings is None:return True
  return is_enabled(flag_id,settings,safe_mode=getattr(self.runtime,'safe_mode',None) is not None)
 async def battle_loop(self,group_id):
  """2Hz per docs/AI_CONTEXT.md 3.1: computed from RAW classification so the
  broadcast delay applies on top of battles exactly like every other frame."""
  engine=self.battle_engines.setdefault(group_id,BattleEngine())
  while self.running:
   g=self.groups.get(group_id)
   if not g or g.get('closed') or g['state']!='running':break
   if not self.flag('battle_index'):self.battles[group_id]=[];await asyncio.sleep(1);continue
   now=time.time()
   rows=[r for r in self.classification(g,now) if r['D'] is not None and not r['stale'] and not r['in_pit']]
   rows.sort(key=lambda r:-r['D'])
   projector=self.projectors.get(group_id);length=projector.length if projector else None
   weights={**DEFAULT_WEIGHTS,**(g.get('battle_weights') or {})}
   try:
    battles,alerts=engine.tick(now,rows,self.histories,length,weights=weights,include_lapping=bool(g.get('battles_include_lapping')))
   except Exception:
    battles,alerts=[],[]
   self.battles[group_id]=battles
   if alerts:
    deck=self.desk_alerts.setdefault(group_id,deque(maxlen=32));identities={e['id']:e['identity'] for e in g['entries'].values()}
    for a in alerts:deck.append({**a,'text':self._alert_text(a,identities),'created':now})
   await asyncio.sleep(.5)
 def _compute_projection(self,g,now):
  """docs/AI_CONTEXT.md 5: net order and pit windows after everyone's remaining
  stops. None outside race formats (practice/qualifying/manual have no notion
  of 'laps remaining' to project against)."""
  if g['format'] not in ('laps','timed'):return None
  rows=self.classification(g,now);leader=next((r for r in rows if r['position']==1),None)
  leader_history=self.histories.get(leader['entry_id']) if leader else None
  leader_median_s=(leader.get('median_lap_ms') or 0)/1000 if leader and leader.get('median_lap_ms') else None
  laps_total=g['laps']
  if g['format']=='timed':
   elapsed=now-g['started'] if g['started'] else None
   laps_total=math.ceil((g['duration_s']-elapsed)/leader_median_s) if elapsed is not None and leader_median_s and g['duration_s'] else None
  entries=[]
  for r in rows:
   if r['stale'] or r['in_pit']:continue
   entry_id=r['entry_id'];v=self.live.get(entry_id,{}).get('values',{})
   fuel_l=v.get('fuel');capacity_l=v.get('fuel_capacity');strategy=v.get('strategy') or {}
   burn=strategy.get('litres_per_lap');source='reported' if burn else None
   if burn is None:
    burn=self.fuel_burn.burn_l_per_lap(entry_id)
    if burn is not None:source='host-calculated'
   if leader and entry_id==leader['entry_id']:gap_to_leader=0.0
   elif leader_history and r['D'] is not None:gap_to_leader=interval(leader_history,now,r['D'])
   else:gap_to_leader=None
   gap_unc=gap_uncertainty(leader.get('clock_uncertainty_ms') if leader else None,r.get('clock_uncertainty_ms'))
   laps_left=(laps_total-r['completed_laps']-(r['progress'] or 0)) if laps_total is not None and r['completed_laps'] is not None else None
   entries.append({'entry_id':entry_id,'position':r['position'],'gap_to_leader_s':gap_to_leader,'gap_uncertainty_s':gap_unc,'fuel_l':fuel_l,'capacity_l':capacity_l,'burn_l_per_lap':burn,'burn_source':source,'laps_left':laps_left,'current_lap':r['completed_laps'],'laps_total':laps_total})
  pit_loss=(g['pit_loss_s'],'host') if g.get('pit_loss_s') else None
  laps_by_entry={eid:self.live.get(eid,{}).get('completed_laps',[]) for eid in g['entries']}
  if pit_loss is None:
   learned=learned_pit_loss(g.get('pit_stops') or [],laps_by_entry)
   if learned:pit_loss=(learned['seconds'],'learned')
  refuel_rate=(g['refuel_rate_lps'],'host') if g.get('refuel_rate_lps') else None
  if refuel_rate is None:
   learned_r=learned_refuel_rate(g.get('pit_stops') or [])
   if learned_r:refuel_rate=(learned_r['litres_per_second'],'learned')
  result=project_stops(entries,pit_loss=pit_loss,refuel_rate=refuel_rate,race_format=g['format'])
  shared=sum(1 for e in entries if e['fuel_l'] is not None)
  return {'result':result,'pit_loss':pit_loss,'refuel_rate':refuel_rate,'coverage':{'sharing':shared,'total':len(g['entries'])}}
 async def projection_loop(self,group_id):
  while self.running:
   g=self.groups.get(group_id)
   if not g or g.get('closed') or g['state']!='running':break
   if not self.flag('net_order_projection'):self.projections[group_id]=None;await asyncio.sleep(.5);continue
   try:self.projections[group_id]=self._compute_projection(g,time.time())
   except Exception:self.projections[group_id]=None
   await asyncio.sleep(.5)
 def _public_projection(self,g):
  """No raw fuel litres, ever - just rank/stops/net-gap/window - and only when
  the group publishes both fuel and strategy (otherwise host-only via the
  dedicated /api/group/projection admin route, which always sees the full thing)."""
  proj=self.projections.get(g['id'])
  if not proj or not proj.get('result') or not {'fuel','strategy'}<=set(g['publication']):return None
  entries=[{'entry_id':e['entry_id'],'position':e.get('position'),'projected_rank':e.get('projected_rank'),'stops':e['stops'],'net_gap_s':e['net_gap_s'],'close_call':e.get('close_call',False),'window':e.get('window'),'change':e.get('change'),'status':e['status']} for e in proj['result']['entries']]
  return {'entries':entries,'summary':proj['result']['summary'],'pit_loss_source':proj['pit_loss'][1] if proj['pit_loss'] else None,'pit_loss_s':proj['pit_loss'][0] if proj['pit_loss'] else None,'coverage':proj['coverage']}
 def raw_snapshot(self,g=None):
  g=g or self.group();now=time.time()
  # Every concurrent viewer/overlay connection calls this independently roughly every
  # 200ms; recomputing classification+fields per connection is the dominant cost under
  # many simultaneous OBS/browser subscribers. A short cache collapses concurrent calls
  # within one tick into a single computation without user-visible staleness.
  cached=self._snapshot_cache
  if cached and cached[0]==g['id'] and cached[1]==g['session_id'] and now-cached[2]<.15:return cached[3]
  entries=[]
  for row in self.classification(g,now):
   sample=self.live.get(row['entry_id'],{});values=sample.get('values',{});fields={}
   for k,v in values.items():fields[k]={'value':None if row['stale'] else v,'source':'derived' if k=='strategy' else 'reported','available':v is not None and not row['stale'],'source_time':sample.get('source_utc'),'received_time':sample.get('received'),'confidence':'participant supplied' if k!='strategy' else 'participant estimate'}
   entries.append({**row,'fields':fields,'flags':applicable_flags(g['instructions'],row['entry_id'],row['progress'],g['zones'],now)})
  frame={'version':1,'group_id':g['id'],'event_id':g['event_id'],'session_id':g['session_id'],'name':g['name'],'event_name':g['event_name'],'state':g['state'],'provenance':g['provenance'],'format':g['format'],'layout_id':g['layout_id'],'started':g['started'],'ended':g['ended'],'duration_s':g['duration_s'],'laps':g['laps'],'timeline':now,'coverage':'host-confirmed complete field' if g['complete_field'] else 'connected-group standings','entries':entries,'map':g['map'],'map_model':g.get('map_model'),'map_revision':g['map_revision'],'pending_map_revision':(g.get('pending_map') or {}).get('revision'),'zones':g['zones'],'instructions':[i for i in g['instructions'] if not i['cancelled'] and (i['expires'] is None or i['expires']>now)],'messages':[m for m in g['messages'] if m['expires']>now],'decisions':g['decisions'],'battles':self.battles.get(g['id'],[]),'steward_cue_active':active_cue(g.get('steward_cues') or [],now),'projection':self._public_projection(g),'results':g['final_results'],'results_revision':g['results_revision'],'branding':{**g['branding_snapshot']['branding'],**g['branding']},'loss':{'frames':self.recording_drops,'error':self.recording_error}}
  self._snapshot_cache=(g['id'],g['session_id'],now,frame);return frame
 def filter_snapshot(self,raw,g,principal=None):
  data=clone(raw);allowed=fields_for(g['publication']);own=None
  if principal and permitted_by(principal,'telemetry.viewOwn'):
   _,p=self.member(principal)
   # Defense in depth alongside entry_update() clearing a reassigned-away
   # driver's own entry_id: even if that were ever missed, never treat a
   # participant as the entry's own driver unless the lease still points back
   # at them (telemetry()/lap_event() already enforce this on the write side).
   own=p['entry_id'] if p['entry_id'] and g['entries'].get(p['entry_id'],{}).get('participant_id')==p['id'] else None
  for row in data['entries']:
   permitted=fields_for(g['participants'][g['entries'][row['entry_id']]['participant_id']]['sharing']) if row['entry_id']==own else allowed;row['fields']={k:v for k,v in row['fields'].items() if k in permitted}
  data['messages']=[{**{k:v for k,v in m.items() if k not in ('receipts','targets')},'for_you':own in m['targets']} for m in data['messages'] if m['public'] or own in m['targets']];data['decisions']=[d for d in data['decisions'] if d['public']]
  # Battles use only basic data (always published); drivers see none of them (this
  # is desk/broadcast context, not something to surface in a driver's own app).
  # Traffic is derived from the RAW battles below, before that redaction, since a
  # driver's own battle_state tag is basic info even though the battle list itself isn't.
  is_driver=bool(principal and permitted_by(principal,'telemetry.viewOwn'))
  data['traffic']=self._traffic_for(data,raw.get('battles') or []) if is_driver and permitted_by(principal,'telemetry.viewAll',group=g) else None
  data['battles']=[] if is_driver else [b for b in data.get('battles',[]) if b['ahead'] in g['entries'] and b['behind'] in g['entries']]
  return data
 def _traffic_for(self,data,battles):
  """docs/AI_CONTEXT.md §12: basic-only per-entry traffic for a driver's own app -
  no fuel or telemetry values, host opt-in required (GroupConfig.share_traffic_with_drivers)."""
  battle_state={}
  for b in battles:
   battle_state.setdefault(b['ahead'],b['state']);battle_state.setdefault(b['behind'],b['state'])
  return [{'entry_id':r['entry_id'],'number':r['identity'].get('number'),'name':r['identity'].get('display_name'),'D':r['D'],'median_lap_s':(r['median_lap_ms']/1000) if r.get('median_lap_ms') else None,'in_pit':r['in_pit'],'battle_state':battle_state.get(r['entry_id'])} for r in data['entries']]
 def delayed_snapshot(self,g,delay):
  if self.replay:
   frame=self.replay_snapshot()
   return frame if frame and frame['group_id']==g['id'] else None
  if delay<=0:return self.raw_snapshot(g)
  cutoff=time.time()-delay;return next((frame for stamp,frame,_ in reversed(self.history) if stamp<=cutoff and frame['session_id']==g['session_id']),None)
 def viewer_frame(self,raw,g,principal,delay):
  """filter_snapshot() shared between viewers that see identical data: every non-driver
  (spectator/overlay) view of one frame is the same, so N subscribers cost one computation.
  Drivers see their own row, so they are keyed by participant."""
  viewer=principal['subject'] if permitted_by(principal,'telemetry.viewOwn') else 'view'
  key=(viewer,g['id'],g['session_id'],self.revision,tuple(g['publication']),delay,raw['timeline'])
  return dict(self.snapshots.get(key,lambda:self.filter_snapshot(raw,g,principal)))
 def public_state(self,principal,workspace=None):
  g=self.group(principal['group_id'])
  if principal['kind'] in ('driver','spectator'):
   _,p=self.member(principal)
   if p['status']!='admitted':return {'admission':p['status'],'entries':[]}
  delay=0 if principal['kind']=='driver' else max(g['delay_s'],(workspace or {}).get('program',{}).get('delay_s',0));raw=self.raw_snapshot(g) if principal['kind']=='driver' else self.delayed_snapshot(g,delay)
  if raw is None:return {'buffering':True,'delay_s':delay,'entries':[],'timeline':None}
  data=self.viewer_frame(raw,g,principal,delay);data['delay_s']=delay
  if workspace:
   revision={'program':workspace['program'],'revision':workspace['program_revision'],'taken_at':workspace['taken_at']}
   if revision['taken_at'] is not None and revision['taken_at']>raw['timeline']:
    revision=next((item for item in reversed(workspace.get('program_history',[])) if item['taken_at'] is None or item['taken_at']<=raw['timeline']),None)
    if revision is None:return {'buffering':True,'delay_s':delay,'entries':[],'timeline':raw['timeline']}
   data['workspace']=clone(revision['program']);data['program_revision']=revision['revision'];data['taken_at']=revision['taken_at']
  return data
 def workspace(self,id,principal=None,capability='graphics.view'):
  w=self.workspaces.get(id)
  if not w:fail(404,'Workspace not found')
  if principal and (w['group_id']!=principal['group_id'] or not permitted_by(principal,capability,w)):fail(403,'Workspace access denied')
  return w
 async def save_workspace(self,body,id=None,principal=None):
  config=WorkspaceConfig.model_validate(body).model_dump();g=self.group(principal['group_id'] if principal else None)
  if principal:
   _,p=self.member(principal)
   if not permitted_by(principal,'graphics.edit',member=p,group=g):fail(403,'Admitted broadcaster required')
  if config['branding'] and not g['allow_workspace_branding']:fail(403,'Workspace branding disabled')
  config['branding']=self.brand_override(config['branding'],g['league_id'])
  for key in ('primary','a','b'):
   if config['slots'].get(key) and config['slots'][key] not in g['entries']:fail(422,'Unknown selected entry')
  for item in config['graphics']:
   if item['entry_id'] and item['entry_id'] not in g['entries']:fail(422,'Unknown locked entry')
   if set(item['settings'])-{'title','rows','opacity'}:fail(422,'Unsupported graphic setting')
  if len({i['id'] for i in config['graphics']})!=len(config['graphics']):fail(422,'Graphic IDs must be unique')
  async with self.lock:
   if id:w=clone(self.workspace(id,principal,'graphics.edit'));w['draft']=config;w['draft_revision']+=1
   else:w={'id':uid(),'group_id':g['id'],'owner':principal['subject'] if principal else 'host','shared_with':[],'draft':config,'program':{**config,'graphics':[]},'draft_revision':1,'program_revision':0,'taken_at':None}
   await asyncio.to_thread(self.repo.commit,[('workspace',w['id'],g['id'],w)],(g['id'],g['session_id'],w['owner'],'workspace_saved',{'id':w['id']}));self.workspaces[w['id']]=w;return w
 async def take(self,id,principal=None):
  async with self.lock:
   w=clone(self.workspace(id,principal,'graphics.take'));g=self.group(w['group_id']);w['program_history']=(w.get('program_history',[])+[{'program':clone(w['program']),'revision':w['program_revision'],'taken_at':w['taken_at']}])[-128:];w['program']=clone(w['draft']);w['program_revision']+=1;w['taken_at']=time.time()
   await asyncio.to_thread(self.repo.commit,[('workspace',id,g['id'],w)],(g['id'],g['session_id'],principal['subject'] if principal else 'host','workspace_taken',{'id':id,'revision':w['program_revision']}));self.workspaces[id]=w;return w
 async def clear_program(self,id):
  async with self.lock:
   w=clone(self.workspace(id));g=self.group(w['group_id']);w['program_history']=(w.get('program_history',[])+[{'program':clone(w['program']),'revision':w['program_revision'],'taken_at':w['taken_at']}])[-128:];w['program']['graphics']=[{**item,'visible':False} for item in w['program']['graphics']];w['program_revision']+=1;w['taken_at']=time.time()
   await asyncio.to_thread(self.repo.commit,[('workspace',id,g['id'],w)],(g['id'],g['session_id'],'host','program_cleared',{'id':id,'revision':w['program_revision']}));self.workspaces[id]=w;return w
 async def focus_battle(self,battle_id,workspace_id,take=False,ensure_graphics=True,principal=None):
  """docs/AI_CONTEXT.md 4: point a workspace's head-to-head/telemetry slots at one
  battle. A spectator only ever sees their own delayed/filtered battles here (via
  public_state), never the raw feed, so this can't be used to see through the delay."""
  w=self.workspace(workspace_id,principal,'graphics.edit');g=self.group(w['group_id'])
  battles=self.public_state(principal,w).get('battles',[]) if principal else (self.battles.get(g['id']) or [])
  battle=next((b for b in battles if b['id']==battle_id),None)
  if not battle:
   engine=self.battle_engines.get(g['id']);st=engine.find(battle_id) if engine else None
   if not st or st.state!='ended' or time.time()-st.last_seen>30:fail(404,'Battle not found or ended')
   battle={'ahead':st.last_ahead,'behind':st.last_behind,'position':None}
  if battle['ahead'] not in g['entries'] or battle['behind'] not in g['entries']:fail(404,'Battle entry no longer in this event')
  draft=clone(w['draft']);draft['slots']={**draft['slots'],'a':battle['ahead'],'b':battle['behind'],'primary':battle['behind']};draft['selection_mode']='manual'
  warnings=[]
  if ensure_graphics:
   defaults={'comparison':(460,760,1000,300,'a'),'telemetry':(1260,780,620,260,'primary')}
   for template,(x,y,width,height,slot) in defaults.items():
    existing=next((it for it in draft['graphics'] if it['template']==template),None)
    if existing is None and len(draft['graphics'])<20:
     draft['graphics'].append({'id':uid(),'template':template,'visible':True,'x':x,'y':y,'width':width,'height':height,'entry_id':'','slot':slot,'duration_s':0,'settings':{}})
    elif existing and existing.get('entry_id'):warnings.append(f'{template} is locked to an entry; left unchanged')
    elif existing:existing['visible']=True
  saved=await self.save_workspace(draft,workspace_id,principal)
  if take:saved=await self.take(workspace_id,principal)
  async with self.lock:
   gg=clone(self.group(g['id']));await self.commit_group(gg,'battle_focused',{'battle_id':battle_id,'workspace_id':workspace_id,'take':take},principal['subject'] if principal else 'host')
  return {'workspace':saved,'warnings':warnings}
 async def share_workspace(self,id,participants):
  w=clone(self.workspace(id));g=self.group(w['group_id'])
  if any(p not in g['participants'] or g['participants'][p]['role']!='spectator' for p in participants):fail(422,'Select spectator participants')
  w['shared_with']=list(set(participants));await asyncio.to_thread(self.repo.commit,[('workspace',id,g['id'],w)]);self.workspaces[id]=w;return w
 async def overlay_token(self,id,principal=None):
  w=self.workspace(id,principal,'graphics.issueOutput');token=await asyncio.to_thread(self.repo.token,'overlay',id,w['group_id'],30*86400);return {'credential':token,'workspace_id':id,'expires_in':30*86400}
 async def record_loop(self):
  while True:
   frame=await self.frame_queue.get()
   try:await asyncio.to_thread(self.repo.frame,*frame);self.recording_error=None
   except Exception as e:self.recording_error=str(e)[:180];self.recording_drops+=1
   finally:self.frame_queue.task_done()
 async def drain_pit_stops(self):
  """Pit stops are detected synchronously per packet (telemetry() is not async);
  this moves their persistence onto the existing async tick instead, the same
  boundary self.history/frame_queue already cross."""
  pending,self.pending_pit_stops=self.pending_pit_stops,[]
  by_group=defaultdict(list)
  for group_id,stop in pending:by_group[group_id].append(stop)
  for group_id,stops in by_group.items():
   g=self.groups.get(group_id)
   if not g or g.get('closed'):continue
   async with self.lock:
    g=clone(self.group(group_id))
    g['pit_stops']=((g.get('pit_stops') or [])+stops)[-MAX_STOPS_PER_SESSION:]
    await self.commit_group(g,'pit_stops_recorded',{'count':len(stops)})
 async def loop(self):
  while self.running:
   from .demo import tick
   try:await tick(self)
   except Exception as error:
    if self.demo:self.demo['error']=str(getattr(error,'detail',error))[:180];self.demo['paused']=True
   if self.pending_pit_stops:await self.drain_pit_stops()
   start=time.monotonic();g=self.active()
   if g and not self.replay:
    frame=self.raw_snapshot(g);size=len(encode(frame));self.history.append((frame['timeline'],frame,size));self.history_bytes=sum(x[2] for x in self.history)
    while self.history and (self.history_bytes>64*1024*1024 or frame['timeline']-self.history[0][0]>121):self.history_bytes-=self.history.popleft()[2]
    if g['state']=='running':
     try:self.frame_queue.put_nowait((g['session_id'],frame['timeline'],frame))
     except asyncio.QueueFull:self.recording_drops+=1
   await asyncio.sleep(max(.01,.2-(time.monotonic()-start)))
 async def start(self):self.running=True;self.task=asyncio.create_task(self.loop());self.writer_task=asyncio.create_task(self.record_loop())
 async def close(self):
  self.running=False
  for task in self.battle_tasks.values():task.cancel()
  if self.battle_tasks:await asyncio.gather(*self.battle_tasks.values(),return_exceptions=True)
  self.battle_tasks={}
  for task in self.projection_tasks.values():task.cancel()
  if self.projection_tasks:await asyncio.gather(*self.projection_tasks.values(),return_exceptions=True)
  self.projection_tasks={}
  if self.client:await self.client.close()
  if self.listener:self.listener.should_exit=True
  if self.listener_task:
   try:await asyncio.wait_for(self.listener_task,5)
   except asyncio.TimeoutError:self.listener_task.cancel();await asyncio.gather(self.listener_task,return_exceptions=True)
  if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
  try:await asyncio.wait_for(self.frame_queue.join(),5)
  except asyncio.TimeoutError:pass
  if self.writer_task:self.writer_task.cancel();await asyncio.gather(self.writer_task,return_exceptions=True)
 def replay_snapshot(self):
  r=self.replay;position=min(r['position']+(0 if r['paused'] else (time.monotonic()-r['anchor'])*r['speed']),r['end']);frame=self.repo.frame_at(r['session_id'],position)
  if frame:frame['provenance']='replay';frame['timeline']=position;frame['replay']={'position':position,'paused':r['paused'],'speed':r['speed']}
  return frame
 async def replay_control(self,body):
  if body.get('action')=='stop':self.replay=None;return {'stopped':True}
  session=body.get('session_id') or (self.replay or {}).get('session_id');saved=self.repo.get('group_session',session)
  if not saved:fail(404,'Recorded group session not found')
  for key in ('position','speed'):
   if key in body and (isinstance(body[key],bool) or not isinstance(body[key],(int,float)) or not math.isfinite(body[key])):fail(422,'Replay values must be finite numbers')
  if self.active() and self.active()['state']=='running':fail(409,'End live session before replay')
  with self.repo.connect() as db:r=db.execute('SELECT MIN(utc),MAX(utc) FROM group_frames WHERE session_id=?',(session,)).fetchone()
  if r[0] is None:fail(404,'No recorded frames')
  self.replay={'session_id':session,'position':max(r[0],min(r[1],float(body.get('position',r[0])))),'end':r[1],'paused':bool(body.get('paused',False)),'speed':max(.25,min(16,float(body.get('speed',1)))),'anchor':time.monotonic()};return self.replay_snapshot()
