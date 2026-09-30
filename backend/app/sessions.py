import uuid, json
from datetime import datetime, timezone
from .analytics import Accumulator,lap_statistics,fuel_prediction,improvements

def utcnow():return datetime.now(timezone.utc).isoformat()

class Sessions:
    def __init__(self,store,settings):
        self.store=store; self.settings=settings; self.id=None; self.status='disconnected'; self.laps=[]; self.latest=None; self.last_report=None; self.manual_ended=False; self.lap_id=None; self.quality=set(); self.meta={}; self.reference=None; self.emit=None  # emit(kind,data): set by Runtime to publish lifecycle events on the bus
    def start(self,s=None):
        self.id=uuid.uuid4().hex; self.started=utcnow(); self.ended=None; self.laps=[]; self.quality=set(); self.status='driving' if s else 'connected/idle'; self.provenance=s.provenance if s else 'live'; self.number=None; self.acc=Accumulator(); self.partial=True; self.lap_id=uuid.uuid4().hex; self.manual_ended=False; self.latest=None
        self.meta={'track':self.settings.track,'layout':self.settings.layout,'direction':self.settings.direction,'notes':self.settings.setup_notes,'car_id':s.values['car_id'] if s else None,'settings':self.settings.model_dump(mode='json'),'parser_version':'1.0','official_validity':'unknown'}
        self.persist()
        if self.emit:self.emit('session_started',{'session_id':self.id,'provenance':self.provenance})
    def persist(self):
        if self.id:self.store.put('session',(self.id,self.started,self.ended,self.status,self.provenance,json.dumps(self.meta),json.dumps(self.report())))
    def close_lap(self,complete,game_ms=None):
        if self.number is None or not self.acc.samples:return
        summary=self.acc.summary(); duration=game_ms if complete and game_ms and 1000<game_ms<3600000 else round(self.acc.elapsed*1000)
        lap={'id':self.lap_id,'number':self.number,'duration_ms':duration,'timing_source':'game completed lap' if complete and game_ms and 1000<game_ms<3600000 else 'estimated active receive time','complete':complete,'partial':self.partial,'official_validity':'unknown','quality':sorted(self.quality), 'comparable':complete and not self.partial and not self.quality and not summary['refuel'],**summary}
        self.laps.append(lap); self.store.put('lap',(self.lap_id,self.id,json.dumps(lap)))
        if complete and self.emit:self.emit('lap_completed',{'session_id':self.id,'lap':lap})
        # Bound live aggregate memory; all original laps remain on disk.
        self.laps=self.laps[-2000:]
    def consume(self,s):
        v=s.values; ontrack=bool(v['flags']&1)
        if not self.id:
            if not ontrack or self.manual_ended:self.status='connected/idle' if not self.manual_ended else self.status; return
            self.start(s)
        if self.latest and (v['car_id']!=self.latest.values['car_id'] or (v['lap']<self.number and ontrack)):
            self.end('interrupted'); self.manual_ended=False; self.start(s)
        if self.number is None:self.number=v['lap']
        if v['lap']>self.number:
            if v['lap']!=self.number+1:self.quality.add('missed lap boundary')
            self.close_lap(True,v['last_ms']); self.number=v['lap']; self.acc=Accumulator(); self.partial=False; self.quality=set(); self.lap_id=uuid.uuid4().hex
            self.persist()
        if self.latest and s.mono-self.latest.mono>.25:self.quality.add('telemetry gap')
        self.quality.update(s.quality)
        self.status='paused' if v['flags']&2 else ('driving' if ontrack else 'connected/idle')
        region=self.settings.pit_region
        if self.status=='driving' and region and all(x is not None for x in v['position']):
            x,_,z=v['position']
            if region[0]<=x<=region[2] and region[1]<=z<=region[3]:self.status='suspected pit activity'
        self.acc.add(s); self.latest=s
        payload=s.json(); payload['session_id']=self.id; payload['lap_id']=self.lap_id
        if not self.store.put('sample',(self.id,self.lap_id,s.mono,v['packet_id'],json.dumps(payload))):self.quality.add('recording queue drop')
    def end(self,status='completed'):
        if not self.id:return self.last_report
        self.close_lap(False); self.status=status; self.ended=utcnow(); self.persist(); result=self.report(); result['id']=self.id
        self.last_report=result; ended_id=self.id; self.id=None; self.manual_ended=True
        if self.emit:self.emit('session_ended',{'session_id':ended_id,'status':status})
        return result
    def report(self):
        return {'status':self.status,'provenance':getattr(self,'provenance','unknown'),'laps':self.laps,'pace':lap_statistics(self.laps),'improvements':improvements(self.laps),'quality':sorted(self.quality),'recording':{'application_drops':self.store.drops,'failed_rows':self.store.failed_rows,'scope':'application lifetime; includes current session'},'official_validity':'unknown','report_status':'incremental summary ready','fuel':self.fuel()}
    def fuel(self):
        if not self.latest:return {'available':False,'reason':'No telemetry'}
        v=self.latest.values
        if not v['fuel_capacity'] or v['fuel_capacity']<=0:return {'available':False,'reason':'Fuel strategy unavailable for this powertrain'}
        uses=[l['fuel_used_l'] for l in self.laps if l['comparable']]
        total=self.settings.race_laps
        # Only configured distance is authoritative. Game count exposed separately.
        remaining=None; fraction=None; pace=lap_statistics(self.laps)['median_ms']
        if pace:
            current=v.get('current_ms') if self.settings.trust_c_fields else None
            fraction=min(.999,max(0,(current if current is not None else self.acc.elapsed*1000)/pace))
        if total is not None and fraction is not None:remaining=max(0,total-v['lap']+1-fraction)
        if self.settings.race_minutes is not None and pace:
            elapsed=sum(l['duration_ms'] for l in self.laps)+self.acc.elapsed*1000
            remaining=max(0,(self.settings.race_minutes*60000-elapsed)/pace)+(1 if self.settings.extra_lap else 0)
        result=fuel_prediction(v['fuel'],uses,self.settings.reserve_l,remaining)
        result.update({'remaining_distance_laps':remaining,'progress_source':'estimated timing fraction' if fraction is not None else 'unavailable','race_assumption':'user configured' if total or self.settings.race_minutes else 'unknown length'})
        return result
