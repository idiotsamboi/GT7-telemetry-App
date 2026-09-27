"""Bounded telemetry briefs with optional offline, evidence-only model ranking.
No model output can invent a metric, change settings, or create a race alert.
"""
import asyncio,json,math,os,secrets,socket,subprocess,time,urllib.request,threading
from pathlib import Path

def memory_available_mb():
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):return int(line.split()[1])/1024
    except OSError:pass
    return None

def evidence(runtime):
    """Reduce existing aggregates, never rescan raw telemetry or recordings."""
    sample=runtime.sample
    if not sample or runtime.received_at is None or time.monotonic()-runtime.received_at>runtime.settings.stale_seconds:
        return {'available':False,'reason':'Fresh telemetry is required','items':[]}
    v=sample.values
    if not v.get('flags',0)&1 or v.get('flags',0)&6:
        return {'available':False,'reason':'Resume driving to build a current brief','items':[]}
    items=[]
    def add(key,text,priority=2):items.append({'id':key,'text':text,'priority':priority})
    def number(x):return isinstance(x,(int,float)) and math.isfinite(x)
    a=runtime.live_analysis.result
    if a.get('available') and a.get('window_s',0)>=5:
        window=a['window_s']
        overlap=a.get('overlap_percent');coast=a.get('coast_percent')
        if number(overlap) and overlap>=10:add('overlap',f'Pedal overlap occupied {overlap:.0f}% of the last {window:.0f} seconds. Review whether simultaneous throttle and brake was intentional.')
        if number(coast) and coast>=15:add('coast',f'Coasting occupied {coast:.0f}% of the last {window:.0f} seconds. Compare those sections with a clean reference before changing technique.')
        spread=a.get('tyre_spread_c')
        if number(spread) and spread>=runtime.settings.tyre_imbalance_c:add('tyres',f'Tyre surface temperature spread is {spread:.0f} degrees Celsius. Check corner loads; this does not establish wear or grip.')
    laps=[lap for lap in runtime.sessions.laps[-12:] if lap.get('comparable') and number(lap.get('duration_ms'))]
    if len(laps)>=2:
        change=(laps[-1]['duration_ms']-min(lap['duration_ms'] for lap in laps[:-1]))/1000
        add('pace',f'Latest comparable lap is {abs(change):.3f} seconds '+('slower' if change>0 else 'faster')+' than the previous best among the last twelve recorded laps.')
    fuel=runtime.sessions.fuel()
    if fuel.get('available') and number(fuel.get('margin_l')) and fuel['margin_l']<0:
        add('fuel',f'Estimated fuel deficit is {abs(fuel["margin_l"]):.1f} litres under your configured race assumptions. Review the fuel strategy.',0)
    if number(v.get('fuel')) and (v.get('fuel_capacity') or 0)>0 and v['fuel']<runtime.settings.low_fuel_l:
        add('low_fuel',f'Fuel remaining is {v["fuel"]:.1f} litres, below your configured low-fuel threshold.',0)
    if sample.quality:add('quality','Current telemetry has quality flags. Treat derived comparisons cautiously.',0)
    if runtime.box:add('pit','Pit intent is marked. Use Unmark pit intent if you decide to stay out.',1)
    if not items:add('learning','No supported coaching pattern stands out yet. Record more clean laps for a useful comparison.',3)
    return {'available':True,'source':runtime.source,'lap':v.get('lap'),'window_s':a.get('window_s',0),'items':items[:8]}

def selected_items(brief,selected=None):
    by_id={x['id']:x for x in brief['items']}
    chosen=[x['id'] for x in brief['items'] if x['priority']==0]
    for key in selected or []:
        if key in by_id and key not in chosen:chosen.append(key)
    for item in sorted(brief['items'],key=lambda x:x['priority']):
        if item['id'] not in chosen:chosen.append(item['id'])
    return [by_id[key] for key in chosen[:3]]

