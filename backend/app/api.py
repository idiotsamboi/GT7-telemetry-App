import asyncio,json,os,time,uuid,secrets,sqlite3
from datetime import datetime,timezone,timedelta
from typing import Literal
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI,Request,WebSocket,HTTPException
from fastapi.responses import JSONResponse,FileResponse,HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .config import Config,Settings
from .tracks import CATALOG as TRACKS,LAYOUTS
from .storage import Store
from .runtime import Runtime
from .telemetry import CAPABILITIES,UNSUPPORTED,UPSTREAM
from .engineer import RULES
from .voice import audio_devices,audio_probe
from .analytics import downsample,approximate_compare,align_laps,braking_episodes,lap_statistics,improvements
from .exporting import export_bundle,report_html,inspect_bundle

ROOT=Path(__file__).resolve().parents[2]

def create_app(data_dir=None):
    cfg=Config(data_dir or os.environ.get('GT7_DATA',ROOT/'data'));runtime=None
    @asynccontextmanager
    async def lifespan(app):
        nonlocal runtime
        # A lock socket prevents multiple HTTP workers from creating duplicate owners.
        import socket
        lock=socket.socket()
        try:lock.bind(('127.0.0.1',cfg.settings.http_port+1 if cfg.settings.http_port<65535 else 65534))
        except OSError:raise RuntimeError('Another GT7 instance owns the single-receiver lock. Use one Uvicorn worker.')
        store=Store(cfg.root/'telemetry.sqlite3');runtime=Runtime(cfg,store);app.state.runtime=runtime
        await runtime.start()
        if os.environ.get("GT7_DEMO")=="1":runtime.switch("demo")
        try:yield
        finally:await runtime.close();lock.close()
    app=FastAPI(title='GT7 Race Engineer',lifespan=lifespan,docs_url=None,redoc_url=None)
    from .group.admin import router as group_router
    from pydantic import ValidationError
    app.include_router(group_router())
    @app.exception_handler(ValidationError)
    async def invalid_group_request(request,error):return JSONResponse({'detail':'Invalid request: '+str(error)[:400]},422)
    def origin_ok(origin):return origin in cfg.settings.allowed_origins
    def token_ok(token):return bool(token) and secrets.compare_digest(token,cfg.token)
    @app.middleware('http')
    async def guard(request,call_next):
        if request.headers.get('content-length','0').isdigit() and int(request.headers.get('content-length','0'))>34*1024*1024:return JSONResponse({'detail':'Request too large'},413)
        origin=request.headers.get('origin')
        host=request.url.hostname
        allowed={'127.0.0.1','localhost','::1'}|{urlparse(x).hostname for x in cfg.settings.allowed_origins}
        if host not in allowed:return JSONResponse({'detail':'Host not configured'},403)
        if origin and not origin_ok(origin):return JSONResponse({'detail':'Origin not allowed'},403)
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/pair'):
            if not token_ok(request.headers.get('x-control-token') or request.cookies.get('gt7_token')):return JSONResponse({'detail':'Pair this browser first'},401)
        result=await call_next(request)
        result.headers['X-Content-Type-Options']='nosniff';result.headers['Referrer-Policy']='no-referrer';result.headers['Cache-Control']='no-store' if request.url.path.startswith('/api') else 'no-cache'
        result.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return result
    @app.get('/api/health')
    def health():return {'ok':True,'service':'GT7 Race Engineer'}
    @app.post('/api/pair')
    async def pair(request:Request):
        body=await request.json()
        local=request.client and request.client.host in ('127.0.0.1','::1','testclient') and request.url.hostname in ('127.0.0.1','localhost','::1')
        if not local and not token_ok(body.get('token')):raise HTTPException(403,'Enter pairing token from the Orange Pi data/control-token file')
        response=JSONResponse({'paired':True});response.set_cookie('gt7_token',cfg.token,httponly=True,samesite='strict',secure=request.url.scheme=='https');return response
    @app.get('/api/state')
    def state():return runtime.snapshot()
    @app.get('/api/settings')
    def settings():return cfg.settings.model_dump(mode='json')
    @app.put('/api/settings')
    async def save_settings(settings:Settings):
        if settings.track_id:
            layout=LAYOUTS.get(settings.track_id)
            if not layout:raise HTTPException(422,'Unknown GT7 layout')
            settings.track=layout['track'];settings.layout=layout['name'];settings.direction=layout['direction']
        runtime.update_settings(settings.model_dump());return {'settings':settings.model_dump(mode='json'),'restart_required':'Console/UDP changes reconnect immediately. HTTP listen/origin changes need restart; audio device changes need microphone reinitialization.'}
    @app.get('/api/tracks')
    def tracks():return TRACKS
    @app.get('/api/track-map')
    def track_map():return runtime.track_map.snapshot()
    class MapImport(BaseModel):
        layout_id:str=Field(max_length=16)
        points:list=Field(max_length=4096)
    @app.put('/api/track-map')
    async def import_map(body:MapImport):
        try:await asyncio.to_thread(runtime.track_map.import_map,body.layout_id,body.points)
        except ValueError as e:raise HTTPException(422,str(e))
        return runtime.track_map.snapshot()
    class MapSelection(BaseModel):
        layout_id:str=Field(max_length=16)
    @app.post('/api/track-map/select')
    async def select_map(body:MapSelection):
        try:runtime.track_map.select(body.layout_id,force=True)
        except ValueError as error:raise HTTPException(422,str(error))
        await asyncio.to_thread(runtime.track_map.alignment,body.layout_id)
        return runtime.track_map.snapshot()
    class MapConfirmation(BaseModel):
        layout_id:str=Field(max_length=16)
        candidate_id:str=Field(max_length=64)
    class MapRestore(BaseModel):
        layout_id:str=Field(max_length=16)
        revision:str=Field(max_length=64)
    @app.get('/api/track-map/library')
    def map_library():
        from .tracks import LAYOUTS,REFERENCES
        return {'layouts':[{'layout_id':key,'name':LAYOUTS[key]['name'],'revision':v['revision'],'kind':v['kind'],'updated':v.get('updated'),'versions':[{'revision':r['revision'],'updated':r.get('updated')} for r in v.get('versions',[])]} for key,v in list(runtime.track_map.library.items())], 'reference_coverage':{key:v.get('status','unavailable') for key,v in REFERENCES.items()}}
    @app.post('/api/track-map/confirm')
    async def confirm_map(body:MapConfirmation):
        try:return await asyncio.to_thread(runtime.track_map.confirm,body.candidate_id,body.layout_id)
        except ValueError as error:raise HTTPException(422,str(error))
        except OSError:raise HTTPException(503,'Map could not be saved; previous revision remains available')
    @app.post('/api/track-map/restore')
    async def restore_map(body:MapRestore):
        try:return await asyncio.to_thread(runtime.track_map.restore,body.layout_id,body.revision)
        except ValueError as error:raise HTTPException(422,str(error))
        except OSError:raise HTTPException(503,'Map could not be restored; previous revision remains available')
    @app.get('/api/capabilities')
    def capabilities():return {'fields':CAPABILITIES,'unsupported':UNSUPPORTED,'rules':RULES,'upstream':UPSTREAM}
    class Command(BaseModel):text:str=Field(max_length=500)
    @app.post('/api/command')
    async def command(body:Command):return runtime.command(body.text)
    @app.get('/api/engineer/requests')
    async def engineer_requests():
        from .requests import public_catalog
        return {'count':100,'requests':public_catalog()}
    class Control(BaseModel):action:str=Field(max_length=40);value:str|float|None=None
    @app.post('/api/control')
    async def control(body:Control):
        action=body.action
        if action in ('demo','live'):runtime.switch(action)
        elif action=='ai_briefing':runtime.ai_refresh_requested=True
        elif action=='telemetry_test':
            if runtime.source!='live':raise HTTPException(400,'Select live PS5 telemetry before testing')
            runtime.start_reception_test()
        elif action=='reconnect':runtime.switch('live')
        elif action=='start':runtime.sessions.manual_ended=False
        elif action=='end':return runtime.command('end session')
        elif action=='stop':return runtime.command('stop talking')
        elif action=='mute':return runtime.command('mute')
        elif action=='resume':return runtime.command('resume engineer')
        elif action=='speaker_test':
            runtime.scheduler.cancel('Speaker test');runtime.speaker.stop()
            if runtime.speaker.thread:await asyncio.to_thread(runtime.speaker.thread.join,3)
            if runtime.speaker.busy:raise HTTPException(409,'Previous speech is still stopping. Try again shortly.')
            runtime.update_settings({**runtime.settings.model_dump(),'speech_enabled':True,'hard_mute':False,'voice_volume':runtime.settings.voice_volume or 80})
            runtime.mic.set_suppressed(True)
            runtime.speaker.speak('Radio check. This is your GT7 race engineer speaking through the selected output device.',runtime.settings,1)
            return {'ok':True,'message':'Speaker test started. Spoken output is now enabled.'}
        elif action in ('audio_test','calibrate'):
            if runtime.mic_testing:raise HTTPException(409,'An audio test is already running')
            runtime.mic_testing=True
            try:
                runtime.speaker.stop();runtime.scheduler.cancel('Audio test');await asyncio.to_thread(runtime.mic.close)
                return await asyncio.to_thread(audio_probe,runtime.settings,action=='audio_test')
            finally:runtime.mic_testing=False;runtime.mic.last_attempt=-1e30
        elif action in ('listen_on','listen_off'):
            runtime.update_settings({**runtime.settings.model_dump(),'hands_free':action=='listen_on'})
        elif action=='mic_enable':runtime.mic.start_worker(runtime.settings)
        elif action=='ptt_start':
            if runtime.mic_testing:raise HTTPException(409,'Wait for the audio test to finish')
            runtime.speaker.stop();runtime.scheduler.cancel('Push to talk');runtime.mic.start_worker(runtime.settings)
            await asyncio.sleep(.25);runtime.mic.control('start')
        elif action=='ptt_stop':runtime.mic.control('stop')
        elif action=='replay':
            sid=str(body.value)
            if not await asyncio.to_thread(runtime.store.detail,sid):raise HTTPException(404,'Session not found')
            runtime.switch('replay');runtime.replay=sid;runtime.replay_cursor=-1e30;runtime.replay_record_id=0;runtime.replay_last=None;runtime.replay_buffer.clear();runtime.replay_paused=False
        elif action=='replay_pause':runtime.replay_paused=not runtime.replay_paused
        elif action=='replay_speed':runtime.replay_speed=max(.25,min(16,float(body.value or 1)))
        elif action=='replay_seek':
            runtime.sessions.end('interrupted');runtime.sessions.manual_ended=False;runtime.scheduler.cancel('Replay seek');runtime.rules=type(runtime.rules)(runtime.settings);runtime.replay_cursor=float(body.value or 0);runtime.replay_record_id=0;runtime.replay_last=None;runtime.replay_buffer.clear();runtime.history.clear();runtime.reset_driver_line();runtime.last_lap=None
        else:raise HTTPException(400,'Unknown control')
        return {'ok':True}
    @app.get('/api/audio')
    async def audio():return await asyncio.to_thread(audio_devices)
    @app.get('/api/sessions')
    async def sessions(include_archived:bool=False):
        await asyncio.to_thread(runtime.store.flush)
        return await asyncio.to_thread(runtime.store.sessions,include_archived)
    @app.get('/api/sessions/{sid}')
    async def detail(sid:str):
        result=await asyncio.to_thread(runtime.store.detail,sid)
        if not result:raise HTTPException(404,'Session not found')
        return result
    @app.get('/api/sessions/{sid}/samples')
    async def samples(sid:str,after:float=-1e30,channel:str='speed_kmh',overview:bool=True):
        rows=await asyncio.to_thread(runtime.store.samples,sid,after,10000)
        return {'rows':downsample(rows,1200,channel) if overview else rows,'next':rows[-1]['mono'] if rows else None,'limit':10000,'more_possible':len(rows)==10000}
    @app.get('/api/sessions/{sid}/report')
    async def html_report(sid:str):
        detail=await asyncio.to_thread(runtime.store.detail,sid)
        if not detail:raise HTTPException(404,'Unknown session')
        return HTMLResponse(report_html(detail))
    class Metadata(BaseModel):
        notes:str=Field('',max_length=4000)
        tags:list[str]=Field(default_factory=list,max_length=20)
        protected:bool=False
        track:str|None=Field(None,max_length=120)
        layout:str|None=Field(None,max_length=120)
        direction:Literal['unknown','forward','reverse']|None=None
        reference_lap:str|None=None
    @app.put('/api/sessions/{sid}/metadata')
    async def metadata(sid:str,body:Metadata):
        detail=await asyncio.to_thread(runtime.store.detail,sid)
        if not detail:raise HTTPException(404,'Unknown session')
        meta={**detail['meta'],'notes':body.notes,'tags':[t[:60] for t in body.tags]}
        for key in ('track','layout','direction','reference_lap'):
            value=getattr(body,key)
            if value is not None:meta[key]=value
        if body.reference_lap and not any(l['id']==body.reference_lap and l['comparable'] for l in detail['laps']):raise HTTPException(422,'Reference must be a complete comparable lap')
        if sid==runtime.sessions.id:runtime.sessions.meta=meta
        if not runtime.store.put('metadata',(json.dumps(meta),int(body.protected),sid)):raise HTTPException(503,'Storage queue full')
        await asyncio.to_thread(runtime.store.flush)
        return {'ok':True}
    class Correction(BaseModel):
        status:Literal['completed','interrupted']|None=None
        lap_id:str|None=None
        exclude:bool=True
        reason:str=Field(min_length=1,max_length=300)
    @app.post('/api/sessions/{sid}/correct')
    async def correct(sid:str,body:Correction):
        detail=await asyncio.to_thread(runtime.store.detail,sid)
        if not detail:raise HTTPException(404,'Unknown session')
        if not detail['ended']:raise HTTPException(409,'End the session before correcting it')
        if body.lap_id:
            lap=next((l for l in detail['laps'] if l['id']==body.lap_id),None)
            if not lap:raise HTTPException(404,'Unknown lap')
            lap['user_excluded']=body.exclude
            lap['user_correction']=body.reason
            lap['comparable']=bool(not body.exclude and lap['complete'] and not lap['partial'] and not lap['quality'] and not lap['refuel'])
            runtime.store.put('lap',(lap['id'],sid,json.dumps(lap)))
        report=detail['report'] or {}
        status=body.status or detail['status']
        report.update({'status':status,'laps':detail['laps'],'pace':lap_statistics(detail['laps']),'improvements':improvements(detail['laps']),'user_correction':body.reason,'official_validity':'unknown'})
        runtime.store.put('correct',(status,json.dumps(report),sid))
        runtime.decision({'session':sid,'category':'manual correction','message':body.reason,'decision':'saved','reason':'User correction; official validity remains unknown','priority':2})
        await asyncio.to_thread(runtime.store.flush)
        return await asyncio.to_thread(runtime.store.detail,sid)
    class Archive(BaseModel):archived:bool=True
    @app.post('/api/sessions/{sid}/archive')
    async def archive(sid:str,body:Archive):
        detail=await asyncio.to_thread(runtime.store.detail,sid)
        if not detail:raise HTTPException(404,'Unknown session')
        if not detail['ended'] or (body.archived and detail['protected']):raise HTTPException(409,'Active or protected sessions cannot be archived')
        runtime.store.put('archive',(datetime.now(timezone.utc).isoformat() if body.archived else None,sid));await asyncio.to_thread(runtime.store.flush)
        return {'ok':True}
    @app.get('/api/retention')
    async def retention_preview():
        cutoff=(datetime.now(timezone.utc)-timedelta(days=cfg.settings.retention_days)).isoformat()
        return await asyncio.to_thread(runtime.store.query,'SELECT id,started,status,provenance FROM sessions WHERE ended IS NOT NULL AND ended<? AND protected=0 AND archived_at IS NULL ORDER BY started LIMIT 1000',(cutoff,))
    @app.post('/api/retention')
    async def retention_apply():
        rows=await retention_preview();stamp=datetime.now(timezone.utc).isoformat()
        for row in rows:runtime.store.put('archive',(stamp,row['id']))
        await asyncio.to_thread(runtime.store.flush)
        return {'archived':len(rows),'note':'Recoverable archive only. Purge requires a separate explicit action.'}
    class Purge(BaseModel):confirmation:Literal['DELETE ARCHIVED SESSION']
    @app.post('/api/sessions/{sid}/purge')
    async def purge(sid:str,body:Purge):
        if runtime.sessions.id:raise HTTPException(409,'End recording before disk cleanup')
        detail=await asyncio.to_thread(runtime.store.detail,sid)
        if not detail or not detail['ended'] or detail['protected'] or not detail['archived_at']:raise HTTPException(409,'Only archived, ended, unprotected sessions can be purged')
        runtime.store.put('purge',sid);await asyncio.to_thread(runtime.store.flush)
        return {'ok':True,'note':'Freed SQLite pages are reused. Vacuum only offline.'}
    @app.get('/api/sessions/{sid}/export')
    async def export(sid:str):
        if runtime.sessions.id:raise HTTPException(409,'End recording before creating a bundle')
        folder=cfg.root/'exports';folder.mkdir(exist_ok=True)
        if not await asyncio.to_thread(runtime.store.detail,sid):raise HTTPException(404,'Unknown session')
        path=await asyncio.to_thread(export_bundle,runtime.store,sid,folder);return FileResponse(path,filename='gt7-session.zip')
    @app.post('/api/import')
    async def import_session(request:Request):
        if runtime.sessions.id:raise HTTPException(409,'End recording before importing')
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>32*1024*1024:raise HTTPException(413,'Import too large')
        try:meta,rows=await asyncio.to_thread(inspect_bundle,bytes(data))
        except Exception as e:raise HTTPException(400,str(e))
        sid=uuid.uuid4().hex
        def write():
            runtime.store.put('session',(sid,meta['started'],meta.get('ended'),'imported','import',json.dumps(meta.get('meta',{})),json.dumps(meta.get('report'))))
            for lap in meta.get('laps',[]):runtime.store.put('lap',(uuid.uuid4().hex,sid,json.dumps(lap)))
            for r in rows:
                while runtime.store.q.qsize()>4000:time.sleep(.02)
                runtime.store.put('sample',(sid,r.get('lap_id'),r['mono'],r['values'].get('packet_id',0),json.dumps(r)))
            runtime.store.flush()
        await asyncio.to_thread(write);return {'id':sid}
    class Comparison(BaseModel):
        reference_session:str
        reference_lap:str
        candidate_session:str
        candidate_lap:str
    @app.post('/api/compare')
    async def compare(body:Comparison):
        def work():
            a=runtime.store.detail(body.reference_session);b=runtime.store.detail(body.candidate_session)
            if not a or not b:raise ValueError('Session not found')
            if a['provenance']!=b['provenance']:raise ValueError('Live/demo/replay provenance cannot be mixed')
            for key in ('track','layout','direction','car_id'):
                if not a['meta'].get(key) or a['meta'][key]=='unknown' or a['meta'][key]!=b['meta'].get(key):raise ValueError('Confirm compatible car, named track/layout and direction before comparing')
            rows=[]
            for detail,lapid in ((a,body.reference_lap),(b,body.candidate_lap)):
                lap=next((l for l in detail['laps'] if l['id']==lapid),None)
                if not lap or not lap['comparable']:raise ValueError('Select complete comparable laps')
                result=runtime.store.query('SELECT payload FROM samples WHERE session=? AND lap_id=? ORDER BY mono LIMIT 100001',(detail['id'],lapid))
                if len(result)>100000:raise ValueError('Lap exceeds 100,000 sample comparison limit')
                rows.append([json.loads(r['payload']) for r in result])
            return {'alignment':align_laps(*rows),'reference_braking':braking_episodes(rows[0]),'candidate_braking':braking_episodes(rows[1]),'conditions_warning':'Setup, tyres, assists and weather may differ. Review session notes.'}
        try:return await asyncio.to_thread(work)
        except ValueError as e:raise HTTPException(422,str(e))
    @app.get('/api/profiles')
    async def profiles():return await asyncio.to_thread(runtime.store.query,'SELECT * FROM profiles ORDER BY name LIMIT 200')
    class Profile(BaseModel):name:str=Field(min_length=1,max_length=100);settings:Settings
    @app.put('/api/profiles')
    def save_profile(body:Profile):runtime.store.put('profile',(body.name,body.settings.model_dump_json()));return {'ok':True}
    @app.websocket('/ws')
    async def websocket(ws:WebSocket):
        if not origin_ok(ws.headers.get('origin')) or not token_ok(ws.cookies.get('gt7_token')):await ws.close(code=1008);return
        await ws.accept();runtime.clients+=1
        try:
            while True:
                # No publisher queue: each client obtains only the newest state.
                await asyncio.wait_for(ws.send_json(runtime.snapshot()),timeout=1)
                await asyncio.sleep(1/(4 if runtime.degraded else runtime.settings.ui_hz))
        except Exception:pass
        finally:runtime.clients-=1
    dist=ROOT/'frontend'/'dist'
    if dist.exists():app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
    else:
        @app.get('/')
        def missing():return HTMLResponse('<h1>Build the frontend first</h1><p>Run npm ci and npm run build in frontend.</p>')
    return app

# Use create_app(data_dir) from the launcher, or uvicorn's --factory option.
# Importing this module must not create writable data inside an installed app.
