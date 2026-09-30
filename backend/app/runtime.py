import asyncio,time,socket,json,shutil,platform,os,logging,math
from .diagnostics import udp_owners,routing_address
from .core.platform import exclusive_udp_bind_supported
from collections import deque
from pathlib import Path
from .telemetry import parse,Sequence,demo_sample,Sample,PacketError,PARSER_VERSION
from .sessions import Sessions,utcnow
from .engineer import Scheduler,Rules,Event,RULES
from .voice import Speaker,Microphone,intent
from .live_analysis import ReceptionTest,LiveAnalysis
from .live_delta import LiveDelta
from .cars import identify
from .requests import answer as engineer_answer
from .analytics import fuel_scenarios,lap_statistics
from .clean_air import pit_advice
from .local_ai import LocalAI
from .tracks import TrackMap,LAYOUTS
from .training import TrainingRecorder
from .track_service import TrackService
from .tyre_heat import TyreHeatMonitor
from .spatial_coaching import SpatialLap,LiveBrakingTracker,corner_report
from .runtime_services import build_services
from .safe_mode import SafeModeSettings
from .core import features as feature_flags
from .telemetry import TelemetryFrame
from .telemetry.bus import TelemetryBus,TelemetryEvent,CONNECTION_CHANGED,PIT_DETECTED,SOURCE_CHANGED,TRACK_LOCKED,TRACK_UNLOCKED
from .telemetry.derived import DerivedEngine
from .telemetry.units import spoken_measure
from .domain.alerts import AlertCenter
from .engineer_service import RuntimeEngineer
from .core.platform import resolve_performance_profile
from .core.defaults import UI_HZ_LOW_POWER,HISTORY_LEN,HISTORY_LEN_LOW_POWER
from .gamification.repository import CareerRepository
from .gamification.processor import CareerProcessor