class LocalAI:
    def __init__(self):
        self.process=None;self.log=None;self.key=secrets.token_urlsafe(24);self.last_request=-1e30;self.task=None
        self.result={'status':'waiting','items':[],'engine':'Evidence summary','reason':'Waiting for telemetry'}
        self.generation=0;self.signature=None
        self.lock=threading.Lock()
    def stop(self):
        with self.lock:
            self.generation+=1
            if self.process:
                self.process.terminate()
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
            self.process=None
            if self.log:self.log.close();self.log=None
    def pressure(self,runtime):
        free=memory_available_mb();thermal=runtime.health_cache.get('thermal_c')
        if free is not None and free<512:return 'Low available memory'
        if thermal is not None and thermal>=75:return 'Board temperature is high'
        if runtime.degraded or runtime.health_cache.get('loop_lag_ms',0)>100:return 'Telemetry processing has priority'
        if self.process and os.name!='nt':
            try:
                for line in Path(f'/proc/{self.process.pid}/status').read_text().splitlines():
                    if line.startswith('VmRSS:') and int(line.split()[1])>1200*1024:return 'Local model exceeded the 1200 MB resident-memory budget'
            except OSError:pass
        return None
    def _request(self,port,path,body=None,timeout=2):
        # Numeric loopback only, no proxies or redirects to external services.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        request=urllib.request.Request(f'http://127.0.0.1:{port}{path}',data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Authorization':'Bearer '+self.key})
        with opener.open(request,timeout=timeout) as response:
            data=response.read(65537)
            if len(data)>65536:raise ValueError('Local model response exceeded limit')
            return json.loads(data)
    def _start(self,settings,root,generation):
        if self.process and self.process.poll() is None:return
        binary=Path(settings.local_ai_binary);model=Path(settings.local_ai_model)
        if not binary.is_file() or not model.is_file():raise RuntimeError('Install the local AI model and select llama-server in Settings')
        free=memory_available_mb()
        if free is not None and free<1100:raise RuntimeError('Need at least 1100 MB available before loading the model')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',settings.local_ai_port))
        command=[str(binary.resolve()),'--model',str(model.resolve()),'--host','127.0.0.1','--port',str(settings.local_ai_port),'--api-key',self.key,'--ctx-size','1536','--threads','2','--threads-batch','2','--parallel','1','--batch-size','128','--ubatch-size','64','--n-gpu-layers','0','--no-webui','--offline','--cache-ram','0']
        with self.lock:
            if generation!=self.generation:raise RuntimeError('Local inference cancelled')
            self.log=(root/'local-ai.log').open('wb')
            self.process=subprocess.Popen(command,stdout=self.log,stderr=self.log,creationflags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=='nt' else 0)
            process=self.process
        if os.name!='nt':
            try:os.setpriority(os.PRIO_PROCESS,process.pid,10)
            except (AttributeError,OSError):pass
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if generation!=self.generation:raise RuntimeError('Local inference cancelled')
            if process.poll() is not None:raise RuntimeError('Local model failed to start; see local-ai.log')
            try:
                if self._request(settings.local_ai_port,'/health').get('status')=='ok':return
            except Exception:pass
            time.sleep(.2)
        raise RuntimeError('Local model startup timed out')
    def _rank(self,settings,root,brief,generation):
        self._start(settings,root,generation)
        options=[{'id':i['id'],'observation':i['text']} for i in brief['items']]
        schema={'type':'object','properties':{'selected':{'type':'array','items':{'type':'string','enum':[i['id'] for i in brief['items']]},'minItems':1,'maxItems':3}},'required':['selected'],'additionalProperties':False}
        payload={'messages':[{'role':'system','content':'Select up to three supplied observation IDs for a concise race engineer briefing. Prioritize fuel and quality issues, then actionable technique or pace. Return only JSON. Do not invent facts.'},{'role':'user','content':json.dumps(options,separators=(',',':'))}],'temperature':0,'seed':42,'max_tokens':48,'response_format':{'type':'json_schema','json_schema':{'name':'brief','strict':True,'schema':schema}}}
        response=self._request(settings.local_ai_port,'/v1/chat/completions',payload,timeout=45)
        answer=json.loads(response['choices'][0]['message']['content']);keys=answer['selected']
        if not isinstance(keys,list) or not 1<=len(keys)<=3 or any(not isinstance(k,str) or k not in {i['id'] for i in brief['items']} for k in keys):raise ValueError('Model returned unsupported evidence')
        return keys
    async def refresh(self,runtime,force=False):
        brief=evidence(runtime);now=time.monotonic()
        signature=(runtime.source_generation,runtime.sessions.id,(runtime.sample.values.get('car_id') if runtime.sample else None),(runtime.settings.track,runtime.settings.layout,runtime.settings.direction),runtime.settings.local_ai_enabled,runtime.settings.local_ai_model,runtime.settings.local_ai_binary,runtime.settings.local_ai_port)
        if self.signature is not None and self.signature!=signature:
            await asyncio.to_thread(self.stop);self.last_request=-1e30
        self.signature=signature
        base={'status':'ready' if brief['available'] else 'waiting','engine':'Evidence summary','items':selected_items(brief),'reason':brief.get('reason'),'lap':brief.get('lap'),'source':brief.get('source'),'generated_at':time.time(),'model_error':None}
        if not brief['available']:
            if self.process and now-self.last_request>120:await asyncio.to_thread(self.stop)
            self.result=base;return
        pressure=self.pressure(runtime)
        if pressure:
            self.result={**base,'reason':pressure}
            if self.process:await asyncio.to_thread(self.stop)
            return
        if self.task and not self.task.done():return
        if not force and now-self.last_request<runtime.settings.local_ai_interval:return
        self.last_request=now;self.result=base
        if pressure or not runtime.settings.local_ai_enabled:
            self.result['reason']=pressure or 'Local model disabled; calculated summary remains available'
            if self.process:await asyncio.to_thread(self.stop)
            return
        if len(brief['items'])<2:
            self.result['reason']='A single supported observation does not need model inference';return
        generation=self.generation
        async def work():
            start=time.perf_counter()
            try:
                keys=await asyncio.to_thread(self._rank,runtime.settings,runtime.config.root,brief,generation)
                current=evidence(runtime)
                if generation!=self.generation or signature!=self.signature or not current['available']:return
                # Revalidate selected IDs against the latest facts, never display stale values.
                self.result={**base,'items':selected_items(current,keys),'engine':'Qwen 0.5B · local CPU','inference_ms':round((time.perf_counter()-start)*1000),'generated_at':time.time(),'lap':current.get('lap')}
            except Exception as error:
                if generation==self.generation:self.result={**base,'model_error':str(error)[:250],'reason':'Using calculated evidence summary'}
                await asyncio.to_thread(self.stop)
        self.result={**base,'status':'thinking'};self.task=asyncio.create_task(work())
    async def close(self):
        await asyncio.to_thread(self.stop)
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
