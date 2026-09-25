"""Approximate causal lap alignment, bounded to 1500 points and 42 segments/query."""
import math

class LiveDelta:
    def __init__(self):
        self.identity=None;self.lap=None;self.points=[];self.reference=None;self.best=None;self.partial=True;self.bad=False;self.last=None;self.start=None;self.cursor=0;self.previous=None
        self.result={'available':False,'reason':'Record two complete clean laps to establish a reference','trend':0,'delta_s':None}
    def unavailable(self,reason):self.result={'available':False,'reason':reason,'trend':0,'delta_s':None};self.previous=None
    def consume(self,s):
        v=s.values;identity=(s.provenance,v.get('car_id'))
        if identity!=self.identity:self.__init__();self.identity=identity
        lap=v.get('lap');p=v.get('position');flags=v.get('flags',0)
        if self.last is not None and (s.mono-self.last>.5 or s.mono<self.last):self.bad=True;self.unavailable('Telemetry discontinuity')
        if not flags&1 or flags&6 or s.quality:self.bad=True;self.unavailable('Paused, loading or quality-limited telemetry');self.last=s.mono;return
        if not p or len(p)!=3 or any(x is None or not math.isfinite(x) for x in p):self.bad=True;self.unavailable('Position unavailable');return
        if self.lap is None:self.lap=lap;self.start=s.mono
        elif lap!=self.lap:
            duration=s.mono-self.start
            closed=bool(self.points and math.dist(self.points[0][1],p)<50)
            if lap==self.lap+1 and not self.partial and not self.bad and closed and len(self.points)>=20 and duration>=10:
                if self.best is None or duration<self.best:
                    self.reference=self.points+[(duration,list(p))];self.best=duration
            elif lap!=self.lap+1:self.reference=None;self.best=None
            self.points=[];self.partial=False;self.bad=False;self.lap=lap;self.start=s.mono;self.cursor=0;self.previous=None
        self.last=s.mono
        elapsed=s.mono-self.start
        if self.points and elapsed-self.points[-1][0]<.19:return
        if len(self.points)>=1500:self.bad=True;self.unavailable('Lap exceeds bounded five-minute alignment window');return
        self.points.append((elapsed,list(p)))
        if self.bad:self.unavailable('Current lap contains a telemetry interruption');return
        if not self.reference:self.unavailable('Complete a clean lap after the opening partial lap');return
        match=None
        for i in range(max(0,self.cursor-2),min(len(self.reference)-1,self.cursor+40)):
            ta,a=self.reference[i];tb,b=self.reference[i+1];d=[b[j]-a[j] for j in range(3)];length=sum(x*x for x in d)
            if length<.01:continue
            f=max(0,min(1,sum((p[j]-a[j])*d[j] for j in range(3))/length))
            distance=sum((p[j]-a[j]-f*d[j])**2 for j in range(3))
            if match is None or distance<match[0]:match=(distance,i,ta+f*(tb-ta))
        if match is None or match[0]>225:self.unavailable('Outside reference alignment corridor');return
        self.cursor=max(self.cursor,match[1]);delta=elapsed-match[2]
        trend=0 if self.previous is None or abs(delta-self.previous)<.01 else 1 if delta<self.previous else -1
        self.previous=delta
        self.result={'available':True,'delta_s':round(delta,3),'trend':trend,'reference_s':round(self.best,3),'reason':'Estimated position-aligned delta to best clean recorded lap; green = gaining, red = losing'}
