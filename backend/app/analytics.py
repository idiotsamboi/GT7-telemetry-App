"""Incremental metrics: no whole-recording rescan in the receive path."""
import math, statistics
from collections import deque

def fuel_prediction(fuel, uses, reserve=2, remaining_laps=None):
    clean=[x for x in uses if x is not None and math.isfinite(x) and x>0]
    if fuel is None or len(clean)<3: return {'available':False,'reason':'Need three complete, clean fuel laps'}
    burn=statistics.median(clean[-7:]); spread=max(clean[-7:])-min(clean[-7:])
    needed=burn*remaining_laps+reserve if remaining_laps is not None else None
    return {'available':True,'source':'calculated','confidence':'moderate' if spread/burn<.2 else 'low',
        'litres_per_lap':burn,'laps_remaining':max(0,(fuel-reserve)/burn),'needed_l':needed,
        'margin_l':fuel-needed if needed is not None else None,
        'save_percent':max(0,100*(1-(fuel-reserve)/(burn*remaining_laps))) if remaining_laps else None,
        'refuel_l':max(0,needed-fuel) if needed is not None else None,'uncertainty_l':spread*(remaining_laps or 1)}

def lap_statistics(laps):
    times=[l['duration_ms'] for l in laps if l['comparable'] and l['duration_ms']]
    return {'best_ms':min(times) if times else None,'mean_ms':statistics.mean(times) if times else None,
        'median_ms':statistics.median(times) if times else None,'std_ms':statistics.pstdev(times) if times else None,
        'trend_ms':statistics.mean(times[-3:])-statistics.mean(times[-6:-3]) if len(times)>=6 else None,'count':len(times)}

