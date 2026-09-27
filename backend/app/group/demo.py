"""Deterministic synthetic league, independent of the local GT7 receiver."""
import math,time
from .repository import uid
from .service import fail

NAMES=['Alex Morgan','Jordan Lee','Sam Rivera','Taylor Chen','Casey Brooks','Jamie Rossi','Riley Park','Morgan Silva','Avery Scott','Quinn Patel','Drew Evans','Skyler Kim','Charlie Reed','Robin Diaz','Reese Clark','Finley Costa']
POSITIONS={'timing':(48,170,430,710),'session':(48,40,1824,96),'flag':(510,158,850,120),'message':(510,286,850,120),'driver':(510,830,850,190),'telemetry':(1400,744,470,280),'comparison':(510,510,850,270),'map':(1400,164,470,500),'results':(470,160,1100,790),'slate':(0,0,1920,1080)}
def scene():
 return [{'id':uid(),'template':kind,'visible':kind in ('timing','session','driver','telemetry','map','flag'),'x':v[0],'y':v[1],'width':v[2],'height':v[3],'slot':'primary','settings':{}} for kind,v in POSITIONS.items()]

async def start_demo(service,count=8):
 if isinstance(count,bool) or count not in (4,8,16):fail(422,'Choose 4, 8 or 16 synthetic drivers')
 active=service.active()
 if active:
  if active.get('demo_league') and service.demo:
   service.demo['paused']=False;service.demo['last']=time.monotonic();return {'running':True,'group_id':active['id']}
  fail(409,'Close the current group before creating a league demo. Existing events are preserved.')
 league=await service.league_save({'name':'APEX DEMO LEAGUE','short_name':'APEX','tagline':'SYNTHETIC RACE • BROADCAST REHEARSAL','colors':{'primary':'#f02442','secondary':'#20232c','accent':'#ae7bff','background':'#101014','text':'#ffffff'}})
 g=await service.create_group({'name':'Demo Grand Prix','event_name':'Broadcast rehearsal','league_id':league['id'],'format':'laps','laps':20,'capacity':16,'approval':False,'provenance':'demo','publication':['basic','telemetry','fuel','strategy']})
 g={**g,'demo_league':True};await service.commit_group(g,'demo_created',{'members':count})
 points=[[round((430+65*math.sin(t*3))*math.cos(t),3),round(280*math.sin(t),3)] for t in [i*math.tau/160 for i in range(161)]]
 await service.set_map(points,[{'name':'North marshal zone','start':.16,'end':.3},{'name':'Start / finish','start':.93,'end':.06}])
 invitation=await service.invite('driver');members=[]
 for i in range(count):
  joined=await service.join({'credential':invitation['credential'],'identity':{'display_name':NAMES[i]+' [DEMO]','number':str(11+i),'team':['Scuderia Apex','Vector Racing','Northstar','Velocity'][i%4],'class_name':'PRO' if i%3 else 'AM'},'accepted_sharing':['basic','telemetry','fuel','strategy']})
  members.append({'principal':await service.authenticate(joined['token']),'entry':joined['participant']['entry_id'],'index':i,'completed':0})
 await service.session_action('start')
 for member in members:await service.entry_update(member['entry'],{'baseline':1})
 await service.configure({'join_locked':True})
 workspace=await service.save_workspace({'name':'Demo broadcast','slots':{'primary':members[0]['entry'],'a':members[0]['entry'],'b':members[1]['entry']},'graphics':scene()})
 await service.take(workspace['id'])
 service.demo={'members':members,'elapsed':0.,'last':time.monotonic(),'paused':False,'speed':1,'sequence':0,'disconnected':set()}
 await tick(service)
 return {'running':True,'group_id':g['id'],'workspace_id':workspace['id']}

async def tick(service):
 d=service.demo
 if not d:return
 g=service.active()
 if not g or not g.get('demo_league') or g['state']!='running':service.demo=None;return
 now=time.monotonic();step=min(1,max(0,now-d['last']));d['last']=now
 if d['paused']:return
 d['elapsed']+=step*d['speed'];d['sequence']+=1
 for m in d['members']:
  i=m['index'];entry=m['entry']
  if entry in d['disconnected'] or g['participants'].get(m['principal']['subject'],{}).get('status')!='admitted':continue
  lap_seconds=76+i*.45;distance=d['elapsed']/lap_seconds+.7-i*.035;lap=int(distance)+1;progress=distance%1;t=progress*math.tau
  throttle=max(0,min(100,65+45*math.sin(t*4+i*.15)));brake=max(0,85-throttle*1.4);speed=90+throttle*1.7
  packet={'group_id':g['id'],'session_id':g['session_id'],'participant_id':m['principal']['subject'],'entry_id':entry,'boot_id':'league-demo','sequence':d['sequence'],'source_mono':now,'source_utc':time.time(),'provenance':'demo','layout_id':'','local_session_id':g['session_id'],'values':{'lap':lap,'car_id':[2159,2160,2183,2184][i%4],'position':[(430+65*math.sin(t*3))*math.cos(t),0,280*math.sin(t)],'flags':1,'speed_kmh':speed,'rpm':3500+throttle*45,'gear':min(6,max(2,int(speed/45))),'throttle':throttle,'brake':brake,'clutch':0,'fuel':max(0,82-d['elapsed']*.025),'fuel_capacity':100,'last_ms':lap_seconds*1000,'best_ms':(lap_seconds-.3)*1000},'available':['position','speed_kmh','rpm','gear','throttle','brake','clutch','fuel'],'quality':[]}
  service.telemetry(m['principal'],packet);service.live[entry]['progress']=progress;service.live[entry]['layout_compatible']=True
  if not service.live[entry]['completed_laps']:
   await service.lap_event(m['principal'],{'session_id':g['session_id'],'id':'demo-reference-'+entry,'duration_ms':(lap_seconds-.3)*1000,'number':0,'comparable':True,'quality':['synthetic reference lap']})
  if lap-1>m['completed']:
   await service.lap_event(m['principal'],{'session_id':g['session_id'],'id':f'demo-{entry}-{lap}','duration_ms':lap_seconds*1000,'number':lap-1,'comparable':True,'quality':['synthetic completed lap']});m['completed']=lap-1
