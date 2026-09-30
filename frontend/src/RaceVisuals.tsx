import React,{useEffect,useState} from 'react';
import imageIds from './carImages.json';
import {settingsApi,tracksApi} from './domain/api';
const carImages=new Set(imageIds);
type Props={settings:any,onSettings:(s:any)=>void,points:number[][],car:any,carId?:number,stale:boolean};
export function TrackSelect({tracks,value,onChange}:{tracks:any[],value:string,onChange:(id:string)=>void}){
 const venue=tracks.find(t=>t.layouts.some((l:any)=>l.id===value));
 return <div className="track-select"><label>Circuit<select aria-label="Circuit" value={venue?.id||''} onChange={e=>onChange(tracks.find(t=>t.id===e.target.value)?.layouts[0]?.id||'')}><option value="">Unassigned / learn a map</option>{tracks.map(t=><option value={t.id} key={t.id}>{t.name}</option>)}</select></label><label>Layout<select aria-label="Layout" value={value||''} disabled={!venue} onChange={e=>onChange(e.target.value)}>{!venue&&<option value="">Select a circuit</option>}{venue?.layouts.map((l:any)=><option value={l.id} key={l.id}>{l.name}</option>)}</select></label></div>
}
export function CircuitMap({map,trace=[],markers=[],showReference=true,showLearned=true,interactive=true,thick=false,emptyLabel}:{map:any,trace?:number[][],markers?:any[],showReference?:boolean,showLearned?:boolean,interactive?:boolean,thick?:boolean,emptyLabel?:string}){
 const learned=map?.points||[],aligned=map?.alignment?.status==='validated similarity fit',reference=showReference?(aligned?map.alignment.points:map?.reference?.points||[]):[];
 const separate=reference.length>1&&!aligned&&(learned.length>1||trace.length>1);
 const referenceOnly=reference.length>1&&!aligned&&!learned.length&&!trace.length;
 const outline=showLearned?learned:[],world=[...learned,...trace];
 const all=referenceOnly?reference:[...world,...(aligned?reference:[])];
 if(all.length<2)return <div className="empty-trace">{emptyLabel||'Drive a clean lap or select a layout to preview its reference.'}</div>;
 const cap=(ps:number[][],n:number)=>ps.length<=n?ps:ps.filter((_,i)=>i%Math.ceil(ps.length/n)===0);
 const xs=all.map((p:number[])=>p[0]),ys=all.map((p:number[])=>p[1]),minX=Math.min(...xs),minY=Math.min(...ys),width=Math.max(...xs)-minX,height=Math.max(...ys)-minY;
 const scale=Math.min(320/Math.max(width,1),220/Math.max(height,1)),project=(p:number[])=>[180+(p[0]-minX-width/2)*scale,130+(p[1]-minY-height/2)*scale];
 const route=(ps:number[][])=>cap(ps,600).map((p,i)=>(i?'L':'M')+project(p).join(',')).join('');const paths:Record<string,string>={'-1':'','0':'','1':''};
 const capped=cap(trace,600);
 for(let i=1;i<capped.length;i++){if(Math.hypot(capped[i][0]-capped[i-1][0],capped[i][1]-capped[i-1][1])>200)continue;const key=String(capped[i][2]||0);paths[key]+='M'+project(capped[i-1]).join(',')+'L'+project(capped[i]).join(',')}
 const end=trace.length?project(trace[trace.length-1]):null;
 let heading=null;
 if(trace.length>1){const a=project(trace[trace.length-2]),b=end as number[];const deg=Math.atan2(b[1]-a[1],b[0]-a[0])*180/Math.PI;heading=deg}
 const startPoint=outline.length>1?project(outline[0]):reference.length>1?project(reference[0]):null;
 let startDeg=0;
 if(outline.length>1){const a=project(outline[0]),b=project(outline[1]);startDeg=Math.atan2(b[1]-a[1],b[0]-a[0])*180/Math.PI+90}
 const w=thick?11:7,lw=thick?4.5:3,rw=thick?3:2;
 return <div className="shared-track-map"><svg className={'circuit-map '+(thick?'circuit-map-thick':'')} viewBox="0 0 360 260" role="img" aria-label={referenceOnly?'Approximate reference outline':'Position-derived circuit map and delta-colored driving line'}>
 {(aligned||referenceOnly)&&<path d={route(reference)} fill="none" stroke="#a58de0" strokeWidth={rw} strokeDasharray="5 3"/>}
 <path d={route(outline)} fill="none" stroke={thick?'#7a7a86':'#555560'} strokeWidth={w} strokeLinejoin="round" strokeLinecap="round"/>
 {showLearned&&Object.entries(paths).map(([key,d])=><path key={key} d={d} fill="none" stroke={key==='1'?'#25e58b':key==='-1'?'#ff354b':'#c5c5cd'} strokeWidth={lw}/>)}
 {startPoint&&<line x1={startPoint[0]-9*Math.cos(startDeg*Math.PI/180)} y1={startPoint[1]-9*Math.sin(startDeg*Math.PI/180)} x2={startPoint[0]+9*Math.cos(startDeg*Math.PI/180)} y2={startPoint[1]+9*Math.sin(startDeg*Math.PI/180)} stroke="#f4d34e" strokeWidth={thick?3:2}/>}
 {end&&<g transform={`translate(${end[0]},${end[1]}) rotate(${heading??0})`}>{heading!=null?<path d="M8,0 L-5,-6 L-1,0 L-5,6 Z" fill="#fff" stroke="#111" strokeWidth="1.5"/>:<circle r={thick?7:5} fill="white" stroke="#111" strokeWidth="2"/>}</g>}
 {!referenceOnly&&learned.length>1&&markers.map(m=>{const p=project(m.point);return <g key={m.id}><circle cx={p[0]} cy={p[1]} r="5" fill={m.selected?'#ff354b':'#25e58b'}/><text x={p[0]+7} y={p[1]-5} fill="white" fontSize="11">{m.label}</text></g>})}</svg>
 {referenceOnly&&<small>Approximate reference · alignment not verified</small>}
 {separate&&interactive&&<details><summary>Separate reference preview · alignment not verified</summary><CircuitMap map={{reference:map.reference}}/></details>}</div>
}
export function useTrackMap(){
 const [tracks,setTracks]=useState<any[]>([]),[map,setMap]=useState<any>(null),[error,setError]=useState('');
 useEffect(()=>{settingsApi.tracks().then(setTracks).catch(e=>setError(e.message));let active=true;const poll=()=>tracksApi.map().then(m=>{if(active)setMap(m)}).catch(e=>{if(active)setError(e.message)});poll();const timer=setInterval(poll,2000);return()=>{active=false;clearInterval(timer)}},[]);
 return {tracks,map,setMap,error};
}
export function MapCard({points,title,height}:{points:number[][],title?:string,height?:number}){
 const {map}=useTrackMap();
 return <section className="card map-card"><div className="card-top"><h3>{title||'Circuit & driving line'}</h3><span className="tiny-badge">{map?.status||'Recognizing'}</span></div><div style={height?{height}:undefined} className="map-card-body"><CircuitMap map={map} trace={points} interactive={false}/></div></section>;
}
export default function RaceVisuals({settings,onSettings,points,car,carId,stale}:Props){
 const {tracks,map,setMap,error:mapError}=useTrackMap();
 const [error,setError]=useState(''),[failed,setFailed]=useState(false),[reference,setReference]=useState(true),[learned,setLearned]=useState(true),[confirmation,setConfirmation]=useState('');
 useEffect(()=>{if(mapError)setError(mapError)},[mapError]);
 useEffect(()=>setFailed(false),[carId]);
 const hasImage=carId!=null&&carImages.has(carId)&&!failed;
 const venue=tracks.find(t=>t.layouts.some((l:any)=>l.id===map?.layout_id));
 async function action(call:()=>Promise<any>){try{setMap(await call());setError('')}catch(e:any){setError(e.message)}}
 async function select(id:string){await action(()=>tracksApi.select(id))}
 async function importMap(file?:File){if(!file)return;try{if(file.size>250000)throw Error('Map file exceeds 250 KB');const data=JSON.parse(await file.text());if(data.layout_id!==map?.layout_id)throw Error('The map layout must match the selected layout');setMap(await tracksApi.importMap(data.layout_id,data.points));setError('')}catch(e:any){setError(e.message)}}
 function exportMap(){const blob=new Blob([JSON.stringify(map,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`gt7-map-${map?.layout_id||'unassigned'}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 return <div className="race-visuals"><section className="card circuit-panel"><div className="card-top"><h3>Circuit & driving line</h3><span className="tiny-badge">{map?.status||'Recognizing'}</span></div>{venue&&<img className="circuit-logo" src={venue.logo} alt={`${venue.name} ${venue.logo_kind}`}/>}<TrackSelect tracks={tracks} value={map?.layout_id} onChange={select}/><div className="toolbar map-display-toggles"><label><input type="checkbox" checked={reference} onChange={e=>setReference(e.target.checked)}/> Reference outline</label><label><input type="checkbox" checked={learned} onChange={e=>setLearned(e.target.checked)}/> Learned line</label></div><CircuitMap map={map} trace={points} showReference={reference} showLearned={learned}/><div className="trace-legend"><span><i style={{background:'#25e58b'}}/>Gaining vs. reference</span><span><i style={{background:'#ff354b'}}/>Losing vs. reference</span><span><i style={{background:'#c5c5cd'}}/>No delta reference yet</span></div><div className="trace-footer"><small>{map?.kind||'Waiting for positions'}</small>{map?.corpus&&<small>{map.corpus.records?`Training data: ${map.corpus.records} recognized laps across ${map.corpus.layouts} layout${map.corpus.layouts===1?'':'s'}${map.corpus.full?' · corpus at its size limit':''}`:'Training data: no recognized laps logged yet'}</small>}</div><p className="subtle">{map?.reason} Outlines show driven routes, not track limits.</p>{map?.recognition?.candidates?.map((c:any)=><p key={c.layout_id} className="subtle">{c.name} · {c.source} · {c.evidence?.direction_agreement!=null?`${Math.round(c.evidence.direction_agreement*100)}% direction agreement`: 'shape suggestion; confirm identity'}</p>)}
 {map?.unnamed_candidates?.length>0&&<div className="map-confirmation"><h4>Confirm a learned layout</h4><TrackSelect tracks={tracks} value={confirmation} onChange={setConfirmation}/>{map.unnamed_candidates.map((c:any)=><p key={c.id}>Clean lap · {Math.round(c.quality.length_m)} m · {new Date(c.created*1000).toLocaleString()} {c.suggestions?.map((v:any)=><button key={v.layout_id} onClick={()=>setConfirmation(v.layout_id)}>Suggested: {v.name}</button>)} <button disabled={!confirmation} onClick={()=>action(()=>tracksApi.confirm(c.id,confirmation))}>Save this lap as selected layout</button></p>)}</div>}
 {map?.save_error&&<p role="alert">{map.save_error}</p>}{map?.save_pending&&<p>Saving map…</p>}
 {map?.versions?.length>0&&<label>Restore previous map<select aria-label="Restore previous map" value="" onChange={e=>e.target.value&&action(()=>tracksApi.restore(map.layout_id,e.target.value))}><option value="">Choose a revision</option>{map.versions.map((v:any)=><option key={v.revision} value={v.revision}>{v.revision} · {v.updated?new Date(v.updated*1000).toLocaleString():'Legacy map'}</option>)}</select></label>}
 <div className="toolbar"><button onClick={exportMap} disabled={!map?.points?.length}>Export map</button><label className="map-import">Import map JSON<input aria-label="Import map JSON" type="file" accept=".json,application/json" disabled={!map?.layout_id} onChange={e=>{importMap(e.target.files?.[0]);e.target.value=''}}/></label></div>{error&&<p role="alert">{error}</p>}</section><section className="card current-car-panel"><div className="card-top"><h3>Current car</h3><span className="tiny-badge">{stale?'LAST RECEIVED':'ONBOARD'}</span></div>{hasImage?<img className="current-car-image" src={`/cars/${carId}.png`} alt={car?.name||`Car ${carId}`} onError={()=>setFailed(true)}/>:<svg className="current-car-image" viewBox="0 0 400 180" role="img" aria-label="Generic vehicle illustration"><path d="M30 120L45 90 125 77 167 43 265 43 315 82 360 96 370 130H30Z" fill="#555560" stroke="#aaa" strokeWidth="3"/><path d="M140 76L175 50H255L285 78Z" fill="#17171d"/><circle cx="100" cy="130" r="29" fill="#111" stroke="#aaa" strokeWidth="7"/><circle cx="305" cy="130" r="29" fill="#111" stroke="#aaa" strokeWidth="7"/></svg>}<small>{car?.manufacturer||'Waiting for telemetry'}</small><h2>{car?.name||'Start driving to identify your car'}</h2><p className="subtle">{!hasImage?'Exact car image unavailable · generic illustration.':'Transparent catalogue image · your in-game livery and paint are not transmitted.'}</p></section></div>
}