def downsample(rows, limit=1200, channel='speed_kmh'):
    """Keep bucket extrema (rather than averaging braking/speed peaks away)."""
    if len(rows)<=limit:return rows
    result=[]; step=max(1,math.ceil(len(rows)/(limit//2)))
    for start in range(0,len(rows),step):
        bucket=rows[start:start+step]; valid=[r for r in bucket if isinstance(r['values'].get(channel),(float,int))]
        selected=[min(valid,key=lambda r:r['values'][channel]),max(valid,key=lambda r:r['values'][channel])] if valid else [bucket[0]]
        result.extend(sorted({r['mono']:r for r in selected}.values(),key=lambda r:r['mono']))
    return result

def approximate_compare(reference, candidate):
    """Distance normalization fallback. Explicitly not spatial alignment at crossings."""
    def progress(rows):
        out=[]; d=0
        for i,r in enumerate(rows):
            if i:d+=max(0,r['mono']-rows[i-1]['mono'])*(r['values'].get('speed') or 0)
            out.append((d,r['mono']-rows[0]['mono']))
        return [(x/d,t) for x,t in out] if d else []
    a,b=progress(reference),progress(candidate)
    if not a or not b:return {'available':False}
    j=0; deltas=[]
    for p,t in b:
        while j+1<len(a) and a[j+1][0]<p:j+=1
        deltas.append([p,t-a[j][1]])
    return {'available':True,'quality':'approximate distance normalization; unreliable at diverging lines/intersections','delta':deltas[::max(1,len(deltas)//400)]}

class Accumulator:
    def __init__(self):
        self.samples=0; self.distance=0.; self.elapsed=0.; self.coast=0.; self.overlap=0.; self.limiter=0.; self.max_speed=0.; self.tyre_max=[None]*4; self.prev=None; self.refuel=False; self.first_fuel=None; self.last_fuel=None
    def add(self,s):
        v=s.values; dt=min(.25,max(0,s.mono-self.prev)) if self.prev is not None else 0; self.prev=s.mono
        if not v['flags']&1 or v['flags']&6:return
        self.samples+=1; self.elapsed+=dt; speed=v.get('speed') or 0; self.distance+=speed*dt; self.max_speed=max(self.max_speed,speed*3.6)
        if speed>10 and v['throttle']<.05 and v['brake']<.05:self.coast+=dt
        if v['throttle']>.2 and v['brake']>.2:self.overlap+=dt
        if v['flags']&32:self.limiter+=dt
        for i,t in enumerate(v['tyres']):
            if t is not None:self.tyre_max[i]=max(t,self.tyre_max[i] if self.tyre_max[i] is not None else t)
        f=v.get('fuel')
        if f is not None:
            if self.first_fuel is None:self.first_fuel=f
            if self.last_fuel is not None and f>self.last_fuel+.2:self.refuel=True
            self.last_fuel=f
    def summary(self):
        return {'samples':self.samples,'distance_m':self.distance,'coast_s':self.coast,'overlap_s':self.overlap,
                'limiter_s':self.limiter,'max_speed_kmh':self.max_speed,'tyre_max_c':self.tyre_max,
                'fuel_used_l':self.first_fuel-self.last_fuel if self.first_fuel is not None and self.last_fuel is not None and not self.refuel else None,'refuel':self.refuel}

def improvements(laps):
    cards=[]
    for key,threshold,title,advice in [('overlap_s',2,'Repeated pedal overlap','Review whether overlapping pedal inputs are intentional. Compare release and pickup with a reference.'),('coast_s',5,'Repeated coasting','Compare these coasting sections with your reference before changing braking points.'),('limiter_s',1,'Repeated limiter exposure','Practice a slightly earlier shift at the marked RPM range.')]:
        affected=[l['number'] for l in laps if l.get(key,0)>threshold]
        if len(affected)>=2:cards.append({'title':title,'observation':f'Above {threshold:g} seconds on laps '+', '.join(map(str,affected[-8:])), 'laps':affected,'confidence':'moderate','impact_ms':None,'advice':advice,'channel':key})
    return cards[:3]

def align_laps(reference,candidate,corridor_m=25):
    """Local forward segment projection. Retains 3-D height and continuity at crossings.

    Requires comparable complete laps starting near the same line. Rejects ambiguous
    or divergent runs rather than silently substituting sample-index alignment.
    """
    def valid(rows):return [r for r in rows if len(r['values'].get('position') or [])==3 and all(isinstance(x,(float,int)) and math.isfinite(x) for x in r['values']['position'])]
    reference=valid(reference);candidate=valid(candidate)
    if len(reference)<20 or len(candidate)<20:return {'available':False,'reason':'Need at least 20 spatial samples per lap'}
    # Bound comparison complexity without changing the stored originals.
    reference=reference[::max(1,len(reference)//2400)];candidate=candidate[::max(1,len(candidate)//2400)]
    ref=[r['values']['position'] for r in reference];dist=[0.]
    for a,b in zip(ref,ref[1:]):dist.append(dist[-1]+math.dist(a,b))
    if dist[-1]<100:return {'available':False,'reason':'Insufficient reference distance'}
    if math.dist(ref[0],candidate[0]['values']['position'])>corridor_m:return {'available':False,'reason':'Lap starts do not align'}
    cursor=0;last_progress=0;bad=0;out=[]
    for row in candidate:
        p=row['values']['position'];best=None
        for j in range(max(0,cursor-2),min(len(ref)-1,cursor+45)):
            a,b=ref[j],ref[j+1];ab=[b[k]-a[k] for k in range(3)];den=sum(x*x for x in ab)
            if den<.001:continue
            t=max(0,min(1,sum((p[k]-a[k])*ab[k] for k in range(3))/den));projection=[a[k]+t*ab[k] for k in range(3)];error=math.dist(p,projection);progress=dist[j]+t*(dist[j+1]-dist[j])
            if progress<last_progress-3:continue
            if best is None or error<best[0]:best=(error,j,t,progress)
        if not best or best[0]>corridor_m:bad+=1;continue
        error,j,t,progress=best;cursor=max(cursor,j);last_progress=max(last_progress,progress)
        ref_time=reference[j]['mono']+t*(reference[j+1]['mono']-reference[j]['mono'])-reference[0]['mono'];elapsed=row['mono']-candidate[0]['mono']
        out.append({'progress_m':last_progress,'delta_s':elapsed-ref_time,'distance_error_m':error,'speed_kmh':row['values'].get('speed_kmh')})
    fraction=bad/len(candidate);coverage=last_progress/dist[-1]
    if fraction>.1 or coverage<.9:return {'available':False,'reason':'Spatial continuity/corridor or coverage check failed','excluded_fraction':fraction,'coverage':coverage}
    return {'available':True,'quality':'spatial projection with forward continuity; review pit divergence and crossings','confidence':'moderate','excluded_fraction':fraction,'coverage':coverage,'delta':out[::max(1,len(out)//600)]}

def braking_episodes(rows):
    episodes=[];active=None
    for r in rows:
        v=r['values'];brake=v.get('brake') or 0
        if brake>.1 and active is None:active={'start':r['mono'],'position':v.get('position'),'entry_kmh':v.get('speed_kmh'),'peak':brake}
        if active:
            active['peak']=max(active['peak'],brake)
            if brake<.05:
                if r['mono']-active['start']>.2:episodes.append({**active,'duration_s':r['mono']-active['start'],'exit_kmh':v.get('speed_kmh')})
                active=None
    return episodes
