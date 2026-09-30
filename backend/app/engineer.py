from dataclasses import dataclass,field,asdict
from collections import deque
from typing import Callable
import uuid,time
from .core.registry import Registry

@dataclass
class Event:
    category:str
    message:str
    priority:int=2
    timestamp:float=field(default_factory=time.monotonic)
    ttl:float=12
    evidence:dict=field(default_factory=dict)
    confidence:str='direct or calculated'
    session:str|None=None
    requested:bool=False
    id:str=field(default_factory=lambda:uuid.uuid4().hex)
    @property
    def key(self):return (self.session,self.category)

class Scheduler:
    def __init__(self,settings,decision):
        self.settings=settings; self.decision=decision; self.pending=[]; self.history=deque(maxlen=80); self.last=-1e30; self.quiet_until=0; self.last_text=''; self.critical_last=-1e30
    def log(self,e,state,reason):self.decision({**asdict(e),'decision':state,'reason':reason})
    def offer(self,e):
        old=next((x for x in self.pending if x.key==e.key),None)
        if old:self.pending.remove(old); self.log(old,'merged','Superseded by newer category evidence')
        normal=sum(x.priority>0 for x in self.pending)
        if len(self.pending)>=20 or (e.priority>0 and normal>=16):self.log(e,'suppressed','Bounded queue full'); return
        self.pending.append(e)
    def cancel(self,reason='User stop'):
        for e in self.pending:self.log(e,'suppressed',reason)
        self.pending.clear()
    def next(self,now,session,workload=False,stale=False):
        for e in self.pending[:]:
            if now-e.timestamp>e.ttl or (e.session and e.session!=session) or (stale and not e.requested and e.category not in ('connection','recording','disk')):
                self.pending.remove(e); self.log(e,'expired','Stale evidence or session changed')
        self.history=deque((x for x in self.history if now-x[0]<60),maxlen=80)
        for e in sorted(self.pending,key=lambda x:(x.priority,x.timestamp)):
            s=self.settings
            if s.hard_mute:self.pending.remove(e); self.log(e,'muted','Hard mute');continue
            if not e.requested:
                if (s.mode=='Critical-only' or now<self.quiet_until) and e.priority>0:self.pending.remove(e);self.log(e,'suppressed','Verbosity or temporary quiet');continue
                if s.mode=='Quiet' and e.priority>1:self.pending.remove(e);self.log(e,'suppressed','Quiet mode');continue
                if e.priority==3 and s.mode!='Coaching':self.pending.remove(e);self.log(e,'suppressed','Coaching disabled');continue
                if workload and e.priority>=2:continue
                if e.priority==0 and now-self.critical_last<15:continue
                if e.priority>0 and (now-self.last<s.speech_gap or len(self.history)>=s.speech_per_min or sum(x[1] for x in self.history)>=s.speech_seconds):continue
            self.pending.remove(e); self.last_text=e.message
            if not e.requested:self.last=now;self.history.append((now,len(e.message.split())/2.5))
            if e.priority==0:self.critical_last=now
            self.log(e,'selected','Revalidated; ready for output');return e
        return None

# Each rule has explicit entry/exit, persistence and cooldown. No synthetic handling diagnosis.
@dataclass(slots=True)
class RuleContext:
    """Values every rule reads, computed once per frame (rules stay pure functions of this + settings)."""
    v:dict;cfg:object;fuel:float|None;valid_fuel:object;temp:float|None;imbalance:float;speed:float;inside:object

@dataclass(frozen=True)
class RuleSpec:
    """Declarative engineer rule. `entry_text`/`exit_text`/`prerequisite` are the documented conditions
    (served by /api/capabilities and ALERT_RULES.md); `entry`/`exit`/`message` are the executable form.
    Rules without callables (tyre_heat_rate) are evaluated by their own stateful method."""
    id:str;priority:int;persist_s:float;prerequisite:str;entry_text:str;exit_text:str
    entry:Callable[[RuleContext],object]|None=None;exit:Callable[[RuleContext],object]|None=None;message:Callable[[RuleContext],str]|None=None
    def public(self):return {'priority':self.priority,'persist':self.persist_s,'prerequisite':self.prerequisite,'entry':self.entry_text,'exit':self.exit_text}

