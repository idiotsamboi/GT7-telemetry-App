import asyncio,time,json,copy,math
from collections import deque,defaultdict
from fastapi import HTTPException
from .models import *
from .repository import GroupRepository,uid,encode
from .timing import Projection,applicable_flags
from ..cars import identify
from ..tracks import LAYOUTS
BASIC={'position','lap','last_ms','best_ms','flags','car_id'}
CATEGORIES={'basic':BASIC,'telemetry':{'speed_kmh','rpm','gear','throttle','brake','clutch','tyres','current_ms'},'fuel':{'fuel','fuel_capacity'},'strategy':{'strategy'}}
def fields_for(categories):return set().union(*(CATEGORIES.get(c,set()) for c in categories))
def fail(status,message):raise HTTPException(status,message)
def clone(x):return copy.deepcopy(x)
class GroupService:
 def __init__(self,runtime):
  self.runtime=runtime;self.repo=GroupRepository(runtime.store.path);self.lock=asyncio.Lock();self.asset_lock=asyncio.Lock()
  self.groups={g['id']:g for g in self.repo.docs('group')};self.leagues={l['id']:l for l in self.repo.docs('league')};self.workspaces={w['id']:w for w in self.repo.docs('workspace')}
  self.live={};self.retired_streams=defaultdict(set);self.projectors={};self.history=deque(maxlen=650);self.history_bytes=0;self.boots={};self.connections={};self.tickets={};self.rate=defaultdict(deque)
  self.demo=None;self.running=False;self.task=None;self.listener=None;self.listener_task=None;self.recording_drops=0;self.recording_error=None;self.frame_queue=asyncio.Queue(maxsize=32);self.writer_task=None;self.replay=None;self.client=None;self._snapshot_cache=None
  for g in self.groups.values():
   if g.get('state')=='running':g['state']='interrupted'
   if g.get('map'):
    try:self.projectors[g['id']]=Projection(g['map'])
    except ValueError:pass
 def active(self):return next((g for g in self.groups.values() if not g.get('closed')),None)
 def group(self,id=None):
  g=self.groups.get(id) if id else self.active()
  if not g:fail(404,'Group not found')
  return g
 async def commit_group(self,g,kind,body,actor='host',documents=()):
  seq=await asyncio.to_thread(self.repo.commit,[('group',g['id'],'',g),*documents],(g['id'],g['session_id'],actor,kind,body));self.groups[g['id']]=g;self._snapshot_cache=None;return seq
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
   if set(row)-{'id','name','asset','enabled','slot','color'} or len(encode(row))>1000:fail(422,'Unsupported sponsor/team settings')
 async def league_save(self,body,id=None):
  b=Branding.model_validate(body).model_dump();id=id or uid()
  async with self.lock:
   item={'id':id,'revision':self.leagues.get(id,{}).get('revision',0)+1,'branding':b};self.check_assets(b,id)
   await asyncio.to_thread(self.repo.commit,[('league',id,'',item),('league_revision',uid(),id,item)]);self.leagues[id]=item
  return item
 def brand_override(self,body,league):
  if not isinstance(body,dict) or set(body)-set(Branding.model_fields):fail(422,'Unsupported branding override')
  valid=Branding.model_validate({**self.leagues[league]['branding'],**body}).model_dump();self.check_assets(valid,league);return {k:valid[k] for k in body}
 async def create_group(self,body):
  config=GroupConfig.model_validate(body).model_dump()
  async with self.lock:
   if self.active():fail(409,'Close current group first')
   league=self.leagues.get(config['league_id'])
   if not league:fail(422,'Create a league first')
   if config['layout_id'] and config['layout_id'] not in LAYOUTS:fail(422,'Unknown layout')
   config['branding']=self.brand_override(config['branding'],config['league_id'])
   g={**config,'id':uid(),'event_id':uid(),'session_id':uid(),'state':'draft','closed':False,'created':time.time(),'started':None,'ended':None,'policy_revision':1,'participants':{},'entries':{},'instructions':[],'messages':[],'decisions':[],'zones':[],'map':None,'map_revision':None,'branding_snapshot':clone(league),'final_results':None,'results_revision':0}
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
    g.update(session_id=uid(),state='running',started=time.time(),ended=None,instructions=[],messages=[],decisions=[],final_results=None,results_revision=0,branding_snapshot=clone(self.leagues[g['league_id']]))
    for entry in g['entries'].values():
     sample=self.live.get(entry['id']);entry['baseline']=sample['values'].get('lap') if sample and time.time()-sample['received']<2 else None;entry['baseline_source']='start snapshot' if entry['baseline'] is not None else None
    self.history.clear();self.history_bytes=0;self.replay=None
   elif action in ('end','close'):g['state']='completed';g['ended']=time.time();g['closed']=action=='close'
   elif action=='finalize':
    if g['state'] not in ('completed','interrupted'):fail(409,'End session before finalizing')
    g['final_results']=self.classification(g,time.time());g['results_revision']+=1
   else:fail(422,'Unknown session action')
   await self.commit_group(g,'session_'+action,{'session_id':g['session_id'],'results_revision':g['results_revision']},documents=[('group_session',g['session_id'],g['id'],g)]);return g
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
  tracker=getattr(self.runtime,'track_map',None);original=self.active()
  if not tracker or not original or not original['layout_id'] or original.get('demo_league'):return
  if original.get('map_source')=='manual' and not adopt and not original.get('pending_map'):return
  key=original['layout_id'];await asyncio.to_thread(tracker.alignment,key);model=tracker.map_for(key)
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
  if principal['kind']!='driver' or p['status']!='admitted':fail(403,'Admitted driver credential required')
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
  self.live[p['entry_id']]={'values':values,'sequence':packet.sequence,'source_mono':packet.source_mono,'source_utc':packet.source_utc,'received':now,'stream':stream,'provenance':packet.provenance,'quality':packet.quality,'available':packet.available,'progress':progress,'layout_compatible':compatible,'counter_reset':reset or bool(old and old.get('counter_reset')),'clock_uncertainty_ms':self.boots.get(p['id'],{}).get('uncertainty_ms'),'completed_laps':old.get('completed_laps',[]) if old and old['stream']==stream else []};return True
 async def lap_event(self,principal,body):
  g,p=self.member(principal)
  if principal['kind']!='driver' or p['status']!='admitted':fail(403,'Driver required')
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
   if principal['kind']!='driver' or p['status']!='admitted':fail(403,'Admitted driver required')
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
   await self.commit_group(g,'steward_decision',item);return item
 def classification(self,g,now):
  rows=[];superseded={d['supersedes'] for d in g['decisions'] if d['supersedes']}
  for e in g['entries'].values():
   p=g['participants'].get(e['participant_id'])
   if not p or p['status']!='admitted' or p['entry_id']!=e['id']:continue
   sample=self.live.get(e['id'],{});v=sample.get('values',{});stale=now-sample.get('received',0)>2;laps=sample.get('completed_laps',[]);best=min((l['duration_ms'] for l in laps if l['comparable']),default=None)
   base=e['baseline'];completed=max(0,v['lap']-base) if base is not None and v.get('lap') is not None and not sample.get('counter_reset') else None
   penalties=[d for d in g['decisions'] if d['entry_id']==e['id'] and d['id'] not in superseded and d['status']!='withdrawn'];penalty_laps=sum(int(d['value']) for d in penalties if d['kind']=='laps');penalty_ms=sum(d['value']*1000 for d in penalties if d['kind']=='time')
   elapsed=sum(l['duration_ms'] for l in laps) if laps and all(l['comparable'] for l in laps) else None;order=next((int(d['value']) for d in reversed(penalties) if d['kind']=='order'),None)
   rows.append({'entry_id':e['id'],'identity':e['identity'],'car':identify(v.get('car_id')),'car_id':v.get('car_id'),'stale':stale,'received':sample.get('received'),'last_ms':v.get('last_ms'),'best_ms':best,'reported_best_ms':v.get('best_ms'),'completed_laps':completed,'progress':None if stale else sample.get('progress'),'clock_uncertainty_ms':sample.get('clock_uncertainty_ms'),'quality':sample.get('quality',[]),'adjusted_laps':max(0,completed-penalty_laps) if completed is not None else None,'penalty_ms':penalty_ms,'adjusted_elapsed_ms':elapsed+penalty_ms if elapsed is not None else None,'disqualified':any(d['kind']=='disqualification' for d in penalties),'manual_order':order,'position':None,'gap_s':None,'lap_separation':None,'classification_source':'host correction' if order is not None else 'derived estimate','baseline_source':e['baseline_source']})
  if g['format'] in ('practice','qualifying'):rows.sort(key=lambda r:(r['disqualified'],r['best_ms'] is None,r['best_ms'] or math.inf,r['entry_id']))
  else:rows.sort(key=lambda r:(r['disqualified'],r['manual_order'] is None,r['manual_order'] or math.inf,r['adjusted_laps'] is None,-(r['adjusted_laps'] or 0),r['adjusted_elapsed_ms'] if g['state']!='running' and r['adjusted_elapsed_ms'] is not None else -(r['progress'] or 0),r['entry_id']))
  for i,r in enumerate(rows):
   usable=r['best_ms'] is not None if g['format'] in ('practice','qualifying') else r['completed_laps'] is not None and not r['stale'] and r['progress'] is not None
   if r['manual_order'] is not None:usable=True
   if usable and not r['disqualified']:r['position']=i+1
   if rows and r['completed_laps'] is not None and rows[0]['completed_laps'] is not None:r['lap_separation']=rows[0]['completed_laps']-r['completed_laps']
  return rows
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
  frame={'version':1,'group_id':g['id'],'event_id':g['event_id'],'session_id':g['session_id'],'name':g['name'],'event_name':g['event_name'],'state':g['state'],'provenance':g['provenance'],'format':g['format'],'layout_id':g['layout_id'],'started':g['started'],'ended':g['ended'],'duration_s':g['duration_s'],'laps':g['laps'],'timeline':now,'coverage':'host-confirmed complete field' if g['complete_field'] else 'connected-group standings','entries':entries,'map':g['map'],'map_model':g.get('map_model'),'map_revision':g['map_revision'],'pending_map_revision':(g.get('pending_map') or {}).get('revision'),'zones':g['zones'],'instructions':[i for i in g['instructions'] if not i['cancelled'] and (i['expires'] is None or i['expires']>now)],'messages':[m for m in g['messages'] if m['expires']>now],'decisions':g['decisions'],'results':g['final_results'],'results_revision':g['results_revision'],'branding':{**g['branding_snapshot']['branding'],**g['branding']},'loss':{'frames':self.recording_drops,'error':self.recording_error}}
  self._snapshot_cache=(g['id'],g['session_id'],now,frame);return frame
 def filter_snapshot(self,raw,g,principal=None):
  data=clone(raw);allowed=fields_for(g['publication']);own=None
  if principal and principal['kind']=='driver':_,p=self.member(principal);own=p['entry_id']
  for row in data['entries']:
   permitted=fields_for(g['participants'][g['entries'][row['entry_id']]['participant_id']]['sharing']) if row['entry_id']==own else allowed;row['fields']={k:v for k,v in row['fields'].items() if k in permitted}
  data['messages']=[{**{k:v for k,v in m.items() if k not in ('receipts','targets')},'for_you':own in m['targets']} for m in data['messages'] if m['public'] or own in m['targets']];data['decisions']=[d for d in data['decisions'] if d['public']];return data
 def delayed_snapshot(self,g,delay):
  if self.replay:
   frame=self.replay_snapshot()
   return frame if frame and frame['group_id']==g['id'] else None
  if delay<=0:return self.raw_snapshot(g)
  cutoff=time.time()-delay;return next((frame for stamp,frame,_ in reversed(self.history) if stamp<=cutoff and frame['session_id']==g['session_id']),None)
 def public_state(self,principal,workspace=None):
  g=self.group(principal['group_id'])
  if principal['kind'] in ('driver','spectator'):
   _,p=self.member(principal)
   if p['status']!='admitted':return {'admission':p['status'],'entries':[]}
  delay=0 if principal['kind']=='driver' else max(g['delay_s'],(workspace or {}).get('program',{}).get('delay_s',0));raw=self.raw_snapshot(g) if principal['kind']=='driver' else self.delayed_snapshot(g,delay)
  if raw is None:return {'buffering':True,'delay_s':delay,'entries':[],'timeline':None}
  data=self.filter_snapshot(raw,g,principal);data['delay_s']=delay
  if workspace:
   revision={'program':workspace['program'],'revision':workspace['program_revision'],'taken_at':workspace['taken_at']}
   if revision['taken_at'] is not None and revision['taken_at']>raw['timeline']:
    revision=next((item for item in reversed(workspace.get('program_history',[])) if item['taken_at'] is None or item['taken_at']<=raw['timeline']),None)
    if revision is None:return {'buffering':True,'delay_s':delay,'entries':[],'timeline':raw['timeline']}
   data['workspace']=clone(revision['program']);data['program_revision']=revision['revision'];data['taken_at']=revision['taken_at']
  return data
 def workspace(self,id,principal=None):
  w=self.workspaces.get(id)
  if not w:fail(404,'Workspace not found')
  if principal and (w['group_id']!=principal['group_id'] or principal['subject'] not in [w['owner'],*w['shared_with']]):fail(403,'Workspace access denied')
  return w
 async def save_workspace(self,body,id=None,principal=None):
  config=WorkspaceConfig.model_validate(body).model_dump();g=self.group(principal['group_id'] if principal else None)
  if principal:
   _,p=self.member(principal)
   if p['role']!='spectator' or p['status']!='admitted':fail(403,'Admitted broadcaster required')
  if config['branding'] and not g['allow_workspace_branding']:fail(403,'Workspace branding disabled')
  config['branding']=self.brand_override(config['branding'],g['league_id'])
  for key in ('primary','a','b'):
   if config['slots'].get(key) and config['slots'][key] not in g['entries']:fail(422,'Unknown selected entry')
  for item in config['graphics']:
   if item['entry_id'] and item['entry_id'] not in g['entries']:fail(422,'Unknown locked entry')
   if set(item['settings'])-{'title','rows','opacity'}:fail(422,'Unsupported graphic setting')
  if len({i['id'] for i in config['graphics']})!=len(config['graphics']):fail(422,'Graphic IDs must be unique')
  async with self.lock:
   if id:w=clone(self.workspace(id,principal));w['draft']=config;w['draft_revision']+=1
   else:w={'id':uid(),'group_id':g['id'],'owner':principal['subject'] if principal else 'host','shared_with':[],'draft':config,'program':{**config,'graphics':[]},'draft_revision':1,'program_revision':0,'taken_at':None}
   await asyncio.to_thread(self.repo.commit,[('workspace',w['id'],g['id'],w)],(g['id'],g['session_id'],w['owner'],'workspace_saved',{'id':w['id']}));self.workspaces[w['id']]=w;return w
 async def take(self,id,principal=None):
  async with self.lock:
   w=clone(self.workspace(id,principal));g=self.group(w['group_id']);w['program_history']=(w.get('program_history',[])+[{'program':clone(w['program']),'revision':w['program_revision'],'taken_at':w['taken_at']}])[-128:];w['program']=clone(w['draft']);w['program_revision']+=1;w['taken_at']=time.time()
   await asyncio.to_thread(self.repo.commit,[('workspace',id,g['id'],w)],(g['id'],g['session_id'],principal['subject'] if principal else 'host','workspace_taken',{'id':id,'revision':w['program_revision']}));self.workspaces[id]=w;return w
 async def clear_program(self,id):
  async with self.lock:
   w=clone(self.workspace(id));g=self.group(w['group_id']);w['program_history']=(w.get('program_history',[])+[{'program':clone(w['program']),'revision':w['program_revision'],'taken_at':w['taken_at']}])[-128:];w['program']['graphics']=[{**item,'visible':False} for item in w['program']['graphics']];w['program_revision']+=1;w['taken_at']=time.time()
   await asyncio.to_thread(self.repo.commit,[('workspace',id,g['id'],w)],(g['id'],g['session_id'],'host','program_cleared',{'id':id,'revision':w['program_revision']}));self.workspaces[id]=w;return w
 async def share_workspace(self,id,participants):
  w=clone(self.workspace(id));g=self.group(w['group_id'])
  if any(p not in g['participants'] or g['participants'][p]['role']!='spectator' for p in participants):fail(422,'Select spectator participants')
  w['shared_with']=list(set(participants));await asyncio.to_thread(self.repo.commit,[('workspace',id,g['id'],w)]);self.workspaces[id]=w;return w
 async def overlay_token(self,id,principal=None):
  w=self.workspace(id,principal);token=await asyncio.to_thread(self.repo.token,'overlay',id,w['group_id'],30*86400);return {'credential':token,'workspace_id':id,'expires_in':30*86400}
 async def record_loop(self):
  while True:
   frame=await self.frame_queue.get()
   try:await asyncio.to_thread(self.repo.frame,*frame);self.recording_error=None
   except Exception as e:self.recording_error=str(e)[:180];self.recording_drops+=1
   finally:self.frame_queue.task_done()
 async def loop(self):
  while self.running:
   from .demo import tick
   try:await tick(self)
   except Exception as error:
    if self.demo:self.demo['error']=str(getattr(error,'detail',error))[:180];self.demo['paused']=True
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
