import {TrackSelect} from './RaceVisuals';
import RaceDesk from './RaceDesk';
import GroupStudio from './GroupStudio';
import LeagueBranding from './LeagueBranding';
import {useEffect,useRef,useState} from 'react';
import {ShieldAlert,Radio as RadioIcon,FolderOpen,LayoutGrid,Palette,UploadCloud} from 'lucide-react';
import {pulse,crossfade,enter} from './motion';
import {groupApi,settingsApi} from './domain/api';
import type {GroupMethod} from './domain/api/group';
const DAVINCI_TABS=[['media','Media',FolderOpen],['edit','Edit',LayoutGrid],['color','Color',Palette],['deliver','Deliver',UploadCloud]] as const;
const FLAG_LABEL:Record<string,string>={green:'TRACK CLEAR',yellow:'YELLOW',double_yellow:'DOUBLE YELLOW',red:'RED FLAG',blue:'BLUE FLAG',white:'WHITE',black:'BLACK FLAG',mechanical:'MECHANICAL',checkered:'CHEQUERED',safety_car:'SAFETY CAR',fcy:'FULL COURSE YELLOW',vsc:'VIRTUAL SAFETY CAR',warning:'WARNING'};
export default function GroupControl({mode='control'}:{mode?:'control'|'studio'}){
 const [data,setData]=useState<any>(null),[error,setError]=useState(''),[notice,setNotice]=useState(''),[leagueName,setLeagueName]=useState('My league'),[league,setLeague]=useState(''),[eventName,setEventName]=useState('Race night'),[origins,setOrigins]=useState('http://127.0.0.1:8090'),[hostOnly,setHostOnly]=useState(false),[secret,setSecret]=useState(''),[host,setHost]=useState('http://192.168.1.10:8090'),[invite,setInvite]=useState(''),[driver,setDriver]=useState(''),[number,setNumber]=useState(''),[sharing,setSharing]=useState<string[]>(['basic']),[demoMembers,setDemoMembers]=useState(8),[tracks,setTracks]=useState<any[]>([]),[layout,setLayout]=useState(''),[recordings,setRecordings]=useState<any[]>([]),[studioTab,setStudioTab]=useState<'media'|'edit'|'color'|'deliver'>('media');
 const refresh=()=>groupApi.state().then(setData).catch(e=>setError(e.message));
 useEffect(()=>{settingsApi.tracks().then(setTracks).catch(e=>setError(e.message));refresh();const timer=setInterval(refresh,1000);return()=>clearInterval(timer)},[]);
 const run=async(path:string,body:any,method='POST')=>{try{setError('');const result=await groupApi.call(path,body,method as GroupMethod);await refresh();setNotice('Saved');return result}catch(e:any){setError(e.message)}};
 const g=data?.group,s=data?.snapshot;
 const globalFlags=(g?.instructions||[]).filter((i:any)=>i.scope==='global'&&!i.cancelled&&(!i.expires||i.expires>(s?.timeline||0)));
 const flagOrder=['red','black','mechanical','double_yellow','yellow','safety_car','fcy','vsc','checkered','blue','white','warning','green'];
 const activeFlag=[...globalFlags].sort((a:any,b:any)=>flagOrder.indexOf(a.flag)-flagOrder.indexOf(b.flag)||b.effective-a.effective)[0];
 const alarmRef=useRef<HTMLDivElement>(null),consoleRef=useRef<HTMLDivElement>(null),pageRef=useRef<HTMLDivElement>(null);
 useEffect(()=>{pulse(alarmRef.current)},[activeFlag?.id]);
 useEffect(()=>{enter(consoleRef.current)},[!!g]);
 useEffect(()=>{crossfade(pageRef.current)},[studioTab]);

 if(mode==='control')return <div className="rc-console" ref={consoleRef}>
 <div className={'rc-alarm '+(activeFlag?'rc-flag-'+activeFlag.flag:'rc-flag-none')} ref={alarmRef}>
  <div className="rc-alarm-main"><ShieldAlert size={22}/><div><strong>{activeFlag?FLAG_LABEL[activeFlag.flag]||activeFlag.flag.toUpperCase():'NO ACTIVE INSTRUCTION'}</strong><small>{activeFlag?activeFlag.reason||'Global instruction':'No global instruction · connected-group standings'}</small></div></div>
  <div className="rc-alarm-meta"><span>{g?g.name.toUpperCase():'NO EVENT LOADED'}</span><span>{g?g.state.toUpperCase():'—'}</span><span>{s?.coverage?.toUpperCase()||'—'}</span></div>
 </div>
 {error&&<p role="alert" className="rc-error">{error}</p>}
 {!g&&<section className="rc-setup"><h2>Session setup</h2><p className="subtle">Race Control needs an active event. Create one, or rehearse with synthetic drivers.</p>
  <div className="rc-setup-grid">
   <div><label>Saved league<select value={league} onChange={e=>setLeague(e.target.value)}><option value="">Choose league</option>{data?.leagues.map((l:any)=><option key={l.id} value={l.id}>{l.branding.name}</option>)}</select></label><label>League name<input value={leagueName} onChange={e=>setLeagueName(e.target.value)}/></label><button onClick={async()=>{const l=await run('leagues',{name:leagueName});if(l)setLeague(l.id)}}>Create league</button></div>
   <div><label>Event name<input value={eventName} onChange={e=>setEventName(e.target.value)}/></label><TrackSelect tracks={tracks} value={layout} onChange={setLayout}/><button className="primary" disabled={!league} onClick={()=>run('create',{name:eventName,event_name:eventName,league_id:league,layout_id:layout})}>Create event</button></div>
   <div><label>League demo grid<select value={demoMembers} onChange={e=>setDemoMembers(Number(e.target.value))}>{[4,8,16].map(n=><option key={n} value={n}>{n} drivers</option>)}</select></label><button onClick={()=>run('demo',{action:'start',members:demoMembers})}>Start rehearsal demo</button></div>
  </div></section>}
 {g&&<section className="rc-session-bar"><div className="toolbar">
  <button onClick={()=>run('configure',{join_locked:!g.join_locked},'PUT')}>{g.join_locked?'Unlock joining':'Lock joining'}</button>
  {data?.demo&&<button onClick={()=>run('demo',{action:data.demo.paused?'resume':'pause'})}>{data.demo.paused?'Resume demo':'Pause demo'}</button>}
  {data?.demo&&<button onClick={()=>run('demo',{action:'stop'})}>Stop demo</button>}
  <div className="grow"/>
  {['start','end','finalize','close'].map(action=><button key={action} className={action==='start'?'primary':''} onClick={()=>run('session/'+action,{})}>{action==='finalize'?'Confirm results':action}</button>)}
 </div></section>}
 {g&&<RaceDesk data={data} run={run}/>}
 </div>;

 const selectedLeague=data?.leagues.find((l:any)=>l.id===league);
 return <div className="studio-app davinci">
 <div className="davinci-pagebar">{DAVINCI_TABS.map(([id,label,Icon])=><button key={id} className={studioTab===id?'active':''} onClick={()=>setStudioTab(id)}><Icon size={15}/>{label}</button>)}</div>
 <div className="davinci-page" ref={pageRef}>
 <p className="badge amber">Development preview · production controls do not affect GT7</p>{error&&<p role="alert" className="amber-text">{error}</p>}{notice&&<p role="status">{notice}</p>}

 {studioTab==='media'&&<div className="two-col"><section className="card"><h2>League &amp; event</h2><label>League name<input value={leagueName} onChange={e=>setLeagueName(e.target.value)}/></label><button onClick={async()=>{const l=await run('leagues',{name:leagueName});if(l)setLeague(l.id)}}>Create league</button><label>Saved league<select value={league} onChange={e=>setLeague(e.target.value)}><option value="">Choose league</option>{data?.leagues.map((l:any)=><option key={l.id} value={l.id}>{l.branding.name}</option>)}</select></label>{league&&<button onClick={()=>setStudioTab('color')}><Palette size={14}/>Open in Color</button>}<label>Event name<input value={eventName} onChange={e=>setEventName(e.target.value)}/></label><TrackSelect tracks={tracks} value={layout} onChange={setLayout}/><button disabled={!league||!!g} onClick={()=>run('create',{name:eventName,event_name:eventName,league_id:league,layout_id:layout})}>Create event</button><p className="subtle">{g?`${g.name} · ${g.state}`:'No active event — create one, or manage it from Race Control.'}</p></section>
 <section className="card"><h2>Recorded media</h2><p className="subtle">Recorded group sessions, available to replay in Deliver for testing overlays or reviewing incidents.</p><div className="toolbar"><button onClick={async()=>{try{setRecordings(await groupApi.recordings());setError('')}catch(e:any){setError(e.message)}}}>Load recorded sessions</button></div><div className="session-list">{recordings.map((r:any)=><div className="toolbar" key={r.session_id}><span>{r.name} · {r.event_name} · {r.started?new Date(r.started*1000).toLocaleString():'—'}</span></div>)}{!recordings.length&&<p className="subtle">No recordings loaded yet.</p>}</div></section></div>}

 <div hidden={studioTab!=='edit'}><GroupStudio data={data} run={run}/></div>

 {studioTab==='color'&&(selectedLeague?<LeagueBranding league={selectedLeague} onSaved={refresh} onClose={()=>setStudioTab('media')}/>:<section className="card"><h2>Color</h2><p className="subtle">Choose a league to grade its branding — logos, palette, sponsors and teams.</p><label>League<select value={league} onChange={e=>setLeague(e.target.value)}><option value="">Choose league</option>{data?.leagues.map((l:any)=><option key={l.id} value={l.id}>{l.branding.name}</option>)}</select></label></section>)}

 {studioTab==='deliver'&&<div className="two-col"><section className="card"><h2>LAN hosting</h2><p>List the exact browser addresses allowed to connect, including your LAN IP and port. Separate addresses with commas.</p><label>Allowed origins<input value={origins} onChange={e=>setOrigins(e.target.value)}/></label><label><input type="checkbox" checked={hostOnly} onChange={e=>setHostOnly(e.target.checked)}/> Host only · suspend local receiver and microphone</label><div className="toolbar"><button onClick={()=>run('hosting',{enabled:true,port:8090,origins:origins.split(',').map(x=>x.trim()).filter(Boolean),host_only:hostOnly})}>Enable group listener</button><button onClick={()=>run('hosting',{enabled:false})}>Disable listener</button></div><p>{data?.listener?.enabled?'Listening on port '+data.listener.port:'LAN hosting disabled'}</p>{g&&<><div className="toolbar">{['driver','spectator'].map(role=><button key={role} onClick={async()=>{const r=await run('invitations',{role});if(r)setSecret(r.credential)}}>Issue {role} invitation</button>)}</div>{secret&&<label>Copy invitation now · shown only when issued<input readOnly value={secret}/><button onClick={()=>{navigator.clipboard.writeText(secret).then(()=>setNotice('Invitation copied')).catch(()=>setError('Select and copy the invitation manually'))}}>Copy</button><button onClick={()=>setSecret('')}>Hide</button></label>}</>}</section>
 <section className="card"><h2>Replay</h2><p className="subtle">Replay a recorded session through the same live pipeline. Does not resend console heartbeats or affect the current live group.</p><div className="toolbar"><button onClick={async()=>{try{setRecordings(await groupApi.recordings());setError('')}catch(e:any){setError(e.message)}}}>Load recorded sessions</button>{data?.replay_now&&<button onClick={()=>run('replay',{action:'stop'})}>Stop replay</button>}</div>
 <div className="session-list">{recordings.filter((r:any)=>r.session_id!==g?.session_id||g?.state!=='running').map((r:any)=><div className="toolbar" key={r.session_id}><span>{r.name} · {r.event_name} · {r.started?new Date(r.started*1000).toLocaleString():'—'}</span><button disabled={g?.state==='running'} onClick={()=>run('replay',{session_id:r.session_id})}>Replay this session</button></div>)}{!recordings.length&&<p className="subtle">No recordings loaded yet.</p>}</div>
 {data?.replay_now&&<div className="replay-controls"><span className="badge amber">REPLAYING</span><button onClick={()=>{const p=data.replay_now.replay;run('replay',{position:p.position,speed:p.speed,paused:!p.paused})}}>{data.replay_now.replay.paused?'Resume':'Pause'}</button><label>Speed<select value={data.replay_now.replay.speed} onChange={e=>{const p=data.replay_now.replay;run('replay',{position:p.position,paused:p.paused,speed:Number(e.target.value)})}}>{[.25,1,2,4,8,16].map(x=><option key={x} value={x}>{x}×</option>)}</select></label><button onClick={()=>{const p=data.replay_now.replay;run('replay',{position:p.position-10,paused:p.paused,speed:p.speed})}}>-10s</button><button onClick={()=>{const p=data.replay_now.replay;run('replay',{position:p.position+10,paused:p.paused,speed:p.speed})}}>+10s</button><span>{new Date(data.replay_now.replay.position*1000).toLocaleTimeString()} · {data.replay_now.coverage}</span></div>}</section>
 <section className="card"><h2><RadioIcon size={16}/> Remote group connection</h2><p className="subtle">Join another host's event as a driver or spectator from this installation.</p><div className="form-grid"><label>Host address<input value={host} onChange={e=>setHost(e.target.value)}/></label><label>Invitation<input type="password" value={invite} onChange={e=>setInvite(e.target.value)}/></label><label>Driver name<input value={driver} onChange={e=>setDriver(e.target.value)}/></label><label>Race number<input value={number} onChange={e=>setNumber(e.target.value)}/></label></div><p>Select the sharing categories you accept. The host rejects admission if required categories are missing.</p>{['basic','telemetry','fuel','strategy'].map(c=><label key={c}><input type="checkbox" checked={sharing.includes(c)} disabled={c==='basic'} onChange={e=>setSharing(e.target.checked?[...sharing,c]:sharing.filter(x=>x!==c))}/>{c} </label>)}<div className="toolbar"><button disabled={!driver||!invite} onClick={()=>run('connection',{host,credential:invite,identity:{display_name:driver,number},accepted_sharing:sharing,rate:5})}>Accept sharing and join</button><button onClick={()=>run('connection',{action:'disconnect'})}>Disconnect</button></div><p>{data?.client?.status||'Not connected'} {data?.client?.error}</p>{data?.client?.state?.messages?.filter((m:any)=>m.for_you).map((m:any)=><p key={m.id}>{m.text} <button onClick={()=>run('connection/response',{action:'acknowledged',message_id:m.id})}>Acknowledge</button></p>)}</section>
 </div>}
 </div></div>
}
