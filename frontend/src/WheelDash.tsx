import {useEffect,useRef,useState} from 'react';
import {X,ChevronLeft,ChevronRight,Fuel,Flag as FlagIcon,Settings2,ArrowUp,ArrowDown} from 'lucide-react';
import {gsap,pulse,flash,crossfade,countTo} from './motion';
import {CircuitMap,useTrackMap} from './RaceVisuals';
import {colors} from './colors';
import './WheelDash.css';
const fmt=(x:any,d=1)=>x==null?'—':Number(x).toFixed(d);
const lapTime=(ms:any)=>ms==null?'—':`${Math.floor(ms/60000)}:${(ms/1000%60).toFixed(3).padStart(6,'0')}`;
const ALL_PAGES=['RACE','TIMING','FUEL','TYRES','STRATEGY','MAP'] as const;
// Upstream GT7 flags bitfield (MacManley/gt7-udp layout). Bits 0/1/2/3/5/6 are exercised by
// this repo's own tests; 4/7/8/9/10/11 follow the same published upstream sequence, unverified here.
const BIT={onTrack:1,paused:2,loading:4,inGear:8,turbo:16,limiter:32,handbrake:64,lights:128,highBeam:256,lowBeam:512,asm:1024,tcs:2048};
function useWheelPages(){
 const [visible,setVisible]=useState<Record<string,boolean>>(()=>{try{const saved=JSON.parse(localStorage.getItem('wheelPages')||'null');if(saved)return saved}catch{}return Object.fromEntries(ALL_PAGES.map(p=>[p,true]))});
 useEffect(()=>{try{localStorage.setItem('wheelPages',JSON.stringify(visible))}catch{}},[visible]);
 const pages=ALL_PAGES.filter(p=>visible[p]!==false);
 return {pages:pages.length?pages:ALL_PAGES,visible,toggle:(p:string)=>setVisible(v=>({...v,[p]:v[p]===false}))};
}

function RpmDial({rpm,rpmMax,gear,speed,stale,gearRef,speedRef,rpmRef}:{rpm:number,rpmMax:number,gear:any,speed:number,stale:boolean,gearRef:any,speedRef:any,rpmRef:any}){
 const pct=Math.max(0,Math.min(1,(rpm||0)/(rpmMax||8000)));
 const ticks=Array.from({length:17},(_,i)=>i/16);
 const r=118,cx=140,cy=140;
 const angle=(t:number)=>-215+t*250;
 const point=(t:number,radius:number)=>{const a=angle(t)*Math.PI/180;return [cx+radius*Math.cos(a),cy+radius*Math.sin(a)]};
 const redline=pct>.86;
 return <div className="wd-dial-wrap">
  <svg className={'wd-dial '+(redline?'wd-dial-redline':'')} viewBox="0 0 280 280">
   {ticks.map((t,i)=>{const[x1,y1]=point(t,r),[x2,y2]=point(t,r-14);const lit=t<=pct;return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} className={lit?(t>.86?'wd-tick wd-tick-red':'wd-tick wd-tick-on'):'wd-tick'}/>})}
   <circle cx={cx} cy={cy} r={92} className="wd-dial-face"/>
  </svg>
  <div className="wd-dial-readout">
   <div ref={gearRef} className={'wd-gear '+(stale?'wd-dim':'')}>{gear==null?'—':gear===0?'R':gear}</div>
   <div className="wd-speed"><span ref={speedRef} data-v="0">{fmt(speed,0)}</span><small> km/h</small></div>
   <div className="wd-rpm-label"><span ref={rpmRef} data-v="0">{fmt(rpm,0)}</span> / {fmt(rpmMax,0)} RPM</div>
  </div>
 </div>;
}

