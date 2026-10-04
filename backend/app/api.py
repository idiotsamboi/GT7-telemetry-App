import asyncio,json,os,time,uuid,secrets,sqlite3
from datetime import datetime,timezone,timedelta
from typing import Literal
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI,Request,WebSocket,HTTPException
from fastapi.responses import JSONResponse,FileResponse,HTMLResponse,Response
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
from .storage.exports import EXPORT_FORMATS,export_session,import_session_file
from .storage.repositories import SqliteSessionRepository
from .storage.models import SessionQuery
from .analysis_cache import AnalysisCache,source_hash
from .core.version import ANALYSIS_VERSION
from .storage.layout import DataLayout
from .control import control_action
from . import operations as ops
from .core.errors import AppError
from .core.logging_setup import setup_logging,shutdown_logging,log_event
from .core.version import APP_VERSION
from .safe_mode import RunMarker,decide as decide_safe_mode
from .core.commands import Ctx,COMMANDS,RateLimiter,dispatch
from .core.permissions import Principal,capabilities_for,matrix as capability_matrix
from .core.features import snapshot as features_snapshot
from .core.modules import MODULES
from .diagnostics_report import collect as diagnostics_collect,redacted_bundle
import logging

ROOT=Path(__file__).resolve().parents[2]

def create_app(data_dir=None,*,safe_mode=False,config=None):
    """Startup stages: 1 load config, 2 validate+migrate (Config), 3 init logging, 4 open storage, 5 decide safe mode,
    6 build + start the runtime and its services (Runtime.start), 7 mount API/UI. A failure in stages 2-4 (invalid
    settings, unopenable database) starts in safe mode instead of a blank screen. Pass `config` to reuse a Config
    the launcher already loaded (keeps its recovery notice)."""
    cfg=config or Config(data_dir or os.environ.get('GT7_DATA',ROOT/'data'));runtime=None
    forced_safe=safe_mode or os.environ.get('GT7_SAFE_MODE')=='1'
    @asynccontextmanager
    async def lifespan(app):
        nonlocal runtime
        log_token=setup_logging(cfg.root/'logs',cfg.settings.log_level)
        marker=RunMarker(cfg.root);lock=None;store=None;started=False
        try:
            log_event('system',logging.INFO,'startup',stage='logging',version=APP_VERSION,data_dir_name=cfg.root.name)
            crashed=marker.dirty()
            if cfg.migrated_from:log_event('system',logging.INFO,'settings_migrated',from_schema=cfg.migrated_from)
            # A lock socket prevents multiple HTTP workers from creating duplicate owners.
            import socket
            lock=socket.socket()
            try:lock.bind(('127.0.0.1',cfg.settings.http_port+1 if cfg.settings.http_port<65535 else 65534))
            except OSError:raise RuntimeError('Another GT7 instance owns the single-receiver lock. Use one Uvicorn worker.')
            storage_error=''
            try:store=Store(cfg.root/'telemetry.sqlite3')
            except Exception as error:
                storage_error=str(error)[:300];log_event('storage',logging.ERROR,'storage_open_failed',error=storage_error)
                store=Store(cfg.root/'telemetry-safe.sqlite3')    # never a blank screen: fall back to a temporary database
            mode=decide_safe_mode(forced=forced_safe,marker_dirty=crashed,safe_mode_on_crash=cfg.settings.safe_mode_on_crash,settings_invalid=bool(cfg.recovery_notice),storage_failed=bool(storage_error),detail=storage_error or (cfg.recovery_notice or ''))
            if mode:log_event('system',logging.WARNING,'safe_mode',reason=mode.reason)
            runtime=Runtime(cfg,store);runtime.set_safe_mode(mode);runtime.local_origins=local_origins;runtime.scenario_override=os.environ.get('GT7_SCENARIO','');app.state.runtime=runtime
            await runtime.start();started=True
            marker.write()
            if os.environ.get("GT7_DEMO")=="1":runtime.switch("demo")
            yield
        finally:
            # every cleanup step runs even if an earlier one raises; a failed startup must not leave the port lock,
            # the database, the marker or the log file behind
            try:
                if started:await runtime.close()
                elif runtime is not None:
                    try:await runtime.close()
                    except Exception:log_event('system',logging.ERROR,'shutdown_after_failed_start_failed')
                elif store is not None:await asyncio.to_thread(store.close)
            finally:
                if lock is not None:lock.close()
                if started:marker.clear()      # only the instance that wrote the marker removes it (a lock-conflict must not erase a running instance's)
                log_event('system',logging.INFO,'shutdown',clean=started)
                shutdown_logging(log_token)
    app=FastAPI(title='GT7 Race Engineer',lifespan=lifespan,docs_url=None,redoc_url=None)
    from .group.admin import router as group_router
    from pydantic import ValidationError
    app.include_router(group_router())
    from .gamification.api import router as career_router
    app.include_router(career_router())
    from .obs_api import router as obs_router
    app.include_router(obs_router())
    from .assets_api import router as assets_router
    app.include_router(assets_router())
    @app.exception_handler(AppError)
    async def app_error(request,error):return JSONResponse({'detail':error.detail},error.status_code)
    @app.exception_handler(ValidationError)
    async def invalid_group_request(request,error):return JSONResponse({'detail':'Invalid request: '+str(error)[:400]},422)
    # Keep the running loopback UI reachable even after an origin/port edit.
    local_origins={f'http://127.0.0.1:{cfg.settings.http_port}',f'http://localhost:{cfg.settings.http_port}'}
    bind_host=str(cfg.settings.http_host)
    if bind_host not in ('0.0.0.0','::'):
        local_origins.add(f'http://{"["+bind_host+"]" if ":" in bind_host else bind_host}:{cfg.settings.http_port}')
    def origin_ok(origin):return origin in local_origins or origin in cfg.settings.allowed_origins
    def token_ok(token):return bool(token) and secrets.compare_digest(token,cfg.token)
    @app.middleware('http')
    async def guard(request,call_next):
        if request.headers.get('content-length','0').isdigit() and int(request.headers.get('content-length','0'))>34*1024*1024:return JSONResponse({'detail':'Request too large'},413)
        origin=request.headers.get('origin')
        host=request.url.hostname
        allowed={'127.0.0.1','localhost','::1'}|{urlparse(x).hostname for x in set(cfg.settings.allowed_origins)|local_origins}
        if host not in allowed:return JSONResponse({'detail':'Host not configured'},403)
        if origin and not origin_ok(origin):return JSONResponse({'detail':'Origin not allowed'},403)
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/pair'):
            if not token_ok(request.headers.get('x-control-token') or request.cookies.get('gt7_token')):return JSONResponse({'detail':'Pair this browser first'},401)
        result=await call_next(request)
        result.headers['X-Content-Type-Options']='nosniff';result.headers['Referrer-Policy']='no-referrer';result.headers['Cache-Control']='no-store' if request.url.path.startswith('/api') else 'no-cache'
        result.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return result
    @app.get('/api/health')
    def health():return {'ok':True,'service':'GT7 Race Engineer','version':APP_VERSION}
    @app.post('/api/pair')
    async def pair(request:Request):
        body=await request.json()
        local=request.client and request.client.host in ('127.0.0.1','::1','testclient') and request.url.hostname in ('127.0.0.1','localhost','::1')
        if not local and not token_ok(body.get('token')):raise HTTPException(403,'Enter pairing token from the data/control-token file')
        response=JSONResponse({'paired':True});response.set_cookie('gt7_token',cfg.token,httponly=True,samesite='strict',secure=request.url.scheme=='https');return response
    @app.get('/api/state')
    def state():return runtime.snapshot()
    @app.get('/api/settings')
    def settings():return cfg.settings.model_dump(mode='json')
    @app.put('/api/settings')
    async def save_settings(settings:Settings):return ops.settings_update(runtime,settings)
    @app.get('/api/tracks')
    def tracks():return TRACKS
    @app.get('/api/track-map')
    def track_map():return runtime.track_map.snapshot()
    class MapImport(BaseModel):
        layout_id:str=Field(max_length=16)
        points:list=Field(max_length=4096)
    @app.put('/api/track-map')
    async def import_map(body:MapImport):return await ops.track_import(runtime,body.layout_id,body.points)
    class MapSelection(BaseModel):
        layout_id:str=Field(max_length=16)
    @app.post('/api/track-map/select')
    async def select_map(body:MapSelection):return await ops.track_select(runtime,body.layout_id)
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
    async def confirm_map(body:MapConfirmation):return await ops.track_confirm(runtime,body.layout_id,body.candidate_id)
    @app.post('/api/track-map/restore')
    async def restore_map(body:MapRestore):return await ops.track_restore(runtime,body.layout_id,body.revision)
    TRAINING_LAYOUTS=ops.TRAINING_LAYOUTS
    @app.get('/api/training/candidates')
    def training_candidates():
        from .track_bundle import iter_models
        try:covered={m['layout_id'] for m in iter_models()}
        except (OSError,ValueError):covered=set()
        trained=covered|{p.stem for p in runtime.training.root.glob('*.jsonl') if runtime.training.saved_lap_count(p.stem)}
        return [{'id':k,'name':v['name'],'track':v['track'],'venue_id':v['venue_id'],'direction':v['direction'],'length_m':v['length_m']} for k,v in TRAINING_LAYOUTS.items() if k not in trained]
    class TrainingStart(BaseModel):
        layout_id:str=Field(max_length=16)
    @app.post('/api/training/start')
    def start_training(body:TrainingStart):return ops.training_start(runtime,body.layout_id)
    @app.post('/api/training/stop')
    def stop_training():return ops.training_stop(runtime)
    @app.post('/api/training/retry-lap')
    def retry_lap():return ops.training_retry_lap(runtime)
    @app.get('/api/training/progress')
    def training_progress():
        return runtime.training.list_progress(TRAINING_LAYOUTS)
    class TrainingRestart(BaseModel):
        layout_id:str=Field(max_length=16)
    @app.post('/api/training/restart')
    def restart_training(body:TrainingRestart):return ops.training_restart(runtime,body.layout_id)
    @app.get('/recovery')
    def recovery_page():return FileResponse(Path(__file__).parent/'data/recovery.html',media_type='text/html')
    @app.get('/recovery.js')
    def recovery_script():return FileResponse(Path(__file__).parent/'data/recovery.js',media_type='application/javascript')
    class RecoveryAction(BaseModel):
        action:Literal['live','display','connection','audio']
    @app.post('/api/recovery')
    async def recover(body:RecoveryAction):return await ops.recovery_action(runtime,body.action,local_origins)
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
        # Thin shim: the same actions are exposed as commands (source.*, audio.*, session.*) via control.py
        return await control_action(runtime,body.action,body.value)
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
        return await ops.session_update_meta(runtime,sid,notes=body.notes,tags=body.tags,protected=body.protected,track=body.track,layout=body.layout,direction=body.direction,reference_lap=body.reference_lap)
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
    async def archive(sid:str,body:Archive):return await ops.session_set_archived(runtime,sid,body.archived)
    @app.get('/api/retention')
    async def retention_preview():return await ops.retention_candidates(runtime)
    @app.post('/api/retention')
    async def retention_apply():return await ops.retention_apply(runtime)
    class Purge(BaseModel):confirmation:Literal['DELETE ARCHIVED SESSION']
    @app.post('/api/sessions/{sid}/purge')
    async def purge(sid:str,body:Purge):return await ops.session_purge(runtime,sid)
    @app.get('/api/sessions-index')
    async def sessions_index(limit:int=50,cursor:str|None=None,include_archived:bool=False,provenance:str|None=None):
        """Paged session index straight from the repository: never loads samples, keyset cursor."""
        await asyncio.to_thread(runtime.store.flush)
        page=await asyncio.to_thread(SqliteSessionRepository(runtime.store).list,SessionQuery(include_archived=include_archived,provenance=provenance,limit=limit,cursor=cursor))
        return page.to_public()
    @app.get('/api/sessions/{sid}/lap-series')
    async def lap_series(sid:str,lap_id:str,channels:str='speed_kmh,throttle,brake',points:int=600):
        """Extrema-preserving lap series (derived channels included in the stored values), for charts."""
        await asyncio.to_thread(runtime.store.flush)
        wanted=[c for c in channels.split(',') if c][:16]
        if not wanted:raise HTTPException(422,'Choose at least one channel')
        series=await asyncio.to_thread(SqliteSessionRepository(runtime.store).lap_series,sid,lap_id,wanted,points)
        return series.to_public()
    @app.get('/api/export-formats')
    def export_formats():return EXPORT_FORMATS.to_public()
    @app.get('/api/sessions/{sid}/export')
    async def export(sid:str,format:str='bundle_v1',lap_id:str|None=None,channels:str|None=None):
        if runtime.sessions.id:raise HTTPException(409,'End recording before creating a bundle')
        fmt=EXPORT_FORMATS.get(format)
        if not fmt:raise HTTPException(422,'Unknown export format')
        if not await asyncio.to_thread(runtime.store.detail,sid):raise HTTPException(404,'Unknown session')
        if format=='bundle_v1':
            folder=cfg.root/'exports';folder.mkdir(exist_ok=True)
            path=await asyncio.to_thread(export_bundle,runtime.store,sid,folder);return FileResponse(path,filename='gt7-session.zip')
        import io
        options={'lap_id':lap_id,'channels':[c for c in (channels or '').split(',') if c] or None}
        buffer=io.BytesIO();await asyncio.to_thread(export_session,runtime.store,sid,format,buffer,options)
        return Response(buffer.getvalue(),media_type=fmt.media_type if hasattr(fmt,'media_type') else 'application/octet-stream',headers={'Content-Disposition':f'attachment; filename="gt7-session{fmt.extension}"'})
    @app.post('/api/import')
    async def import_session(request:Request):
        if runtime.sessions.id:raise HTTPException(409,'End recording before importing')
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>32*1024*1024:raise HTTPException(413,'Import too large')
        try:imported=await asyncio.to_thread(import_session_file,bytes(data))
        except Exception as e:raise HTTPException(400,str(e))
        meta,rows=imported.metadata,imported.rows
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
            cache=AnalysisCache(cfg.root);key=f'compare:{body.reference_session}:{body.reference_lap}:{body.candidate_session}:{body.candidate_lap}'
            src=source_hash(runtime.store,body.reference_session)+source_hash(runtime.store,body.candidate_session)
            cached=cache.get(key,src)
            if cached is not None:return cached
            rows=[]
            for detail,lapid in ((a,body.reference_lap),(b,body.candidate_lap)):
                lap=next((l for l in detail['laps'] if l['id']==lapid),None)
                if not lap or not lap['comparable']:raise ValueError('Select complete comparable laps')
                result=runtime.store.query('SELECT payload FROM samples WHERE session=? AND lap_id=? ORDER BY mono LIMIT 100001',(detail['id'],lapid))
                if len(result)>100000:raise ValueError('Lap exceeds 100,000 sample comparison limit')
                rows.append([json.loads(r['payload']) for r in result])
            result={'alignment':align_laps(*rows),'reference_braking':braking_episodes(rows[0]),'candidate_braking':braking_episodes(rows[1]),'conditions_warning':'Setup, tyres, assists and weather may differ. Review session notes.'}
            cache.put(key,src,result);return result
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
                await asyncio.sleep(1/(4 if runtime.degraded else runtime.effective_ui_hz()))
        except Exception:pass
        finally:runtime.clients-=1
    # ---- foundation endpoints: services, features, capabilities, commands, diagnostics ------------------------
    local_principal=Principal('local','operator')
    GROUP_COMMANDS=('group.','raceControl.','graphics.','branding.')
    def command_ctx(command_id=''):
        from .storage.audit import AuditSink
        session_id=runtime.sessions.id
        if command_id.startswith(GROUP_COMMANDS):       # group actions are recorded against the group session (ADR 0007)
            try:session_id=runtime.group.group()['session_id']
            except Exception:pass
        return Ctx(local_principal,services=runtime,audit=AuditSink(runtime.store),session_id=session_id)
    @app.get('/api/services')
    def services():return runtime.services.public()
    @app.get('/api/features')
    def feature_flags():return features_snapshot(runtime.settings,safe_mode=runtime.safe_mode is not None)
    @app.get('/api/me/capabilities')
    def my_capabilities():return {'principal':{'kind':local_principal.kind,'subject':local_principal.subject},'capabilities':sorted(capabilities_for(local_principal)),'roles':capability_matrix()}
    @app.get('/api/commands')
    def command_catalogue():
        from . import commands_catalog  # noqa: F401  (registers the catalogue)
        return COMMANDS.to_public()
    @app.post('/api/commands/{command_id}')
    async def run_command(command_id:str,request:Request):
        from . import commands_catalog  # noqa: F401
        try:payload=await request.json()
        except ValueError:payload={}
        result=await dispatch(command_ctx(command_id),command_id,payload if isinstance(payload,dict) else {})
        return JSONResponse(result.to_public(),result.http_status)
    @app.get('/api/diagnostics')
    def diagnostics():return diagnostics_collect(runtime,cfg)
    class CopyRequest(BaseModel):include_ips:bool=False
    @app.post('/api/diagnostics/copy')
    def diagnostics_copy(body:CopyRequest):return redacted_bundle(runtime,cfg,include_ips=body.include_ips)
    class ClientError(BaseModel):
        message:str=Field(max_length=1000);stack:str=Field('',max_length=4000);component:str=Field('',max_length=100);url:str=Field('',max_length=300)
    client_limiter=RateLimiter()
    @app.post('/api/client-errors')
    def client_errors(body:ClientError):
        if not client_limiter.allow(('client-errors','local'),30,60):return JSONResponse({'detail':'Too many client error reports'},429)
        log_event('ui',logging.ERROR,'client_error',message=body.message,component=body.component,stack=body.stack[:1500],url=body.url.split('#')[0])
        return {'ok':True}
    @app.get('/api/audit')
    async def audit(session:str|None=None,since:float|None=None,limit:int=200):
        await asyncio.to_thread(runtime.store.flush)      # audit rows are written by the single writer thread
        return await asyncio.to_thread(runtime.store.audit,session,since,max(1,min(limit,1000)))
    def require_developer_mode():
        if not runtime.settings.developer_mode:raise HTTPException(404,'Developer mode is off')
    @app.get('/api/dev/packets')
    def dev_packets(n:int=20):
        require_developer_mode();return {'frames':list(runtime.dev_frames)[:max(1,min(n,50))],'raw_capture':runtime.settings.raw_capture,'note':'Latest parsed frames at 10 Hz; raw_hex only when raw_capture is on.'}
    @app.get('/api/dev/scenarios')
    def dev_scenarios():
        require_developer_mode()
        from .telemetry.sources import SCENARIOS
        return {'active':runtime.settings.demo_scenario or None,'scenarios':SCENARIOS.to_public()}
    @app.get('/api/alerts')
    def alerts(include_acknowledged:bool=False):return runtime.alerts.to_public(include_acknowledged)
    @app.get('/api/modules')
    def module_registry():
        from . import modules  # noqa: F401  (registers the modules)
        return MODULES.to_public()
    @app.get('/api/storage')
    async def storage_info():return {'layout':DataLayout(cfg.root).describe(),'health':await asyncio.to_thread(runtime.store.health)}
    @app.get('/api/channels')
    def channels():
        from .telemetry.derived import all_public_channels as public_channels
        return public_channels()
    dist=ROOT/'frontend'/'dist'
    if dist.exists():app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
    else:
        @app.get('/')
        def missing():return HTMLResponse('<h1>Build the frontend first</h1><p>Run npm ci and npm run build in frontend.</p>')
    return app

# Use create_app(data_dir) from the launcher, or uvicorn's --factory option.
# Importing this module must not create writable data inside an installed app.