def _off_surface(c):return sum(ch in 'DGSs' for ch in (c.v.get('surface') or ''))
RULE_SPECS:Registry[RuleSpec]=Registry('engineer_rules',public=lambda r:{'id':r.id,**r.public()})
for _r in (
 RuleSpec('low_fuel',1,3,'meaningful fuel capacity; configured threshold','fuel < low_fuel_l','fuel > low_fuel_l + 0.5',
  lambda c:c.valid_fuel and c.fuel<c.cfg.low_fuel_l,lambda c:not c.valid_fuel or c.fuel>c.cfg.low_fuel_l+.5,
  lambda c:f'Fuel low. {c.fuel:.1f} litres remaining.' if c.valid_fuel else ''),
 RuleSpec('fuel_critical',0,2,'fuel capacity > 0 and moving','fuel < 0.5 L','fuel > 0.8 L',
  lambda c:c.valid_fuel and c.fuel<.5 and c.speed>5,lambda c:not c.valid_fuel or c.fuel>.8 or c.speed<=5,
  lambda c:'Fuel critically low. Stop consumption or refuel.'),
 RuleSpec('tyre_hot',2,8,'user configured temperature limit','max surface > limit','max surface < limit - 3',
  lambda c:c.temp is not None and c.cfg.tyre_limit_c is not None and c.temp>c.cfg.tyre_limit_c,
  lambda c:c.temp is None or c.cfg.tyre_limit_c is None or c.temp<c.cfg.tyre_limit_c-3,
  lambda c:'Tyre surface temperature exceeds your configured limit.'),
 RuleSpec('tyre_imbalance',2,10,'four finite temperatures','left/right difference > configured threshold','difference < threshold - 3',
  lambda c:c.imbalance>c.cfg.tyre_imbalance_c,lambda c:c.imbalance<c.cfg.tyre_imbalance_c-3,
  lambda c:'Persistent left-right tyre temperature difference. Review the temperature trace.'),
 RuleSpec('limiter',3,3,'rev limiter flag while driving','flag set','flag clear',
  lambda c:bool(c.v['flags']&32),lambda c:not c.v['flags']&32,
  lambda c:'Prolonged limiter exposure. Consider an earlier shift.'),
 RuleSpec('handbrake',1,3,'speed > 30 km/h','handbrake flag','flag clear',
  lambda c:bool(c.v['flags']&64) and c.speed>30,lambda c:not c.v['flags']&64 or c.speed<20,
  lambda c:'Handbrake is still active.'),
 RuleSpec('off_surface',2,1.5,'validated C interpretation enabled','two tyres D/G/S/s','fewer than two',
  lambda c:c.cfg.trust_c_fields and _off_surface(c)>=2,lambda c:not c.cfg.trust_c_fields or _off_surface(c)<2,
  lambda c:'Multiple tyres report an off-surface condition. Official track limits are unknown.'),
 RuleSpec('pedal_overlap',3,4,'speed > 36 km/h','both pedals > 20%','either below 10%',
  lambda c:c.v['throttle']>.2 and c.v['brake']>.2 and c.speed>36,lambda c:c.v['throttle']<.1 or c.v['brake']<.1 or c.speed<30,
  lambda c:'Sustained pedal overlap. Check whether this is intentional.'),
 RuleSpec('pit_speed',1,1,'user configured pit region and limit','speed > limit + 2','speed <= limit',
  lambda c:c.inside and c.cfg.pit_limit_kmh and c.speed>c.cfg.pit_limit_kmh+2,lambda c:not c.inside or not c.cfg.pit_limit_kmh or c.speed<=c.cfg.pit_limit_kmh,
  lambda c:'Above your configured pit speed limit.'),
 RuleSpec('tyre_heat_rate',2,8,'2 warm-up laps completed since session start or a detected pit/refuel; v3 track lock preferred, time baseline otherwise',
  'rate >= 0.15 degC/s and anomaly >= +4 degC, both sustained','rate < 0.05 degC/s or anomaly < +2 degC'),
):RULE_SPECS.register(_r)
_CONDITION_SPECS=tuple(r for r in RULE_SPECS if r.entry)
RULES={r.id:r.public() for r in RULE_SPECS}     # legacy shape: /api/capabilities and Event evidence
TYRE_NAMES=('front-left','front-right','rear-left','rear-right')
TYRE_HEAT_ENTER_RATE=.15;TYRE_HEAT_ENTER_ANOMALY=4.;TYRE_HEAT_EXIT_RATE=.05;TYRE_HEAT_EXIT_ANOMALY=2.
TYRE_HEAT_COOLDOWN_PER_TYRE=120.;TYRE_HEAT_COOLDOWN_GLOBAL=60.;TYRE_HEAT_WARMUP_LAPS=2
class Rules:
    def __init__(self,settings):
        self.settings=settings;self.active={};self.fired={}
        self.tyre_active={};self.tyre_fired={};self.tyre_heat_fired=-1e30
        self.laps_since_start=0;self.last_lap=None;self.pit_exit_lap=None;self.was_inside_pit=False
    def evaluate(self,s,session,tyre_heat=None):
        v=s.values;now=s.mono;cfg=self.settings
        if v['flags']&6 or not v['flags']&1:self.active.clear();return []
        fuel=v.get('fuel');valid_fuel=v.get('fuel_capacity') and v['fuel_capacity']>0 and fuel is not None
        tyres=[t for t in v['tyres'] if t is not None]; temp=max(tyres) if tyres else None
        imbalance=max(abs(tyres[0]-tyres[1]),abs(tyres[2]-tyres[3])) if len(tyres)==4 else 0
        speed=v.get('speed_kmh') or 0
        region=cfg.pit_region; p=v.get('position'); inside=region and p and None not in p and region[0]<=p[0]<=region[2] and region[1]<=p[2]<=region[3]
        ctx=RuleContext(v,cfg,fuel,valid_fuel,temp,imbalance,speed,inside)
        events=[]
        for spec in _CONDITION_SPECS:
            key=spec.id;enter=spec.entry(ctx);leave=spec.exit(ctx)
            if leave:self.active.pop(key,None)
            if enter:self.active.setdefault(key,now)
            rule=RULES[key]
            if key in self.active and now-self.active[key]>=spec.persist_s and now-self.fired.get(key,-1e30)>=cfg.alert_cooldown:
                self.fired[key]=now;events.append(Event(key,spec.message(ctx),spec.priority,timestamp=now,session=session,evidence={'fuel_l':fuel,'speed_kmh':speed,'max_tyre_c':temp,'rule':rule}))
        lap=v.get('lap')
        if self.last_lap is not None and lap is not None and lap>self.last_lap:self.laps_since_start+=1
        self.last_lap=lap
        if self.was_inside_pit and not inside:self.pit_exit_lap=lap
        self.was_inside_pit=bool(inside)
        events+=self._tyre_heat_events(tyre_heat,lap,now,session)
        return events
    def _tyre_heat_events(self,tyre_heat,lap,now,session):
        if not tyre_heat:return []
        rates,anomalies=tyre_heat['rates'],tyre_heat['anomalies']
        # Hysteresis tracking always runs, even while suppressed below, so a
        # condition that's already been sustained through a pit stop or the
        # warm-up laps fires the moment suppression lifts rather than needing
        # another full persist window to re-accumulate from zero.
        rule=RULES['tyre_heat_rate'];persist=RULE_SPECS.require('tyre_heat_rate').persist_s;qualified=set()
        for i in range(4):
            enter=rates[i] is not None and rates[i]>=TYRE_HEAT_ENTER_RATE and anomalies[i] is not None and anomalies[i]>=TYRE_HEAT_ENTER_ANOMALY
            leave=rates[i] is None or rates[i]<TYRE_HEAT_EXIT_RATE or anomalies[i] is None or anomalies[i]<TYRE_HEAT_EXIT_ANOMALY
            if leave:self.tyre_active.pop(i,None)
            if enter:self.tyre_active.setdefault(i,now)
            if i in self.tyre_active and now-self.tyre_active[i]>=persist and now-self.tyre_fired.get(i,-1e30)>=TYRE_HEAT_COOLDOWN_PER_TYRE:qualified.add(i)
        if sum(a is not None for a in anomalies)<4:return []
        if self.laps_since_start<TYRE_HEAT_WARMUP_LAPS:return []
        if self.pit_exit_lap is not None and lap is not None and lap<=self.pit_exit_lap+1:return []
        if not qualified or now-self.tyre_heat_fired<TYRE_HEAT_COOLDOWN_GLOBAL:return []
        events=[]
        def emit(indices,message):
            for i in indices:self.tyre_fired[i]=now
            self.tyre_heat_fired=now
            evidence={'rates':rates,'anomalies':anomalies,'method':tyre_heat['method'],'tyres':list(indices)}
            events.append(Event('tyre_heat_rate',message,RULE_SPECS.require('tyre_heat_rate').priority,timestamp=now,session=session,evidence=evidence))
        remaining=set(qualified)
        if {0,1}<=qualified:emit((0,1),f'Front tyres heating fast, plus {max(anomalies[0],anomalies[1]):.0f} degrees. Consider a smoother entry.');remaining-={0,1}
        if {2,3}<=qualified:emit((2,3),f'Rear tyres heating fast, plus {max(anomalies[2],anomalies[3]):.0f} degrees. Consider a smoother entry.');remaining-={2,3}
        for i in sorted(remaining):
            emit((i,),f'{TYRE_NAMES[i].replace("-"," ").capitalize()} tyre heating fast: plus {anomalies[i]:.0f} degrees over your usual at this point. Ease the entry or check your line.')
        return events