class Runtime:
    def __init__(self,config,store):
        self.host_only=False;self.safe_mode=None;self._flags={};self.scenario_override='';self.performance_profile=resolve_performance_profile(config.settings.performance_profile)
        self.answer_variations={};self.last_answer=''
        self.local_ai=LocalAI();self.ai_refresh_requested=False
        self.reception_test=None;self.live_analysis=LiveAnalysis();self.live_delta=LiveDelta()
        self.track_map=TrackMap(config.root);self.track_map.select(config.settings.track_id,manual=False)
        self.training=TrainingRecorder(config.root)
        self.track=TrackService(config.root,config.settings);self.progress_s=None;self._track_project_at=0.;self._track_last_mono=0.
        self.tyre_heat=TyreHeatMonitor();self.tyre_heat_result=None
        self.spatial_lap=None;self.spatial_reference=None;self.spatial_braking=LiveBrakingTracker();self.spatial_reference_episodes=[];self.spatial_reference_lap=None;self._lap_episodes=[];self._lap_start_mono=None;self.coaching_result=None
        self.fuel_alert_fired=False;self.fuel_alert_lap=-1e9;self.fuel_alert_recommendation=None
        self.config=config;self.settings=config.settings;self.store=store;self.sessions=Sessions(store,self.settings)
        self.events=deque(maxlen=100);self.scheduler=Scheduler(self.settings,self.decision);self.rules=Rules(self.settings);self.speaker=Speaker();self.mic=Microphone()
        self.alerts=AlertCenter();self.engineer=RuntimeEngineer(self);self.bus=TelemetryBus(on_error=self._pipeline_error);self.derived=DerivedEngine();self.derived_values={};self.dev_frames=deque(maxlen=50);self.seq=Sequence();self.sample=None;self.received_at=None;self.received=0;self.parse_errors=0;self.unexpected=0;self.socket_error=None;self.source='live';self.running=True;self.transport=None;self.demo_time=0.;self.demo_index=0;self.trace=deque(maxlen=self._buffer_len());self.history=deque(maxlen=self._buffer_len())
        self.receiver={'phase':'not_configured','datagrams':0,'valid_packets':0,'heartbeats':0,'last_sender':None,'last_length':None,'last_variant':None,'last_error':None,'error_counts':{},'port_owners':[],'local_route':None,'parser_version':PARSER_VERSION}
        self.source_generation=0;self.last_datagram_at=None;self.pipeline_errors=0
        self.mic_restart=False;self.mic_testing=False
        self.tasks=[];self._scenario_iter=None;self._scenario_t0=0.;self._scenario_base=None;self.services_cache=[];self.clients=0;self.loop_lag=0.;self.health_cache={};self.transcript=None;self.box=False;self.replay=None;self.replay_paused=False;self.replay_speed=1.;self.replay_cursor=0.;self.replay_record_id=0;self.replay_buffer=deque(maxlen=1100);self.replay_last=None;self.degraded=False;self.bad_since=None;self.good_since=None;self.last_lap=None
        self.career_repository=CareerRepository(store);self.career=CareerProcessor(self,self.career_repository)
        self._wire_bus();self._refresh_flags()
    def decision(self,event):
        event['utc']=utcnow();self.events.appendleft(event)
        if event.get('decision') in ('selected','subtitle') and not event.get('requested'):self._raise_alert(event)
        self.store.put('event',(event.get('session') or self.sessions.id,event['utc'],json.dumps(event)))
    _ALERT_SOURCES={'connection':'network','recording':'storage','disk':'storage'}
    _ALERT_SEVERITY=('critical','warning','notice','info')
    def _raise_alert(self,event):
        """Display/notification model. The Scheduler stays the speech arbiter; an alert is what the UI lists."""
        category=event.get('category','');priority=event.get('priority',2)
        source=self._ALERT_SOURCES.get(category) or ('telemetry' if category in RULES else 'engineer')
        severity=self._ALERT_SEVERITY[priority] if isinstance(priority,int) and 0<=priority<=3 else 'notice'
        self.alerts.raise_alert(source,severity,category.replace('_',' ').capitalize(),event.get('message',''),ttl_s=600 if severity in ('info','notice') else None,dedupe_key=category,context={'session':event.get('session'),'evidence':event.get('evidence') or {}})
    def event(self,category,message,priority=2,evidence=None,requested=False):
        self.scheduler.offer(Event(category,message,priority,evidence=evidence or {},requested=requested,session=self.sessions.id))
    async def start(self):
        from .group.service import GroupService
        await self.career.start()
        self.group=GroupService(self);await self.group.start()
        self.tasks=[];self.services=build_services(self);await self.services.start_all();self.refresh_services()
    def _buffer_len(self):
        """Display-only history/trace length (10 Hz points). LOW_POWER halves it; the recorder is never affected."""
        return HISTORY_LEN_LOW_POWER if self.performance_profile=='LOW_POWER' else HISTORY_LEN
    def feature(self,flag_id):
        """Feature flag state (cached; refreshed when settings or safe mode change)."""
        return self._flags.get(flag_id,True)
    def _refresh_flags(self):
        safe=self.safe_mode is not None
        self._flags={f.id:feature_flags.is_enabled(f.id,self.settings,safe_mode=safe) for f in feature_flags.FEATURES}
        view=SafeModeSettings(self.settings) if safe else self.settings
        self.sessions.settings=view;self.rules.settings=view
    def set_safe_mode(self,mode):
        self.safe_mode=mode;self._refresh_flags()
    def effective_ui_hz(self):
        """LOW_POWER lowers only what the UI is sent; recording rate and accuracy are never touched."""
        hz=self.settings.ui_hz
        return min(hz,UI_HZ_LOW_POWER) if self.performance_profile=='LOW_POWER' else hz
    def refresh_services(self):
        self.services_cache=self.services.public()
    async def close(self):
        self.running=False
        if hasattr(self,"group"):await self.group.close()
        if hasattr(self,'services'):await self.services.stop_all()
        for task in self.tasks:task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        await self.local_ai.close()
        await asyncio.to_thread(self.track_map.flush)
        if self.transport:self.transport.close()
        self.sessions.end('interrupted');self.speaker.stop();await self.career.close();await asyncio.to_thread(self.mic.close);await asyncio.to_thread(self.store.close)
    def ingest_datagram(self,data,addr,received_mono=None):
        """Fault boundary: one malformed datagram or parser bug cannot kill reception."""
        now=time.monotonic() if received_mono is None else received_mono
        self.receiver['datagrams']+=1
        self.receiver['last_sender']=f'{addr[0]}:{addr[1]}'
        self.receiver['last_length']=len(data)
        self.last_datagram_at=now
        if addr[0]!=str(self.settings.ps5_ip):
            self.unexpected+=1
            return False
        try:
            sample=parse(data,raw=self.settings.raw_capture,mono=now)
        except Exception as error:
            self.parse_errors+=1
            code=error.code if isinstance(error,PacketError) else 'parser_exception'
            errors=self.receiver['error_counts'];errors[code]=errors.get(code,0)+1
            self.receiver['last_error']={'code':code,'message':str(error)[:300],'utc':utcnow()}
            self.receiver['phase']='packets_rejected'
            if code=='parser_exception' and errors[code]==1:logging.exception('Telemetry parser failed; reception continues')
            return False
        self.receiver['valid_packets']+=1
        self.receiver['last_variant']=sample.variant
        self.receiver['phase']='receiving'
        self.receiver['last_error']=None
        before=self.seq.counts.copy()
        if not self.seq.accept(sample.values['packet_id']):return False
        try:
            gap=self._sequence_effects(sample,before)
            self.consume(sample,sequence_gap=gap or None,source_addr=self.receiver['last_sender'])
            return True
        except Exception as error:
            self.pipeline_errors+=1
            self.receiver['last_error']={'code':'pipeline_exception','message':str(error)[:300],'utc':utcnow()}
            if self.sessions.id:self.sessions.quality.add('application processing failure')
            if self.pipeline_errors==1:logging.exception('Sample processing failed; receiver remains active')
            return False

    async def source_loop(self):
        loop=asyncio.get_running_loop();sock=None;heartbeat=0;retry=0;next_sample=time.monotonic();generation=self.source_generation
        try:
            while self.running:
                now=time.monotonic()
                if generation!=self.source_generation:
                    if sock:sock.close()
                    sock=None;self.transport=None;retry=0;heartbeat=0;generation=self.source_generation;next_sample=now
                if self.host_only:
                    self.receiver['phase']='host_only';await asyncio.sleep(.2);continue
                if self.source=='demo':
                    self.receiver['phase']='demo_no_network'
                    if self.scenario_name():
                        await self._scenario_step(now);continue
                    sample=demo_sample(self.demo_time,self.demo_index);sample.mono=now;self.consume(sample)
                    self.demo_time+=1/60;self.demo_index+=1
                    next_sample=max(next_sample+1/60,now+.001)
                    await asyncio.sleep(max(0,next_sample-time.monotonic()));continue
                if self.source=='replay':
                    self.receiver['phase']='replay_no_network'
                    if self.replay_paused:await asyncio.sleep(.05);continue
                    if not self.replay_buffer:
                        rows=await asyncio.to_thread(self.store.samples,self.replay,self.replay_cursor,1000,self.replay_record_id)
                        if not rows:self.sessions.end('completed');self.replay_paused=True;continue
                        self.replay_buffer.extend(rows)
                    row=self.replay_buffer.popleft()
                    delay=max(0,min(2,row['mono']-(self.replay_last if self.replay_last is not None else row['mono'])))/self.replay_speed
                    await asyncio.sleep(delay)
                    if generation!=self.source_generation:continue
                    self.replay_last=row['mono'];self.replay_cursor=row['mono'];self.replay_record_id=row['record_id']
                    self.consume(Sample(row['values'],row['mono'],row['utc'],row['variant'],'replay',row['quality']))
                    continue
                if not self.settings.ps5_ip:
                    self.receiver['phase']='not_configured';await asyncio.sleep(.2);continue
                if sock is None:
                    if now<retry:await asyncio.sleep(.2);continue
                    self.receiver['phase']='binding'
                    try:
                        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                        if exclusive_udp_bind_supported():sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                        sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024*1024)
                        sock.setblocking(False)
                        sock.bind((str(self.settings.udp_bind),self.settings.udp_port))
                        self.transport=sock;self.socket_error=None;heartbeat=0
                        self.receiver['port_owners']=[]
                        self.receiver['local_route']=routing_address(str(self.settings.ps5_ip))
                        self.receiver['receive_buffer_bytes']=sock.getsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF)
                        self.receiver['phase']='awaiting_packets'
                    except OSError as error:
                        if sock:sock.close()
                        sock=None;self.transport=None
                        owners=await asyncio.to_thread(udp_owners,self.settings.udp_port)
                        self.receiver['port_owners']=owners
                        names=', '.join(f"{x.get('name','process')} (PID {x.get('pid','?')})" for x in owners)
                        self.socket_error=f'Cannot bind local UDP {self.settings.udp_bind}:{self.settings.udp_port}. '+(f'Already used by {names}. Close the other receiver to use GT7 Race Engineer.' if owners else f'{error}. Check the local interface and other telemetry apps.')
                        self.receiver['phase']='bind_failed';retry=time.monotonic()+5;continue
                try:
                    if now>=heartbeat and not self.safe_mode:
                        await loop.sock_sendto(sock,self.settings.variant.encode('ascii'),(str(self.settings.ps5_ip),self.settings.remote_port))
                        self.receiver['heartbeats']+=1;self.receiver['last_heartbeat_utc']=utcnow()
                        heartbeat=now+self.settings.heartbeat
                    try:data,addr=await asyncio.wait_for(loop.sock_recvfrom(sock,65535),timeout=.2 if self.safe_mode else max(.001,min(.2,heartbeat-time.monotonic())))
                    except asyncio.TimeoutError:
                        if self.received_at and now-self.received_at>self.settings.stale_seconds:self.receiver['phase']='stale'
                        continue
                    if generation!=self.source_generation or self.source!='live':continue
                    self.ingest_datagram(data,addr,time.monotonic())
                except OSError as error:
                    self.socket_error=str(error);self.receiver['phase']='socket_error';sock.close();sock=None;self.transport=None;retry=now+5
        finally:
            if sock:sock.close()
            self.transport=None
    def scenario_name(self):
        return self.settings.demo_scenario or self.scenario_override
    def _sequence_effects(self,sample,before):
        """What an accepted packet's sequence outcome means, shared by live ingestion and scenario playback."""
        if self.seq.counts['resets']>before['resets']:
            self.sessions.end('interrupted');self.sessions.manual_ended=False;self.scheduler.cancel('Sequence reset')
        gap=self.seq.counts['gaps']-before['gaps']
        if gap:
            sample.quality.append('source sequence gap')
            if self.sessions.id:self.sessions.quality.add('source sequence gap')
        return gap
    async def _scenario_step(self,now):
        """Demo source driven by a deterministic scenario (telemetry/sources.py). Frames pass through the same
        Sequence guard as live packets, so gap/reorder/stale scenarios exercise the real ingestion logic. SYNTHETIC."""
        if self._scenario_iter is None:
            from .telemetry.sources import ScenarioDemo
            self._scenario_iter=ScenarioDemo(seed=0).run(self.scenario_name());self._scenario_t0=now;self._scenario_base=None
        item=next(self._scenario_iter,None)
        if item is None:
            self.receiver['phase']='demo_scenario_complete';await asyncio.sleep(.2);return
        generation=self.source_generation
        await asyncio.sleep(max(0,self._scenario_t0+item.mono_offset_s-time.monotonic()))
        if generation!=self.source_generation or self.source!='demo':return      # source switched during a (possibly long) silent gap
        if item.sample is None:return                     # a deliberate silent gap (stale/session-end scenarios)
        s=item.sample
        if self._scenario_base is None:self._scenario_base=s.mono
        s.mono=self._scenario_t0+(s.mono-self._scenario_base)
        before=self.seq.counts.copy()
        if not self.seq.accept(item.packet_id):return
        gap=self._sequence_effects(s,before)
        self.consume(s,sequence_gap=gap or None)
    def consume(self,s,*,sequence_gap=None,source_addr=None):
        """Every accepted sample (live, demo, replay) enters here and is fanned out on the TelemetryBus.
        Subscriber order is the original explicit call order (see _wire_bus); a failing subscriber is
        isolated and counted as a pipeline error, it no longer skips the subscribers after it."""
        self.bus.publish(TelemetryFrame.from_sample(s,sequence_gap=sequence_gap,source_addr=source_addr))
    def _wire_bus(self):
        b=self.bus
        b.subscribe('driver_line',self._on_frame_reset)
        b.subscribe('track_map',lambda f:self.track_map.consume(f.sample))
        b.subscribe('training',lambda f:self.training.consume(f.sample))
        b.subscribe('track_service',lambda f:self.consume_track_service(f.sample))
        b.subscribe('live_delta',lambda f:self.live_delta.consume(f.sample))       # attribute resolved per call: reset_driver_line swaps the object
        b.subscribe('live_analysis',lambda f:self.live_analysis.consume(f.sample))
        b.subscribe('reception_test',self._on_frame_reception)
        b.subscribe('sessions',self._on_frame_session)
        b.subscribe('coaching',self._on_frame_coaching)
        b.subscribe('rules',self._on_frame_rules)
        b.subscribe('derived',lambda f:setattr(self,'derived_values',self.derived.evaluate(f)),mode='rate',hz=20)
        b.subscribe('dev_packets',self._on_frame_dev,mode='rate',hz=10)   # no-op unless Settings.developer_mode
        self.sessions.emit=lambda kind,data:self.bus.emit(TelemetryEvent(kind,data,time.monotonic()))
        b.subscribe_events('driver_career',self.career.on_event,kinds=('session_started','lap_completed','session_ended','spatial_analysis_completed','track_locked','track_unlocked'))
    def _pipeline_error(self,name,error):
        self.pipeline_errors+=1
        self.receiver['last_error']={'code':'pipeline_exception','message':f'{name}: {error}'[:300],'utc':utcnow()}
        if self.sessions.id:self.sessions.quality.add('application processing failure')
    def _on_frame_reset(self,f):
        s=f.sample;previous=self.sample.values if self.sample else None
        # GT7's car-on-track flag is cleared on circuit exit. Pausing alone
        # keeps that flag set and must preserve the driver's line.
        if (not s.values.get('flags',0)&1 or
            (previous and (s.values.get('car_id')!=previous.get('car_id') or
             s.values.get('lap',0)<previous.get('lap',0)))):
            self.reset_driver_line(forget_layout=True)
    def _on_frame_dev(self,f):
        if not self.settings.developer_mode:return
        m=f.meta;self.dev_frames.appendleft({'mono':m.mono,'utc':m.utc,'packet_id':m.packet_id,'variant':m.variant,'provenance':m.provenance,'wire_length':m.wire_length,'quality':list(m.quality),'sequence_gap':m.sequence_gap,'values':f.values,'raw_hex':f.sample.raw_hex})
    def _on_frame_reception(self,f):
        if self.reception_test and f.meta.provenance=='live':self.reception_test.observe(f.sample,time.monotonic())
    def _on_frame_session(self,f):
        s=f.sample
        now=time.monotonic();restored=self.received_at is None or now-self.received_at>self.settings.stale_seconds
        previous_session=self.sessions.id
        self.received_at=now;self.received+=1;self.sample=s;self.sessions.consume(s)
        if self.sessions.id and self.sessions.id!=previous_session:
            layout=LAYOUTS.get(self.track_map.layout_id,{}) if self.track_map.bound else {}
            self.sessions.meta.update(track=layout.get('track',''),layout=layout.get('name',''),direction=layout.get('direction','unknown'),recognized_layout_id=self.track_map.layout_id if self.track_map.bound else '')
            self.sessions.persist()
        if restored:
            self.event('connection','Telemetry connected.' if self.received==1 else 'Telemetry restored.',2)
            self.bus.emit(TelemetryEvent(CONNECTION_CHANGED,{'state':'connected' if self.received==1 else 'restored'},now))
    def _on_frame_coaching(self,f):
        s=f.sample;v=s.values;active=bool(v.get('flags',0)&1) and not bool(v.get('flags',0)&6)
        tyre_result=self.tyre_heat.observe(s.mono,v.get('tyres'),v.get('speed_kmh'),active=active,locked=self.track.locked is not None,s=self.progress_s,layout_id=self.track.locked_layout_id) if self.feature('tyre_heat_rate') else None;self.tyre_heat_result=tyre_result
        if self.feature('spatial_coaching') and active and self.track.locked and self.progress_s is not None:
            if self.spatial_lap is None or self.spatial_lap.layout_id!=self.track.locked_layout_id:
                self.spatial_lap=SpatialLap(self.track.locked.length,self.track.locked_layout_id,v.get('car_id'));self._lap_start_mono=s.mono;self._lap_episodes=[]
            elapsed=s.mono-self._lap_start_mono
            self.spatial_lap.record(self.progress_s,elapsed,v.get('speed_kmh'),v.get('brake'),v.get('throttle'))
            episode=self.spatial_braking.observe(s.mono,self.progress_s,v.get('speed_kmh'),v.get('brake'),v.get('throttle'),v.get('lap'))
            if episode:self._lap_episodes.append(episode)
    def _on_frame_rules(self,f):
        s=f.sample;now=self.received_at
        was_in_pit=self.rules.was_inside_pit
        # Rules use source monotonic time; scheduler uses arrival monotonic time.
        for e in self.rules.evaluate(s,self.sessions.id,tyre_heat=self.tyre_heat_result):e.timestamp=now;self.scheduler.offer(e)
        if self.rules.was_inside_pit and not was_in_pit:self.bus.emit(TelemetryEvent(PIT_DETECTED,{'lap':s.values.get('lap')},now))
        lap=s.values['lap']
        if self.last_lap is not None and lap>self.last_lap:
            self.close_spatial_lap(lap)
            self.event('lap',f'Lap {lap}. Previous lap {((s.values.get("last_ms") or 0)/1000):.2f} seconds.',2)
            fuel=self.sessions.fuel()
            if fuel.get('margin_l') is not None and fuel['margin_l']<0:self.event('fuel_deficit',f'Estimated fuel deficit {abs(fuel["margin_l"]):.1f} litres. Save {fuel["save_percent"]:.0f} percent or plan a stop.',1,fuel)
            if fuel.get('confidence')=='moderate' and fuel.get('margin_l') is not None and fuel['margin_l']<0:
                scenarios=fuel_scenarios(fuel,self.sessions.report().get('laps',[]),reserve_l=self.settings.reserve_l,pit_loss_s=self.settings.pit_loss_s,refuel_rate_lps=self.settings.refuel_rate_lps,max_save_percent=self.settings.max_save_percent,fuel_time_slope_s_per_l=self.settings.fuel_time_slope_s_per_l)
                if scenarios['short'] and lap-self.fuel_alert_lap>=3 and (not self.fuel_alert_fired or scenarios['recommendation']!=self.fuel_alert_recommendation):
                    self.fuel_alert_fired=True;self.fuel_alert_lap=lap;self.fuel_alert_recommendation=scenarios['recommendation']
                    rec=next((b for b in scenarios['branches'] if b['id']==scenarios['recommendation']),None)
                    if rec:self.event('fuel_options',f"Fuel options available. {rec['text']}",1,scenarios)
            if self.box:self.event('box','Box this lap. Pit intent is marked.',1)
        self.last_lap=lap
    def close_spatial_lap(self,new_lap):
        """docs/AI_CONTEXT.md 8: finalize this lap's spatial trace, compare it
        against the reference lap for the same layout if one exists, and adopt
        it as the new reference if it's the fastest clean lap seen so far.
        A short/partial segment (car exited, layout changed mid-lap) isn't a
        fair basis for either role, so it's simply discarded, not compared."""
        completed=self.spatial_lap;self.spatial_lap=None
        if not self.feature('spatial_coaching'):self._lap_episodes=[];return
        episodes=self._lap_episodes;self._lap_episodes=[]
        if completed is None:return
        coverage=sum(0. if math.isnan(x) else 1. for x in completed.times)/len(completed.times)
        if coverage<.8:return
        finishing=next((t for t in reversed(completed.times) if not math.isnan(t)),None)
        if self.feature('gamification') and self.feature('corner_mastery') and self.sessions.laps:
            # Career references are session-local and quality-gated. Keep the
            # engineer's existing reference selection and behavior unchanged.
            try:
                from .gamification.mastery import capture_spatial
                from .track_catalogue import bundled_document
                if getattr(self,'_career_spatial_session',None)!=self.sessions.id:
                    self._career_spatial_session=self.sessions.id;self._career_spatial_reference=None
                closed=self.sessions.laps[-1]
                reference=getattr(self,'_career_spatial_reference',None)
                if closed.get('comparable') is True and closed.get('complete') is True:
                    if reference:
                        spatial=capture_spatial(completed,reference[0],(bundled_document(completed.layout_id) or {}).get('corners') or [],closed['id'],reference[1])
                        if spatial:self.bus.emit(TelemetryEvent('spatial_analysis_completed',{'session_id':self.sessions.id,'spatial':spatial},time.monotonic()))
                    if reference is None or (finishing is not None and finishing<reference[2]):
                        self._career_spatial_reference=(completed,closed['id'],finishing if finishing is not None else float('inf'))
            except Exception:
                logging.getLogger('gamification').exception('gamification.spatial_capture_failed')
        if self.spatial_reference and self.spatial_reference.layout_id==completed.layout_id:
            from .track_catalogue import bundled_document
            document=bundled_document(completed.layout_id);corners=(document or {}).get('corners') or []
            report=corner_report(completed,self.spatial_reference,corners,self.last_lap,episodes,self.spatial_reference_episodes)
            if report:
                self.coaching_result={'lap':self.last_lap,'reference_lap':self.spatial_reference_lap,'items':report,'method':'s-aligned v3'}
                top=report[0]
                if top['loss_s']>0 and top['confidence']!='low':self.event('coaching',top['text'],3,evidence=top)
        reference_finishing=next((t for t in reversed(self.spatial_reference.times) if not math.isnan(t)),None) if self.spatial_reference else None
        if finishing is not None and (self.spatial_reference is None or self.spatial_reference.layout_id!=completed.layout_id or (reference_finishing is not None and finishing<reference_finishing)):
            self.spatial_reference=completed;self.spatial_reference_episodes=episodes;self.spatial_reference_lap=self.last_lap
    def consume_track_service(self,s):
        # observe() self-throttles to ~5Hz internally (cheap early-return the rest of
        # the time), so calling it every sample is fine. The grid-search project()
        # call itself measures ~0.5-1.8ms on real geometry - too slow at 60Hz - so it
        # only runs at the same <=5Hz the recognizer already refreshes at (matching
        # it exactly wastes nothing: a faster outside rate wouldn't get fresher
        # recognizer output anyway). Samples in between advance s from measured
        # speed instead - the interpolation fallback the design doc anticipates.
        v=s.values;position=v.get('position');flags=v.get('flags') or 0;active=bool(flags&1) and not bool(flags&6)
        velocity=v.get('velocity');speed=(v.get('speed_kmh') or 0)/3.6
        if not self.feature('v3_track_authority'):self.progress_s=None;return
        was_locked=self.track.locked is not None;previous_layout=self.track.locked_layout_id
        self.track.observe(position,s.mono,speed=speed,velocity=velocity,lap=v.get('lap'),car_id=v.get('car_id'),provenance=s.provenance,active=active)
        if (self.track.locked is not None)!=was_locked or previous_layout!=self.track.locked_layout_id:self.bus.emit(TelemetryEvent(TRACK_LOCKED if self.track.locked is not None else TRACK_UNLOCKED,{'layout_id':self.track.locked_layout_id},s.mono))
        valid_position=active and position and len(position)==3 and position[0] is not None and position[2] is not None
        if not (self.track.locked and valid_position):
            self.progress_s=None;self._track_project_at=0.
        elif self.progress_s is not None and s.mono-self._track_project_at<.2:
            self.progress_s=(self.progress_s+speed*(s.mono-self._track_last_mono))%self.track.locked.length
        else:
            heading=math.atan2(velocity[2],velocity[0]) if velocity and math.hypot(velocity[0],velocity[2])>3 else None
            progress=self.track.project(position,heading=heading,previous_s=self.progress_s)
            if progress is not None:self.progress_s=progress.s
            self._track_project_at=s.mono
        self._track_last_mono=s.mono
    async def ai_loop(self):
        while self.running:
            if self.safe_mode:await asyncio.sleep(2);continue
            try:
                await self.local_ai.refresh(self,self.ai_refresh_requested)
                self.ai_refresh_requested=False
            except Exception as error:
                self.local_ai.result={'status':'unavailable','items':[],'reason':str(error)[:200]}
            await asyncio.sleep(2)
    async def track_loop(self):
        while self.running:
            try:
                await asyncio.to_thread(self.track_map.maintenance)
                key=self.track_map.layout_id
                if key:
                    await asyncio.to_thread(self.track_map.alignment,key)
                    from .tracks import LAYOUTS
                    if self.sessions.id and self.source=='live' and self.track_map.bound:
                        layout=LAYOUTS[key]
                        if self.sessions.meta.get('recognized_layout_id')!=key:
                            self.sessions.meta.update(track=layout['track'],layout=layout['name'],direction=layout['direction'],recognized_layout_id=key,map_revision=self.track_map.snapshot()['revision'])
                            self.sessions.persist()
                if hasattr(self,'group'):await self.group.sync_track_library()
            except Exception as error:self.track_map.error='Track worker: '+str(error)[:180]
            await asyncio.sleep(.5)
    def reset_driver_line(self,forget_layout=False):
        self.trace.clear()
        if forget_layout:self.track_map.leave()
        else:self.track_map.reset()
        self.live_delta=LiveDelta()
        self.spatial_lap=None;self.spatial_braking=LiveBrakingTracker();self._lap_episodes=[];self._lap_start_mono=None

    def record_driver_position(self,stale):
        v=self.sample.values
        p=v.get('position')
        if p and None not in p and not stale and v.get('flags',0)&1 and not v.get('flags',0)&6:
            self.trace.append([p[0],p[2],self.live_delta.result.get('trend',0)])

    async def engine_loop(self):
        last_history=0
        while self.running:
            now=time.monotonic();stale=self.received_at is None or now-self.received_at>self.settings.stale_seconds
            if self.mic_restart:
                await asyncio.to_thread(self.mic.close);self.mic_restart=False
            self.mic.set_suppressed(self.speaker.busy or now-self.speaker.finished<.6 or self.mic_testing)
            if not self.host_only and not self.safe_mode and self.settings.hands_free and not self.mic_testing and now-self.mic.last_attempt>30:
                self.mic.start_worker(self.settings)
            if self.sessions.id and self.received_at and now-self.received_at>self.settings.interrupt_seconds:
                self.sessions.end('interrupted');self.event('connection','Telemetry interrupted. An interrupted-session report is ready.',1);self.bus.emit(TelemetryEvent(CONNECTION_CHANGED,{'state':'interrupted'},now))
                self.sessions.manual_ended=False
                self.reset_driver_line()
            if stale and self.received_at and not getattr(self,'stale_warned',False):
                self.event('connection','Telemetry is stale. Current readings are unavailable.',1);self.stale_warned=True;self.bus.emit(TelemetryEvent(CONNECTION_CHANGED,{'state':'stale'},now))
            if not stale:self.stale_warned=False
            for result in self.mic.poll():
                words=result.get('result',[]);confidence=sum(w.get('conf',0) for w in words)/len(words) if words else 0
                text=result.get('text','')
                if confidence>=self.settings.recognition_confidence and intent(text)[0]!='unknown':self.command(text)
                elif text and not self.settings.hands_free:self.event('answer','Command unclear. Please repeat or use a control.',1,requested=True)
            workload=bool(self.sample and (self.sample.values['brake']>.15 or abs((self.sample.values.get('angular_velocity') or [0,0,0])[1] or 0)>.3))
            if self.scheduler.pending and any(e.priority==0 for e in self.scheduler.pending) and self.speaker.busy and self.speaker.priority>0:self.speaker.stop()
            if getattr(self,'active_speech',None) and not self.speaker.busy:
                e=self.active_speech;self.active_speech=None
                self.scheduler.log(e,'suppressed' if self.speaker.cancelled.is_set() or self.speaker.error else 'spoken',self.speaker.error or ('Playback interrupted' if self.speaker.cancelled.is_set() else 'Audio worker completed'))
            if not self.host_only and not self.speaker.busy and not self.mic_testing and (self.settings.hands_free or self.mic.state not in ('listening','loading')):
                event=self.scheduler.next(now,self.sessions.id,workload,stale)
                if event:
                    if self.settings.speech_enabled:
                        self.mic.set_suppressed(True)
                        accepted=self.speaker.speak(event.message,self.settings,event.priority)
                        if accepted:self.active_speech=event
                        self.scheduler.log(event,'output_started' if accepted else 'suppressed','Audio worker' if accepted else 'Audio busy')
                    else:self.scheduler.log(event,'subtitle','Audio output disabled')
            if now-last_history>=.1 and self.sample:
                last_history=now;v=self.sample.values
                self.history.append({'t':now,'speed':v['speed_kmh'],'throttle':v['throttle']*100,'brake':v['brake']*100,'clutch':(v.get('clutch') or 0)*100})
                self.record_driver_position(stale)
            await asyncio.sleep(.05)
    async def health_loop(self):
        prev=time.monotonic();packets=self.received;cpu=time.process_time()
        while self.running:
            await asyncio.sleep(1);now=time.monotonic();dt=now-prev;self.loop_lag=max(0,dt-1)
            disk=await asyncio.to_thread(shutil.disk_usage,self.config.root);store=self.store.health();thermal=None
            try:thermal=float(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
            except (OSError,ValueError):pass
            rss=None
            try:
                import resource
                rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
            except ImportError:pass
            busy=store['queue']>4096 or self.loop_lag>.2 or (thermal is not None and thermal>80)
            if busy:
                self.bad_since=self.bad_since or now;self.good_since=None
                if now-self.bad_since>3:self.degraded=True
            else:
                self.good_since=self.good_since or now;self.bad_since=None
                if now-self.good_since>20:self.degraded=False
            self.health_cache={'rate_hz':(self.received-packets)/dt,'cpu_percent_one_core':(time.process_time()-cpu)/dt*100,'peak_rss_bytes':rss,'thermal_c':thermal,'free_bytes':disk.free,'loop_lag_ms':self.loop_lag*1000,'storage':store,'network':self.seq.counts,'parse_errors':self.parse_errors,'unexpected_senders':self.unexpected,'pipeline_errors':self.pipeline_errors,'receiver':self.receiver,'clients':self.clients,'degraded':self.degraded,'reason':'Storage backlog, loop lag or thermal pressure' if self.degraded else None,'platform':platform.platform(),'architecture':platform.machine(),'python':platform.python_version()}
            if (store['error'] or store['application_drops'] or store['failed_rows']) and not getattr(self,'warned_storage',False):self.event('recording','Recording failure. Check diagnostics; live telemetry is still available.',1);self.warned_storage=True
            if disk.free<500*1024*1024 and not getattr(self,'warned_disk',False):self.event('disk','Storage space is low. Check recording storage.',1);self.warned_disk=True
            self.refresh_services()
            prev=now;packets=self.received;cpu=time.process_time()
    def snapshot(self):
        age=time.monotonic()-self.received_at if self.received_at else None
        stale=age is None or age>self.settings.stale_seconds
        return {'host_only':self.host_only,'recovery_notice':getattr(self.config,'recovery_notice',None),'track_selection':{'layout_id':self.track_map.layout_id,'name':LAYOUTS.get(self.track_map.layout_id,{}).get('name'),'status':self.track_map.status},'local_ai':self.local_ai.result,'car':identify(self.sample.values.get('car_id') if self.sample else None),'live_delta':dict(self.live_delta.result,stale=stale),'race_flags':{'available':False,'reason':'Not transmitted by GT7 UDP'},'reception_test':self.reception_test.snapshot(time.monotonic(),self.test_counters(),self.source_generation) if self.reception_test else None,'live_analysis':dict(self.live_analysis.result,stale=stale),'sample':self.sample.json() if self.sample else None,'source':self.source,'stale':stale,'age_ms':age*1000 if age is not None else None,'status':'disconnected' if stale and self.sessions.id else self.sessions.status,'session_id':self.sessions.id,'report':self.sessions.report() if self.sessions.id else self.sessions.last_report,'fuel':self.sessions.fuel() if self.sessions.id else None,'subtitle':self.scheduler.last_text,'events':list(self.events)[:20],'health':self.health_cache,'socket_error':self.socket_error,'receiver':self.receiver,'audio':{'hands_free':self.settings.hands_free,'input_device':self.mic.input_name,'input_rate':self.mic.sample_rate,'delivery':self.speaker.status(),'enabled':self.settings.speech_enabled,'speaking':self.speaker.busy,'error':self.speaker.error,'microphone':self.mic.state,'mic_error':self.mic.error,'level':self.mic.level,'clipping':self.mic.clipping,'muted':self.settings.hard_mute,'transcript':self.transcript},'trace':list(self.trace),'history':list(self.history),'box':self.box,'training':self.training.status(),'track':self.track.snapshot(self.progress_s),'tyre_heat':dict(self.tyre_heat_result,stale=stale) if self.tyre_heat_result else None,'coaching':self.coaching_result,'replay':{'paused':self.replay_paused,'speed':self.replay_speed,'cursor':self.replay_cursor},'services':self.services_cache,'derived':self.derived_values,'safe_mode':self.safe_mode.to_public() if self.safe_mode else None,'alerts':self.alerts.to_public()[:20]}
    def test_counters(self):
        return dict(self.seq.counts,parse_errors=self.parse_errors,pipeline_errors=self.pipeline_errors,unexpected_senders=self.unexpected,storage_drops=self.store.drops,storage_failures=self.store.failed_rows)
    def start_reception_test(self):
        self.reception_test=ReceptionTest(time.monotonic(),self.test_counters(),self.source_generation)
    def switch(self,source):
        self.live_analysis=LiveAnalysis();self.live_delta=LiveDelta();self.derived.reset();self.derived_values={};self._scenario_iter=None
        self.source_generation+=1
        self.sessions.end('interrupted');self.scheduler.cancel('Source changed');self.speaker.stop();self.sessions.manual_ended=False;self.seq=Sequence();self.source=source;self.track_map.select(self.settings.track_id,force=True,manual=False);self.track.reset();self.progress_s=None;self._track_project_at=0.;self._track_last_mono=0.;self.tyre_heat.reset();self.spatial_lap=None;self.spatial_reference=None;self.spatial_braking=LiveBrakingTracker();self.spatial_reference_episodes=[];self.spatial_reference_lap=None;self._lap_episodes=[];self._lap_start_mono=None;self.coaching_result=None;self.fuel_alert_fired=False;self.fuel_alert_lap=-1e9;self.fuel_alert_recommendation=None;self.socket_error=None;self.demo_time=0;self.demo_index=0;self.sample=None;self.received_at=None;self.history.clear();self.trace.clear();self.last_lap=None;self.rules=Rules(self.settings);self._refresh_flags()
        self.bus.emit(TelemetryEvent(SOURCE_CHANGED,{'source':source},time.monotonic()))
    def update_settings(self,values):
        old_mic=tuple(getattr(self.settings,k) for k in ('hands_free','vosk_model','input_device','mic_rate'));old_scenario=self.settings.demo_scenario
        old_track=tuple(getattr(self.settings,k) for k in ('track','layout','direction'))
        old_network=tuple(str(getattr(self.settings,k)) for k in ('ps5_ip','udp_bind','udp_port','remote_port','variant'))
        settings=self.config.save(values)
        if settings.track_id!=self.settings.track_id:self.track_map.select(settings.track_id)
        self.settings=settings;self.scheduler.settings=settings;self._refresh_flags();self.performance_profile=resolve_performance_profile(settings.performance_profile)
        if old_mic!=tuple(getattr(settings,k) for k in ('hands_free','vosk_model','input_device','mic_rate')):
            self.mic_restart=True;self.mic.last_attempt=-1e30
        new_network=tuple(str(getattr(settings,k)) for k in ('ps5_ip','udp_bind','udp_port','remote_port','variant'))
        if old_network!=new_network and self.source=='live':self.switch('live')
        if old_track!=tuple(getattr(settings,k) for k in ('track','layout','direction')):self.live_delta=LiveDelta();self.trace.clear()
        if settings.hard_mute:self.speaker.stop();self.scheduler.cancel('Hard mute')
        if self.source=='demo' and old_scenario!=settings.demo_scenario:self.switch('demo')
        return settings
    def clean_air_advice(self):
        """docs/AI_CONTEXT.md §12: only when connected as a driver to a group that
        opted in to share_traffic_with_drivers - built entirely from that group's
        own published traffic/projection fields, never a guess at another car."""
        if not self.feature('clean_air_advice'):return None
        client=getattr(getattr(self,'group',None),'client',None);state=client.state if client else None
        if not state:return None
        traffic=state.get('traffic')
        if not traffic:return None
        own_id=client.joined['participant']['entry_id'];own=next((e for e in state.get('entries') or [] if e['entry_id']==own_id),None)
        if not own or own.get('D') is None:return None
        pit_loss_s=((state.get('projection') or {}).get('pit_loss_s'))
        layout=LAYOUTS.get(self.track_map.layout_id,{}) if self.track_map.bound else {};length_m=layout.get('length_m')
        if not length_m:return None
        f=self.sessions.fuel()
        if not f.get('available'):return None
        v=self.sample.values if self.sample else {};pace=lap_statistics(self.sessions.laps)['median_ms']
        if not pace or v.get('fuel') is None:return None
        return pit_advice(my_d=own['D'],my_lap_s=pace/1000,fuel_l=v.get('fuel'),capacity_l=v.get('fuel_capacity'),burn_l_per_lap=f.get('litres_per_lap'),reserve_l=self.settings.reserve_l,pit_loss_s=pit_loss_s,laps_left=f.get('laps_remaining'),length_m=length_m,traffic=traffic)
    def command(self,text):
        action,arg=intent(text)
        if self.settings.retain_transcripts:self.transcript=text
        return self.execute(action,arg)
    def spoken(self,value,unit_word,digits):
        """'42.3 litres' / '11.2 US gallons' per Settings.units (default units: byte-identical to the old phrasing)."""
        number,word=spoken_measure(value,unit_word,self.settings.units)
        return f'{number:.{digits}f} {word}'
    def execute(self,action,arg=None):
        """Run an already-parsed engineer intent (voice/text `command()` and the engineer.* commands share this)."""
        v=self.sample.values if self.sample else {};f=self.sessions.fuel();report=self.sessions.report() if self.sessions.id else self.sessions.last_report or {};answer='That value is unavailable from the current telemetry.';navigate=None
        if action=='radio':answer='Radio check. Engineer is ready.'
        elif action=='status':answer=f'{self.sessions.status}. '+(self.spoken(v['speed_kmh'],'kilometres per hour',0)+'.' if v.get('speed_kmh') is not None else 'No fresh speed available.')
        elif action=='fuel' and v.get('fuel') is not None:answer=self.spoken(v['fuel'],'litres',1)+' remaining.'
        elif action in ('finish','save','pit','fuel_options'):
            deficit=f.get('margin_l') is not None and f['margin_l']<0
            if action=='fuel_options' or deficit:
                scenarios=fuel_scenarios(f,report.get('laps',[]),reserve_l=self.settings.reserve_l,pit_loss_s=self.settings.pit_loss_s,refuel_rate_lps=self.settings.refuel_rate_lps,max_save_percent=self.settings.max_save_percent,fuel_time_slope_s_per_l=self.settings.fuel_time_slope_s_per_l)
                if not scenarios['short']:answer=scenarios['summary'] or f.get('reason','Set race distance or duration; finish prediction is uncertain.')
                else:
                    options=[b['text'] for b in scenarios['branches'][:2]];rec=next((b for b in scenarios['branches'] if b['id']==scenarios['recommendation']),None)
                    answer=f"You're {scenarios['deficit_l']:.1f} litres short. "+' '.join(f'Option {i+1}: {t}' for i,t in enumerate(options))
                    if rec:answer+=f" {rec['id'].capitalize()} is quicker."
            elif f.get('margin_l') is not None:answer=f'Estimated finish margin {f["margin_l"]:.1f} litres. Fuel saving target {f["save_percent"]:.0f} percent.'
            else:answer=f.get('reason','Set race distance or duration; finish prediction is uncertain.')
            if action=='pit':
                advice=self.clean_air_advice()
                if advice and advice.get('available') and advice.get('text'):answer+=' '+advice['text']
        elif action=='box':self.box=True;answer='Box this lap marked.'
        elif action=='unbox':
            self.box=False
            for pending in self.scheduler.pending[:]:
                if pending.category=='box':
                    self.scheduler.pending.remove(pending);self.scheduler.log(pending,'suppressed','Pit intent cleared')
            if getattr(self,'active_speech',None) and self.active_speech.category=='box':self.speaker.stop()
            answer='Pit intent cleared. Stay out.'
        elif action in ('last','best') and v.get(action+'_ms') is not None:answer=f'{action.capitalize()} lap {v[action+"_ms"]/1000:.2f} seconds.'
        elif action=='tyres':answer='Tyre surface temperatures: '+', '.join('unavailable' if t is None else f'{spoken_measure(t,"degrees Celsius",self.settings.units)[0]:.0f}' for t in v.get('tyres',[None]*4))+('' if self.settings.units.temperature=='C' else ' degrees Fahrenheit')+'. Wear and pressures are unavailable.'
        elif action=='loss':
            navigate='Analysis'
            if self.coaching_result and self.coaching_result.get('items'):answer=self.coaching_result['items'][0]['text']
            else:answer=' '.join(x['observation'] for x in report.get('improvements',[])) or 'Not enough repeated comparable evidence yet.'
        elif action=='corner_report':
            items=(self.coaching_result or {}).get('items') or [];navigate='Analysis';match=None
            if arg and arg.isdigit():match=next((i for i in items if i['corner'].strip().lower()==f'turn {arg}'),None)
            elif arg:match=next((i for i in items if arg.lower() in i['corner'].lower()),None)
            answer=match['text'] if match else 'No coaching evidence for that corner from your last completed lap.'
        elif action=='compare_braking':
            items=[i for i in (self.coaching_result or {}).get('items') or [] if any(k=='onset' for k,_ in i.get('causes',[]))];navigate='Analysis'
            answer=items[0]['text'] if items else 'No braking-onset difference from your reference exceeded the threshold on your last completed lap.'
        elif action=='lap_summary':
            laps=report.get('laps',[]);navigate='Analysis'
            if laps:
                lap=laps[-1];duration=lap.get('duration_ms');answer=f'Lap {lap.get("number")}: '+(f'{duration/1000:.3f} seconds. ' if duration else 'Timing unavailable. ')+f'Coasting {lap.get("coast_s",0):.1f} seconds, pedal overlap {lap.get("overlap_s",0):.1f} seconds. '+('Comparable by application checks.' if lap.get('comparable') else 'Excluded from comparable-lap analysis.')
            else:answer='Complete a lap before requesting its summary.'
        elif action=='compare':
            laps=[lap for lap in report.get('laps',[]) if lap.get('comparable') and lap.get('duration_ms')];navigate='Analysis'
            if len(laps)>=2:answer=f'Latest comparable lap is {(laps[-1]["duration_ms"]-min(lap["duration_ms"] for lap in laps[:-1]))/1000:+.3f} seconds against your previous best comparable lap.'
            else:answer='I need two comparable completed laps for that comparison.'
        elif action=='reference':answer='Last clean lap queued as the live reference from your next lap.' if self.live_delta.select_last_reference() else 'The last completed lap must pass position and continuity checks before it can become a live reference.'
        elif action in ('corner','incident','note'):
            self.decision({'category':'annotation','message':arg or action,'position':v.get('position'),'session':self.sessions.id,'decision':'saved','reason':'User marked','priority':2});answer='Marker saved.'
        elif action=='target':self.update_settings({**self.settings.model_dump(), 'target_ms':arg});answer=f'Target set to {arg/1000:.2f} seconds.'
        elif action.startswith('show_'):navigate={'show_live':'Live Race','show_analysis':'Analysis','show_strategy':'Strategy'}[action];answer=f'Showing {navigate}.'
        elif action=='repeat':answer=self.last_answer or self.scheduler.last_text or 'Nothing to repeat.'
        elif action in ('less','more','mute','resume'):
            changes={'less':{'mode':'Quiet'},'more':{'mode':'Detailed'},'mute':{'hard_mute':True},'resume':{'hard_mute':False,'speech_enabled':True,'mode':'Normal'}}[action];self.update_settings({**self.settings.model_dump(),**changes});answer='Engineer settings updated.'
        elif action=='quiet':self.scheduler.quiet_until=time.monotonic()+120;answer='Quiet for two minutes. Critical alerts remain enabled.'
        elif action=='stop':
            self.speaker.stop();self.scheduler.cancel();answer,variation=engineer_answer(self,action,'Stopped.');return {'answer':answer,'intent':action,'variation':variation}
        elif action=='end':self.sessions.end();self.scheduler.cancel('Session ended');self.speaker.stop();navigate='Analysis';answer='Session ended. Your report is ready.'
        elif action=='unknown':answer='Command unclear. Please use an exact command or the controls.'
        if action=='delta' and self.live_delta.result.get('available'):answer=f'Estimated delta {self.live_delta.result["delta_s"]:+.3f} seconds to the active clean recorded reference.'
        if self.received_at is None or time.monotonic()-self.received_at>self.settings.stale_seconds:
            if action in ('status','fuel','finish','save','pit','tyres','delta'):answer='Telemetry is stale or unavailable. I cannot give a current reading.'
        answer,variation=engineer_answer(self,action,answer)
        if action!='repeat':self.last_answer=answer
        self.event('answer',answer,1,requested=True)
        return {'answer':answer,'navigate':navigate,'intent':action,'variation':variation}