function ShiftLights({rpm,rpmMin,rpmMax,limiter}:{rpm:number,rpmMin:number,rpmMax:number,limiter:boolean}){
 const lo=rpmMin||rpm*.7||4000,hi=rpmMax||8000;
 const pct=Math.max(0,Math.min(1,((rpm||0)-lo)/Math.max(1,hi-lo)));
 const n=20,lit=Math.round(pct*n);
 return <div className={'wd-shiftstrip '+(limiter?'wd-shiftstrip-flash':'')}>{Array.from({length:n},(_,i)=><div key={i} className={'wd-shiftled '+(i<lit?(i>n-4?'wd-led-red':i>n-9?'wd-led-amber':'wd-led-green'):'')}/>)}</div>;
}
function Lamp({on,label,color}:{on:boolean,label:string,color?:string}){
 return <div className={'wd-lamp '+(on?'wd-lamp-on':'')} style={on&&color?{color,borderColor:color}:undefined}><small>{label}</small></div>;
}
function tyreClass(t?:number){return t==null?'wd-dim':t>100?'wd-bad':t<60?'wd-dim':'wd-good'}
function isHeating(heat:any,i:number){return heat&&!heat.stale&&heat.rates?.[i]!=null&&heat.rates[i]>=.15&&heat.anomalies?.[i]!=null&&heat.anomalies[i]>=4}
function spread(tyres?:number[],a?:number[],b?:number[]){
 if(!tyres||!a||!b||tyres.some(t=>t==null))return '—';
 const av=(tyres[a[0]]+tyres[a[1]])/2,bv=(tyres[b[0]]+tyres[b[1]])/2;
 return `${(av-bv>=0?'+':'')}${(av-bv).toFixed(1)} °C`;
}
function CircuitMapMini({points,status}:{points:number[][],status:string}){
 const {map}=useTrackMap();
 return <div className="wd-mini-map"><CircuitMap map={map} trace={points} interactive={false} thick emptyLabel="TRACK UNKNOWN"/><small className="wd-mini-map-status">{status}</small></div>;
}
function CircuitMapFull({points}:{points:number[][]}){
 const {map}=useTrackMap();
 return <CircuitMap map={map} trace={points} interactive={false} thick emptyLabel="TRACK UNKNOWN — drive a clean lap to start recognition"/>;
}
export default function WheelDash({state,settings,onExit}:{state:any,settings:any,onExit:()=>void}){
 const {pages:PAGES,visible,toggle}=useWheelPages();
 const [page,setPage]=useState(0);
 const [showSettings,setShowSettings]=useState(false);
 const v=state?.sample?.values||{}, stale=state?.stale!==false, fuel=state?.fuel;
 const delta=state?.live_delta;
 const gearRef=useRef<HTMLDivElement>(null),speedRef=useRef<HTMLSpanElement>(null),rpmRef=useRef<HTMLSpanElement>(null);
 const lapRef=useRef<HTMLElement>(null),pageRef=useRef<HTMLDivElement>(null),deltaRef=useRef<HTMLElement>(null);
 const prevGear=useRef<any>(undefined),prevLap=useRef<any>(undefined);
 useEffect(()=>{if(page>=PAGES.length)setPage(0)},[PAGES.length]);
 const next=()=>setPage(p=>(p+1)%PAGES.length), prev=()=>setPage(p=>(p-1+PAGES.length)%PAGES.length);
 useEffect(()=>{
  const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')onExit();else if(e.key==='ArrowRight')next();else if(e.key==='ArrowLeft')prev()};
  window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey);
 },[PAGES.length]);
 useEffect(()=>{crossfade(pageRef.current)},[page]);
 useEffect(()=>{countTo(speedRef.current,v.speed_kmh||0,0)},[v.speed_kmh]);
 useEffect(()=>{countTo(rpmRef.current,v.rpm||0,0)},[v.rpm]);
 useEffect(()=>{if(prevGear.current!==undefined&&prevGear.current!==v.gear)pulse(gearRef.current);prevGear.current=v.gear},[v.gear]);
 useEffect(()=>{if(prevLap.current!==undefined&&prevLap.current!==v.lap)flash(lapRef.current,'#f4d34e');prevLap.current=v.lap},[v.lap]);
 useEffect(()=>{if(deltaRef.current)gsap.fromTo(deltaRef.current,{scale:1.15},{scale:1,duration:.4,ease:'power2.out'})},[delta?.delta_s!=null&&Math.round(delta.delta_s*10)]);
 const flagBits=v.flags||0;
 const status=stale?'NO SIGNAL':flagBits&BIT.loading?'LOADING':flagBits&BIT.paused?'PAUSED':flagBits&BIT.onTrack?'ON TRACK':'OFF TRACK';
 const statusClass=stale?'':status==='ON TRACK'?'wd-flag-green':status==='PAUSED'?'wd-flag-yellow':status==='LOADING'?'wd-flag-blue':'wd-flag-red';
 const deltaColor=delta?.available?(delta.delta_s<0?'wd-good':'wd-bad'):'';
 const car=state?.car?.name||(v.car_id?`Car ${v.car_id}`:'Awaiting car'), track=state?.track_selection?.name||'Recognizing track';
 const hasTurbo=!!(flagBits&BIT.turbo), boost=v.boost!=null?v.boost-1:null;
 const shiftHint=v.suggested_gear!=null&&v.gear!=null?(v.suggested_gear>v.gear?'up':v.suggested_gear<v.gear?'down':null):null;
 const overlap=state?.live_analysis?.overlap_percent;
 const mapStatus=state?.track_selection?.status||'Recognizing';
 return <div className={'wd-shell '+(stale?'wd-stale':'')}>
  <div className="wd-topbar">
   <span className="wd-lap" ref={lapRef as any}>LAP <b>{v.lap??'—'}{v.total_laps?<small> / {v.total_laps}</small>:null}</b></span>
   <span className="wd-track">{track} <i>·</i> {car}</span>
   <span className={'wd-flagpill '+statusClass}>{status}</span>
   {state?.box&&<span className="wd-flagpill wd-flag-yellow"><FlagIcon size={11}/> BOX THIS LAP</span>}
   <span className="wd-hz">{fmt(state?.health?.rate_hz,0)} Hz</span>
   <span className={'wd-live '+(stale?'':'wd-live-on')}>{stale?'NO SIGNAL':state?.source==='demo'?'DEMO':state?.source==='replay'?'REPLAY':'LIVE'}</span>
   <button className="wd-exit" onClick={()=>setShowSettings(s=>!s)} aria-label="Wheel page settings"><Settings2 size={16}/></button>
   <button className="wd-exit" onClick={onExit} aria-label="Exit wheel display"><X size={18}/></button>
  </div>
  {state?.subtitle&&<div className="wd-message">{state.subtitle}</div>}
  {showSettings&&<div className="wd-settings"><small>WHEEL PAGES</small><div className="wd-settings-grid">{ALL_PAGES.map(p=><label key={p}><input type="checkbox" checked={visible[p]!==false} onChange={()=>toggle(p)}/>{p}</label>)}</div></div>}
  <div className="wd-page" ref={pageRef}>
   {PAGES[page]==='RACE'&&<div className="wd-race">
    <ShiftLights rpm={v.rpm} rpmMin={v.rpm_min} rpmMax={v.rpm_max} limiter={!!(flagBits&BIT.limiter)}/>
    <div className="wd-race-top">
     <div className="wd-col wd-col-left">
      <div className="wd-vbars-row">
       <div className="wd-vstat"><small>THR</small><div className="wd-vbar"><div className="wd-vbar-fill wd-throttle" style={{height:`${(v.throttle||0)*100}%`}}/></div></div>
       <div className="wd-vstat"><small>BRK</small><div className="wd-vbar"><div className="wd-vbar-fill wd-brake" style={{height:`${(v.brake||0)*100}%`}}/></div></div>
       <div className="wd-vstat"><small>CLU</small><div className="wd-vbar"><div className="wd-vbar-fill wd-clutch" style={{height:`${(v.clutch||0)*100}%`}}/></div></div>
      </div>
      <div className="wd-mini-stat-row">
       {overlap!=null&&<div className="wd-mini-stat"><small>OVERLAP</small><b>{fmt(overlap)}%</b></div>}
       {hasTurbo&&<div className="wd-mini-stat"><small>BOOST</small><b>{fmt(boost,2)}</b></div>}
      </div>
     </div>
     <div className="wd-dial-col">
      <RpmDial rpm={v.rpm} rpmMax={v.rpm_max||8000} gear={v.gear} speed={v.speed_kmh} stale={stale} gearRef={gearRef} speedRef={speedRef} rpmRef={rpmRef}/>
      {shiftHint&&<div className={'wd-shift-hint '+(shiftHint==='up'?'wd-good':'wd-bad')}>{shiftHint==='up'?<ArrowUp size={14}/>:<ArrowDown size={14}/>}SHIFT {shiftHint}</div>}
     </div>
     <div className="wd-col wd-col-right">
      <div className="wd-corner" ref={deltaRef as any}><small>DELTA</small><b className={deltaColor}>{delta?.available&&!stale?`${delta.delta_s>0?'+':''}${fmt(delta.delta_s,2)}`:'—'}</b></div>
      <div className="wd-corner"><small>LAST</small><b>{lapTime(v.last_ms)}</b></div>
      <div className="wd-corner"><small>BEST</small><b className="wd-good">{lapTime(v.best_ms)}</b></div>
     </div>
    </div>
    <div className={'wd-delta-bar wd-race-delta '+deltaColor}><div style={{width:`${Math.min(100,Math.abs((delta?.delta_s||0))*20)}%`}}/></div>
    <div className="wd-lamprow">
     <Lamp on={!!(flagBits&BIT.tcs)} label="TCS"/>
     <Lamp on={!!(flagBits&BIT.asm)} label="ASM"/>
     <Lamp on={!!(flagBits&BIT.limiter)} label="LIMITER" color={colors.brake}/>
     <Lamp on={!!(flagBits&BIT.handbrake)} label="H-BRAKE" color={colors.brake}/>
     <Lamp on={!!(flagBits&BIT.lights)} label="LIGHTS"/>
     <Lamp on={!!(flagBits&BIT.highBeam)} label="HIGH"/>
     <Lamp on={!!(flagBits&BIT.lowBeam)} label="LOW"/>
     <Lamp on={!!(flagBits&BIT.inGear)} label="IN GEAR" color={colors.personal}/>
    </div>
    <div className="wd-tilerow">
     <div className="wd-tile wd-tile-map"><CircuitMapMini points={state?.trace||[]} status={mapStatus}/></div>
     <div className="wd-tile"><small>FUEL</small><b className={fuel?.margin_l<0?'wd-bad':'wd-good'}>{fmt(v.fuel,1)} L</b><span className="wd-tile-sub">{fmt(fuel?.laps_remaining)} laps left</span></div>
     <div className="wd-tile wd-tile-tyres">{['FL','FR','RL','RR'].map((label,i)=><div className="wd-tyre-mini" key={label}><small>{label}</small><b className={tyreClass(v.tyres?.[i])}>{fmt(v.tyres?.[i],0)}°</b>{isHeating(state?.tyre_heat,i)&&<span className="wd-heating" title="Heating fast">▲</span>}</div>)}</div>
     <div className="wd-tile wd-tile-dyn">
      <div><small>LONG G</small><b>{state?.live_analysis?.stale?'—':fmt(state?.live_analysis?.longitudinal_g,2)}</b></div>
      <div className="wd-slip-row"><small>SLIP</small>{['FL','FR','RL','RR'].map((label,i)=>{const r=v.wheel_speed_ratio?.[i];const cls=r==null?'wd-dim':r>1.06?'wd-bad':r<.94?'wd-bad':'wd-good';return <span key={label} className={cls} title={label}>{r==null?'—':fmt((r-1)*100,0)}</span>})}</div>
     </div>
    </div>
   </div>}
   {PAGES[page]==='TIMING'&&<div className="wd-timing">
    <div className="wd-timing-main">
     <small>CURRENT LAP {v.lap??'—'}</small>
     <div className="wd-timing-big">{settings?.trust_c_fields?lapTime(v.current_ms):'—'}</div>
     <div className={'wd-delta-bar '+deltaColor}><div style={{width:`${Math.min(100,Math.abs((delta?.delta_s||0))*20)}%`}}/></div>
     <span className="wd-subtle">{delta?.available&&!stale?`${delta.delta_s>0?'+':''}${fmt(delta.delta_s,3)} s vs personal best`:'No delta reference yet'}</span>
    </div>
    <div className="wd-timing-rows">
     <div className="wd-row"><span>Last lap</span><b>{lapTime(v.last_ms)}</b></div>
     <div className="wd-row"><span>Personal best</span><b className="wd-good">{lapTime(v.best_ms)}</b></div>
     <div className="wd-row"><span>Lap count</span><b>{v.lap??'—'}{v.total_laps?` / ${v.total_laps}`:''}</b></div>
     <div className="wd-row"><span>Predicted lap</span><b className="wd-dim">Not calculated</b></div>
     <div className="wd-row"><span>Overall fastest</span><b className="wd-dim">Not transmitted</b></div>
     <div className="wd-row"><span>Sectors</span><b className="wd-dim">Not transmitted</b></div>
    </div>
   </div>}
   {PAGES[page]==='FUEL'&&<div className="wd-fuel">
    <div className="wd-fuel-main">
     <small>{fuel?.available?'FINISH MARGIN':'LEARNING FUEL MODEL'}</small>
     <div className={'wd-fuel-big '+(fuel?.margin_l<0?'wd-bad':'wd-good')}>{fmt(fuel?.margin_l)}<span> L</span></div>
     <span className="wd-subtle">{fuel?.reason||'Needs clean fuel laps to calibrate.'}</span>
    </div>
    <div className="wd-timing-rows">
     <div className="wd-row"><span>Consumption / lap</span><b>{fmt(fuel?.litres_per_lap,2)} L</b></div>
     <div className="wd-row"><span>Estimated laps left</span><b>{fmt(fuel?.laps_remaining)}</b></div>
     <div className="wd-row"><span>Tank</span><b>{fmt(v.fuel,1)} / {fmt(v.fuel_capacity,0)} L</b></div>
     <div className="wd-row"><span>Tank %</span><b>{v.fuel_capacity?fmt(v.fuel/v.fuel_capacity*100,0):'—'}%</b></div>
     <div className="wd-row"><span>Saving required</span><b className={fuel?.save_percent>0?'wd-bad':''}>{fmt(fuel?.save_percent)}%</b></div>
    </div>
    <div className="wd-fuel-gauge"><div style={{width:`${Math.min(100,(v.fuel||0)/(v.fuel_capacity||100)*100)}%`}}/></div>
   </div>}
   {PAGES[page]==='TYRES'&&<div className="wd-fuel">
    <div className="wd-fuel-main"><small>SURFACE TEMPERATURE</small><span className="wd-subtle">Surface temperature ≠ tyre wear. No optimum assumed.</span></div>
    <div className="wd-tyres wd-tyres-big">{['FL','FR','RL','RR'].map((label,i)=><div className="wd-tyre wd-tyre-big" key={label}><small>{label}{isHeating(state?.tyre_heat,i)&&<span className="wd-heating" title="Heating fast"> ▲ heating</span>}</small><b className={tyreClass(v.tyres?.[i])}>{fmt(v.tyres?.[i],0)}<span>°C</span></b></div>)}</div>
    <div className="wd-timing-rows">
     <div className="wd-row"><span>Front / rear spread</span><b>{spread(v.tyres,[0,1],[2,3])}</b></div>
     <div className="wd-row"><span>Left / right spread</span><b>{spread(v.tyres,[0,2],[1,3])}</b></div>
     <div className="wd-row"><span>Suspension travel (m)</span><b>{v.suspension?v.suspension.map((s:number)=>fmt(s,3)).join(' / '):'—'}</b></div>
    </div>
   </div>}
   {PAGES[page]==='STRATEGY'&&<div className="wd-timing">
    <div className="wd-timing-rows">
     <div className="wd-row"><span>Race distance</span><b>{settings?.race_laps?`${settings.race_laps} laps`:settings?.race_minutes?`${settings.race_minutes} min`:'Not set'}</b></div>
     <div className="wd-row"><span>Remaining distance</span><b>{fmt(fuel?.remaining_distance_laps,2)} laps</b></div>
     <div className="wd-row"><span>Saving required</span><b className={fuel?.save_percent>0?'wd-bad':''}>{fmt(fuel?.save_percent)} %</b></div>
     <div className="wd-row"><span>Suggested refuel</span><b>{fmt(fuel?.refuel_l)} L</b></div>
     <div className="wd-row"><span>Pit intent</span><b className={state?.box?'wd-bad':''}>{state?.box?'Marked':'Not marked'}</b></div>
    </div>
   </div>}
   {PAGES[page]==='MAP'&&<div className="wd-map-page">
    <div className="wd-map-header">
     <span className="wd-track">{track}</span>
     <span className={'wd-flagpill '+(mapStatus==='Saved map'?'wd-flag-green':mapStatus==='Recognizing'?'wd-flag-yellow':'')}>{mapStatus}</span>
     <span className="wd-subtle">Lap {v.lap??'—'} · Corner/sector not transmitted</span>
    </div>
    <div className="wd-map-full"><CircuitMapFull points={state?.trace||[]}/></div>
    <div className="wd-map-footer">
     <div><small>DELTA</small><b className={deltaColor}>{delta?.available&&!stale?`${delta.delta_s>0?'+':''}${fmt(delta.delta_s,2)} s`:'—'}</b></div>
     <div><small>LAST</small><b>{lapTime(v.last_ms)}</b></div>
     <div><small>BEST</small><b className="wd-good">{lapTime(v.best_ms)}</b></div>
    </div>
   </div>}
  </div>
  <div className="wd-pager">
   <button onClick={prev} aria-label="Previous page"><ChevronLeft size={18}/></button>
   {PAGES.map((p,i)=><button key={p} className={'wd-dot '+(i===page?'active':'')} onClick={()=>setPage(i)}>{p}</button>)}
   <button onClick={next} aria-label="Next page"><ChevronRight size={18}/></button>
  </div>
 </div>;
}
