import {CircuitMap} from './RaceVisuals';
import {useEffect,useRef,useState} from 'react';
import {pulse} from './motion';
import {Flame,X,Radio} from 'lucide-react';
import {groupApi} from './domain/api';
import {AppError} from './domain/http';
const STATE_ORDER:Record<string,number>={critical:0,hot:1,forming:2};
function BattlesPanel({battles,entries,workspaces,run}:any){
 const [dismissed,setDismissed]=useState<string[]>([]);
 const [workspaceId,setWorkspaceId]=useState('');
 const [notice,setNotice]=useState('');
 useEffect(()=>{if(!workspaces.some((w:any)=>w.id===workspaceId))setWorkspaceId(workspaces[0]?.id||'')},[workspaces.length]);
 const rows=(battles||[]).filter((b:any)=>!dismissed.includes(b.id)).slice().sort((a:any,b:any)=>(STATE_ORDER[a.state]??9)-(STATE_ORDER[b.state]??9)||b.heat-a.heat);
 const name=(id:string)=>{const e=entries.find((x:any)=>x.entry_id===id);return e?`#${e.identity.number||'?'} ${e.identity.display_name}`:'Unknown car'};
 const focus=async(b:any,take:boolean)=>{
  const result=await run('battles/'+b.id+'/focus',{workspace_id:workspaceId,take,ensure_graphics:true});
  if(!result)return;
  const warn=result.warnings?.length?' · '+result.warnings.join('; '):'';
  setNotice(`Draft updated from battle P${b.position} (${name(b.ahead)} vs ${name(b.behind)})${take?' · taken to program':''}${warn}`);
  window.setTimeout(()=>setNotice(''),6000);
 };
 if(!rows.length)return null;
 return <div className="battles-panel"><h3 className="rc-section"><Flame size={15}/> Battles</h3>
 {workspaces.length>1&&<label className="battles-workspace-pick">Focus target<select aria-label="Workspace to focus into" value={workspaceId} onChange={e=>setWorkspaceId(e.target.value)}>{workspaces.map((w:any)=><option key={w.id} value={w.id}>{w.draft.name}</option>)}</select></label>}
 {notice&&<p role="status" className="battles-notice">{notice}</p>}
 <div className="battles-list">
  {rows.map((b:any)=><div className={'battle-row battle-'+b.state+(b.confidence==='low'?' battle-low-confidence':'')} key={b.id}>
   <div className="battle-heat-bar"><div className="battle-heat-fill" style={{width:`${b.heat}%`}}/></div>
   <span className={'battle-chip battle-chip-'+b.state}>{b.state.toUpperCase()}</span>
   <div className="battle-cars"><b>{name(b.ahead)}</b><span>vs</span><b>{name(b.behind)}</b>{b.lapping&&<span className="tiny-badge">Lapping</span>}{b.confidence==='low'&&<span className="tiny-badge">low confidence</span>}</div>
   <span className="battle-gap">{b.gap_s==null?'gap unknown':`${b.gap_s.toFixed(1)}s`}</span>
   <span className="battle-closing">{b.closing_per_lap_s==null?'':<>{b.closing_per_lap_s<0?'▼':'▲'} {Math.abs(b.closing_per_lap_s).toFixed(1)}s/lap</>}</span>
   <span className="battle-heat-value">{Math.round(b.heat)}</span>
   <div className="battle-actions">
    <button type="button" disabled={!workspaceId} title="Set this workspace's slots from this battle" onClick={()=>focus(b,false)}><Radio size={12}/>Focus</button>
    <button type="button" disabled={!workspaceId} title="Focus and publish immediately" onClick={()=>focus(b,true)}>Focus &amp; Take</button>
    <button type="button" className="battle-dismiss" title="Suppress alerts for this battle for 5 minutes" onClick={()=>{run('battles/'+b.id+'/dismiss',{});setDismissed(d=>[...d,b.id])}}><X size={13}/></button>
   </div>
  </div>)}
 </div></div>;
}
function FuelStrategyPanel({g,run}:any){
 const [full,setFull]=useState<any>(null);
 const [pitLoss,setPitLoss]=useState(g.pit_loss_s??'');
 const [refuelRate,setRefuelRate]=useState(g.refuel_rate_lps??'');
 useEffect(()=>{setPitLoss(g.pit_loss_s??'');setRefuelRate(g.refuel_rate_lps??'')},[g.pit_loss_s,g.refuel_rate_lps]);
 useEffect(()=>{let stopped=false;const poll=()=>groupApi.projection().then(v=>{if(!stopped)setFull(v)},e=>{if(!stopped&&e instanceof AppError&&e.status>0)setFull(null)});poll();const timer=setInterval(poll,2000);return()=>{stopped=true;clearInterval(timer)}},[]);
 const learnedPit=full?.pit_loss?.[1]==='learned'?full.pit_loss[0]:null;
 const learnedRefuel=full?.refuel_rate?.[1]==='learned'?full.refuel_rate[0]:null;
 return <details><summary>Fuel &amp; pit strategy</summary>
  <div className="form-grid">
   <label>Pit loss · seconds<input type="number" min={5} max={120} placeholder="Not set" value={pitLoss} onChange={e=>setPitLoss(e.target.value)}/></label>
   <label>Refuel rate · L/s<input type="number" min={0.5} max={20} step={0.1} placeholder="Not set" value={refuelRate} onChange={e=>setRefuelRate(e.target.value)}/></label>
  </div>
  <button onClick={()=>run('configure',{pit_loss_s:pitLoss===''?null:Number(pitLoss),refuel_rate_lps:refuelRate===''?null:Number(refuelRate)},'PUT')}>Save</button>
  <p className="subtle">Learned pit loss: {learnedPit==null?'not enough stops yet':`${learnedPit.toFixed(1)}s`}{learnedPit!=null&&<button onClick={()=>{setPitLoss(learnedPit.toFixed(1));run('configure',{pit_loss_s:learnedPit},'PUT')}}>Use learned</button>}</p>
  <p className="subtle">Learned refuel rate: {learnedRefuel==null?'not enough stops yet':`${learnedRefuel.toFixed(2)} L/s`}{learnedRefuel!=null&&<button onClick={()=>{setRefuelRate(learnedRefuel.toFixed(2));run('configure',{refuel_rate_lps:learnedRefuel},'PUT')}}>Use learned</button>}</p>
  {full?.coverage&&<p className="subtle">{full.coverage.sharing} of {full.coverage.total} cars share fuel data.</p>}
  {!full?.result&&<p className="subtle">Projection needs a laps or timed format session.</p>}
 </details>;
}
function StewardCueQueue({g,run}:any){
 const cues=g.steward_cues||[];
 return <details><summary>Steward cue queue ({cues.length})</summary>
  <label className="check"><input type="checkbox" checked={!!g.auto_steward_paused} onChange={e=>run('steward-cues/paused',{paused:e.target.checked},'PUT')}/>Pause auto cues</label>
  {cues.length?<div className="event-list rc-tight">{cues.slice().reverse().map((c:any)=><div className="toolbar" key={c.id}><span>{c.text}</span><button onClick={()=>run('steward-cues/'+c.id,{},'DELETE')}>Cancel</button></div>)}</div>:<p className="subtle">No automated cues yet this session.</p>}
 </details>;
}
export default function RaceDesk({data,run}:any){
 const g=data.group,s=data.snapshot,entries=s?.entries||[],[selected,setSelected]=useState(''),[search,setSearch]=useState(''),[scope,setScope]=useState('global'),[zone,setZone]=useState(''),[reason,setReason]=useState(''),[text,setText]=useState(''),[expiry,setExpiry]=useState(60),[messageScope,setMessageScope]=useState('all'),[penalty,setPenalty]=useState('warning'),[amount,setAmount]=useState(5),[zoneName,setZoneName]=useState(''),[zoneStart,setZoneStart]=useState(0),[zoneEnd,setZoneEnd]=useState(10),[roster,setRoster]=useState<any>(null);
 const instructionBank=useRef<HTMLDivElement>(null);
 useEffect(()=>{pulse(instructionBank.current)},[g.instructions.length]);
 useEffect(()=>{if(!entries.some((e:any)=>e.entry_id===selected))setSelected(entries[0]?.entry_id||'')},[g.id,entries.length]);
 const entry=entries.find((e:any)=>e.entry_id===selected),target=scope==='entry'?selected:scope==='zone'?zone:'',rawEntry=g.entries[selected],admittedDrivers=Object.values(g.participants).filter((p:any)=>p.role==='driver'&&p.status!=='removed');
 useEffect(()=>{if(rawEntry)setRoster({display_name:rawEntry.identity.display_name,number:rawEntry.identity.number,team:rawEntry.identity.team,class_name:rawEntry.identity.class_name,baseline:rawEntry.baseline??'',grid:rawEntry.grid??'',notes:rawEntry.notes||'',participant_id:rawEntry.participant_id});else setRoster(null)},[selected]);
 const flags=['green','yellow','double_yellow','red','blue','white','black','mechanical','checkered','safety_car','fcy','vsc'];
 return <section className="card rc-desk"><div className="studio-title"><h2>Race director</h2><span className="badge">{s.provenance?.toUpperCase()} · {g.state.toUpperCase()}</span></div>
 <div className="atem-bank rc-tight"><small>SOURCE SELECT</small><div className="atem-row">{entries.map((e:any)=><button key={e.entry_id} className={'atem-btn '+(e.entry_id===selected?'live':'')+(e.stale?' atem-off':'')} onClick={()=>setSelected(e.entry_id)}><b>{e.identity.number||'—'}</b><small>{e.identity.display_name.split(' ')[0]}</small></button>)}{!entries.length&&<span className="subtle">No connected entries</span>}</div></div>

 <BattlesPanel battles={s.battles} entries={entries} workspaces={(data.workspaces||[]).filter((w:any)=>w.group_id===g.id)} run={run}/>

 <div className="rc-grid">
  <div className="race-desk"><div><label>Find driver, team or class<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search connected entries"/></label><div className="table-wrap"><table><thead><tr><th>P</th><th>Driver</th><th>Laps</th><th>Best</th><th>Link</th></tr></thead><tbody>{entries.filter((e:any)=>JSON.stringify(e.identity).toLowerCase().includes(search.toLowerCase())).map((e:any)=><tr key={e.entry_id} className={e.entry_id===selected?'selected':''} onClick={()=>setSelected(e.entry_id)}><td>{e.position??'—'}</td><td><button onClick={()=>setSelected(e.entry_id)}>#{e.identity.number} {e.identity.display_name}</button><small>{e.identity.team} · {e.identity.class_name}</small></td><td>{e.completed_laps??'—'}</td><td>{e.best_ms==null?'—':(e.best_ms/1000).toFixed(3)}</td><td>{e.stale?'STALE':'LIVE'}</td></tr>)}</tbody></table></div><details><summary>Admission and participants ({Object.keys(g.participants).length})</summary>{Object.values(g.participants).map((p:any)=><div className="toolbar" key={p.id}><span>{p.identity.display_name} · {p.role} · {p.status}</span>{p.status==='pending'&&<button onClick={()=>run('participants/'+p.id,{status:'admitted'})}>Admit</button>}{p.status!=='removed'&&<button onClick={()=>run('participants/'+p.id,{status:'removed'})}>Remove</button>}</div>)}</details></div><div className="inspector"><h3>{entry?`#${entry.identity.number} ${entry.identity.display_name}`:'Select a driver'}</h3><p>{entry?.identity.team} · {entry?.identity.class_name} · {entry?.car?.name||'Car unavailable'} · {entry?.stale?'Telemetry stale':'Receiving telemetry'}</p>{data.demo&&entry&&<button onClick={()=>run('demo',{action:'disconnect',entry_id:selected})}>{data.demo.disconnected.includes(selected)?'Reconnect demo driver':'Simulate driver disconnect'}</button>}
  <details><summary>Roster &amp; identity</summary>{roster?<><div className="form-grid"><label>Display name<input value={roster.display_name} onChange={e=>setRoster({...roster,display_name:e.target.value})}/></label><label>Number<input value={roster.number} onChange={e=>setRoster({...roster,number:e.target.value})}/></label><label>Team<input value={roster.team} onChange={e=>setRoster({...roster,team:e.target.value})}/></label><label>Class<input value={roster.class_name} onChange={e=>setRoster({...roster,class_name:e.target.value})}/></label><label>Lap-counter baseline correction<input type="number" value={roster.baseline} onChange={e=>setRoster({...roster,baseline:e.target.value})}/></label><label>Grid position<input type="number" value={roster.grid} onChange={e=>setRoster({...roster,grid:e.target.value})}/></label></div><label>Driver / entry link · reassign for endurance driver changes<select value={roster.participant_id} onChange={e=>setRoster({...roster,participant_id:e.target.value})}>{admittedDrivers.map((p:any)=><option key={p.id} value={p.id}>{p.identity.display_name}{p.entry_id&&p.entry_id!==selected?' · linked to another entry':''}{p.status==='pending'?' · pending admission':''}</option>)}</select></label><label>Host notes<textarea value={roster.notes} onChange={e=>setRoster({...roster,notes:e.target.value})}/></label><button disabled={g.state==='running'&&roster.participant_id!==rawEntry.participant_id} onClick={()=>run('entries/'+selected,{identity:{display_name:roster.display_name,number:roster.number,team:roster.team,class_name:roster.class_name,driver_id:rawEntry.identity.driver_id,roster:rawEntry.identity.roster},baseline:roster.baseline===''?null:Number(roster.baseline),grid:roster.grid===''?null:Number(roster.grid),notes:roster.notes,participant_id:roster.participant_id},'PUT')}>Save roster changes</button><small className="subtle">Reassigning the driver link revokes the previous driver's lease.</small></>:<p className="subtle">Select a driver.</p>}</details>
  <details><summary>Steward decision</summary><div className="toolbar"><select aria-label="Decision type" value={penalty} onChange={e=>setPenalty(e.target.value)}>{['warning','investigation','time','laps','disqualification','order'].map(x=><option key={x}>{x}</option>)}</select><input aria-label="Penalty value" type="number" min="0" value={amount} onChange={e=>setAmount(Number(e.target.value))}/></div><div className="toolbar"><button disabled={!selected||!reason} onClick={()=>run('decisions',{entry_id:selected,kind:penalty,value:amount,reason,public:false})}>Record private decision</button><button disabled={!selected||!reason} onClick={()=>run('decisions',{entry_id:selected,kind:penalty,value:amount,reason,public:true})}>Record public decision</button></div><small>Uses the reason below. Public decisions of a popup kind (warning, investigation, time, laps, disqualification by default) auto-populate a penalty overlay.</small></details>
  <StewardCueQueue g={g} run={run}/></div>
  </div>

  <div className="rc-side"><details open><summary>Shared circuit map · {s.map_revision?.slice(0,8)||'—'}</summary><CircuitMap map={s.map_model||{points:s.map||[]}} markers={entries.filter((e:any)=>!e.stale&&e.fields?.position?.available).map((e:any)=>({id:e.entry_id,point:[e.fields.position.value[0],e.fields.position.value[2]],label:e.identity.number,selected:e.entry_id===selected}))}/><button onClick={()=>run('map/library',{})}>Use saved layout map</button></details>
  <FuelStrategyPanel g={g} run={run}/>
  <details><summary>Marshal zones ({g.zones.length})</summary><div className="event-list">{g.zones.map((z:any)=><div className="toolbar" key={z.id}><b>{z.name}</b><span>{Math.round(z.start*100)}% → {Math.round(z.end*100)}%</span><button disabled={g.state==='running'} onClick={()=>run('map',{points:s.map,zones:g.zones.filter((x:any)=>x.id!==z.id)},'PUT')}>Remove</button></div>)}{!g.zones.length&&<p className="subtle">None defined yet.</p>}</div><div className="form-grid"><label>Zone name<input value={zoneName} onChange={e=>setZoneName(e.target.value)}/></label><label>Start · %<input type="number" min={0} max={100} value={zoneStart} onChange={e=>setZoneStart(Number(e.target.value))}/></label><label>End · %<input type="number" min={0} max={100} value={zoneEnd} onChange={e=>setZoneEnd(Number(e.target.value))}/></label></div><button disabled={g.state==='running'||!zoneName||!s.map?.length} onClick={async()=>{if(await run('map',{points:s.map,zones:[...g.zones,{name:zoneName,start:zoneStart/100,end:zoneEnd/100}]},'PUT'))setZoneName('')}}>Add zone</button></details></div>
 </div>

 <h3 className="rc-section">Instructions</h3>
 <div className="rc-instruction-row">
  <div className="atem-bus rc-tight"><small>BUS</small><div className="atem-row">{[['global','FIELD'],['entry','DRIVER'],['zone','ZONE']].map(([v,label])=><button key={v} className={'atem-btn atem-bus-btn '+(scope===v?'live':'')} onClick={()=>setScope(v)}>{label}</button>)}</div>{scope==='zone'&&<select className="atem-zone-select" value={zone} onChange={e=>setZone(e.target.value)}><option value="">Choose zone</option>{g.zones.map((z:any)=><option key={z.id} value={z.id}>{z.name}</option>)}</select>}</div>
  <input aria-label="Reason" value={reason} onChange={e=>setReason(e.target.value)} placeholder="Reason shown to affected drivers" className="rc-reason"/>
  <input aria-label="Expires after seconds" type="number" min="5" max="3600" value={expiry} onChange={e=>setExpiry(Number(e.target.value))} className="rc-expiry" title="Expires after · seconds"/>
 </div>
 <div className="atem-bank rc-tight" ref={instructionBank}><small>INSTRUCTION</small><div className="atem-flags">{flags.map(flag=><button key={flag} className={'atem-flag-btn atem-flag-'+flag} disabled={scope!=='global'&&!target||scope!=='global'&&['safety_car','fcy','vsc'].includes(flag)} onClick={()=>run('instructions',{flag,scope,target,reason,expires_in:expiry})}>{flag.replaceAll('_',' ').toUpperCase()}</button>)}</div></div>
 <div className="event-list rc-tight">{g.instructions.filter((i:any)=>!i.cancelled&&(!i.expires||i.expires>s.timeline)).map((i:any)=><div className="toolbar" key={i.id}><b>{i.flag.toUpperCase()}</b><span>{i.scope} · {i.reason}</span><button onClick={()=>run('instructions/'+i.id,{},'DELETE')}>Cancel</button></div>)}</div>

 <div className="rc-grid rc-grid-messages">
  <div><h3 className="rc-section">Driver radio messages</h3><div className="toolbar"><select aria-label="Message recipients" value={messageScope} onChange={e=>setMessageScope(e.target.value)}><option value="all">All drivers</option><option value="entry">Selected driver</option><option value="team">Selected driver's team</option><option value="class">Selected driver's class</option></select>{['Acknowledge race control','Pit lane closed','Return to pits safely'].map(t=><button key={t} onClick={()=>setText(t)}>{t}</button>)}</div><label>Message<input value={text} onChange={e=>setText(e.target.value)}/></label><button disabled={!text||messageScope!=='all'&&!selected} onClick={()=>run('messages',{text,scope:messageScope,target:messageScope==='entry'?selected:messageScope==='team'?entry?.identity.team:messageScope==='class'?entry?.identity.class_name:'',public:messageScope==='all',acknowledgement:true,expires_in:expiry})}>Send · acknowledgement required</button><div className="event-list rc-tight">{g.messages.slice(-5).reverse().map((m:any)=><div className="event" key={m.id}><div><b>{m.text}</b><span className="receipt">{m.scope} · {m.expires<s.timeline?'Expired':'Active'} · {Object.values(m.receipts).filter((r:any)=>r.delivered).length}/{m.targets.length} delivered · {Object.values(m.receipts).filter((r:any)=>r.acknowledged).length} acknowledged</span>{data.demo&&m.expires>s.timeline&&m.targets.includes(selected)&&<button onClick={()=>run('demo',{action:'acknowledge',entry_id:selected,message_id:m.id})}>Simulate selected driver's acknowledgement</button>}</div></div>)}</div></div>
  <div><details><summary>Steward history ({g.decisions.length})</summary>{g.decisions.map((d:any)=><p key={d.id}>{d.kind} · {g.entries[d.entry_id]?.identity.display_name} · {d.reason} · {d.public?'Public':'Private'}</p>)}</details></div>
 </div></section>
}
