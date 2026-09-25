"""Bounded, causal analysis. No inferred tyre wear, grip or opponent data."""
from collections import deque
import math
from .telemetry import FIELDS, LENGTHS

class ReceptionTest:
    def __init__(self, now, counters, generation, duration=15):
        self.started=now; self.duration=duration; self.baseline=counters; self.generation=generation
        self.seen=set(); self.variants=set(); self.packets=0; self.last=None; self.max_gap=0.; self.result=None;self.quality_samples=0
    def observe(self, sample, now):
        if self.result or now>self.started+self.duration:return
        if self.last is not None:self.max_gap=max(self.max_gap,now-self.last)
        self.last=now; self.packets+=1; self.variants.add(sample.variant)
        if sample.quality:self.quality_samples+=1
        for name,_,_,_,_ in FIELDS:
            value=sample.values.get(name)
            if value is not None and (not isinstance(value,(list,tuple)) or all(x is not None for x in value)):self.seen.add(name)
    def snapshot(self, now, counters, generation):
        if self.result:return self.result
        elapsed=min(self.duration,max(0,now-self.started)); done=elapsed>=self.duration or generation!=self.generation
        changes={k:max(0,v-self.baseline.get(k,0)) for k,v in counters.items()}
        lengths={v:k for k,v in LENGTHS.items()}
        size=max((lengths[v] for v in self.variants),default=0)
        expected=[n for n,o,f,u,v in FIELDS if o<size]
        missing=sorted(set(expected)-self.seen)
        gap=max(self.max_gap, (min(now,self.started+self.duration)-(self.last or self.started)))
        status='running'
        if done:
            status='cancelled' if generation!=self.generation else 'no_data' if not self.packets else 'degraded' if any(changes.values()) or self.quality_samples or gap>0.5 or self.packets/max(elapsed,.001)<45 else 'healthy'
        result=dict(status=status,elapsed_s=round(elapsed,1),duration_s=self.duration,packets=self.packets,rate_hz=round(self.packets/max(elapsed,.001),1),max_gap_ms=round(gap*1000),counters=changes,variants=sorted(self.variants),fields_seen=len(self.seen),fields_expected=len(expected),unavailable_or_sentinel=missing,not_in_variant=[n for n,_,_,_,_ in FIELDS if n not in expected],note='Constant values are valid. Missing timing may be a game sentinel. Coverage proves receipt, not the meaning of undocumented fields.')
        result['samples_with_quality_flags']=self.quality_samples
        if done:self.result=result
        return result

class LiveAnalysis:
    def __init__(self):
        self.window=deque(maxlen=150);self.last=None;self.key=None;self.braking=None;self.episodes=deque(maxlen=8);self.result={}
    def consume(self,s):
        v=s.values; key=(s.provenance,v.get('car_id'),v.get('lap'))
        if key!=self.key or (self.last is not None and (s.mono-self.last>.5 or s.mono<self.last)):
            self.window.clear();self.braking=None;self.last=None;self.key=key
        if not v.get('flags',0)&1 or v.get('flags',0)&2:
            self.window.clear();self.last=None;self.braking=None;self.result={'available':False,'reason':'Paused or not on track'};return
        if self.last is not None and s.mono-self.last<.19:return
        speed=v.get('speed'); throttle=v.get('throttle');brake=v.get('brake')
        if any(x is None or not math.isfinite(x) for x in (speed,throttle,brake)):
            self.window.clear();self.last=None;self.braking=None;self.result={'available':False,'reason':'Required channels unavailable'};return
        dt=s.mono-self.last if self.last is not None else 0
        acceleration=(speed-self.window[-1][1])/dt if dt and self.window else None
        self.window.append((s.mono,speed,throttle,brake,dt));self.last=s.mono
        if brake>=.1 and self.braking is None:self.braking=(s.mono,speed)
        if brake<.05 and self.braking:
            start,entry=self.braking
            if s.mono-start>=.2:self.episodes.appendleft({'duration_s':round(s.mono-start,2),'entry_kmh':round(entry*3.6,1),'release_kmh':round(speed*3.6,1),'lap':v.get('lap')})
            self.braking=None
        total=sum(x[4] for x in self.window)
        def fraction(test):return round(100*sum(x[4] for x in self.window if test(x))/total,1) if total else None
        tyres=[t for t in (v.get('tyres') or []) if t is not None]
        self.result={'available':True,'source':s.provenance,'window_s':round(total,1),'longitudinal_g':round(acceleration/9.80665,2) if acceleration is not None else None,'coast_percent':fraction(lambda x:x[1]>10 and x[2]<.05 and x[3]<.05),'overlap_percent':fraction(lambda x:x[2]>.1 and x[3]>.1),'tyre_spread_c':round(max(tyres)-min(tyres),1) if len(tyres)==4 else None,'braking_episodes':list(self.episodes),'method':'5 Hz, trailing 30 s; acceleration from speed derivative; tyre surface temperature only'}
