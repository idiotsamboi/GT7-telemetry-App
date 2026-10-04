// OBS Overlays: replaces the old Studio (draft / program / preview). Every overlay has a fixed local
// address; this page copies it, sets its size, and sets the driver focus shared by all overlays.
import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {Copy,RotateCcw,Check} from 'lucide-react';
import {obsApi,type ObsConfig,type ObsOverlay,type ObsState} from './domain/api/obs';
import GroupControl from './GroupControl';
import './ObsOverlays.css';
const TUTORIAL_KEY='obs:tutorial:hidden';
const MIN_W=100,MIN_H=40,MAX_W=3840,MAX_H=2160;
const clamp=(n:number,lo:number,hi:number)=>Math.min(hi,Math.max(lo,Math.round(n)));
const CATEGORY_LABEL:Record<string,string>={timing:'Timing',session:'Session',race_control:'Race control',driver:'Driver',telemetry:'Telemetry',map:'Map',results:'Results',branding:'Branding',strategy:'Strategy'};

function SizeFrame({overlay,onChange}:{overlay:ObsOverlay,onChange:(w:number,h:number)=>void}){
 // The box is centred, so dragging a left/right edge grows both sides and a top/bottom edge grows both ends.
 const AREA_W=300,AREA_H=190,scale=Math.min((AREA_W-30)/(overlay.default_width*1.8),(AREA_H-50)/(overlay.default_height*1.8));
 const drag=useRef<{x:number,y:number,w:number,h:number,axis:'x'|'y'|'xy'}|null>(null);
 const start=(axis:'x'|'y'|'xy')=>(e:React.PointerEvent)=>{e.preventDefault();(e.target as HTMLElement).setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,w:overlay.width,h:overlay.height,axis}};
 const move=(sx:1|-1,sy:1|-1)=>(e:React.PointerEvent)=>{
  const d=drag.current;if(!d)return;
  const w=d.axis==='y'?d.w:clamp(d.w+sx*2*(e.clientX-d.x)/scale,MIN_W,MAX_W),h=d.axis==='x'?d.h:clamp(d.h+sy*2*(e.clientY-d.y)/scale,MIN_H,MAX_H);
  onChange(w,h);
 };
 const end=()=>{drag.current=null};
 const boxW=Math.min(AREA_W-30,overlay.width*scale),boxH=Math.min(AREA_H-50,overlay.height*scale);
 const handle=(cls:string,axis:'x'|'y'|'xy',sx:1|-1,sy:1|-1,label:string)=><span role="slider" aria-label={label} className={'obs-handle '+cls} onPointerDown={start(axis)} onPointerMove={move(sx,sy)} onPointerUp={end} onPointerCancel={end}/>;
 return <div className="obs-size-area" style={{width:AREA_W,height:AREA_H}}>
  <span className="obs-size-readout">{overlay.width} × {overlay.height} px · drag any edge</span>
  <div className="obs-size-box" style={{width:boxW,height:boxH,marginBottom:22}}>
   {handle('left','x',-1,1,'Resize width from the left edge')}{handle('right','x',1,1,'Resize width from the right edge')}
   {handle('top','y',1,-1,'Resize height from the top edge')}{handle('bottom','y',1,1,'Resize height from the bottom edge')}
   {handle('corner','xy',1,1,'Resize width and height')}
  </div>
 </div>;
}

function OverlayRow({overlay,onSize,onSettings,onReset}:{overlay:ObsOverlay,onSize:(w:number,h:number)=>void,onSettings:(s:ObsOverlay['settings'])=>void,onReset:()=>void}){
 const [open,setOpen]=useState(false),[copied,setCopied]=useState(false);
 const copy=async()=>{try{await navigator.clipboard.writeText(overlay.url);setCopied(true);setTimeout(()=>setCopied(false),1500)}catch{}};
 const changed=overlay.width!==overlay.default_width||overlay.height!==overlay.default_height;
 return <div className="obs-row">
  <div className="obs-row-main">
   <strong>{overlay.name}</strong>
   <input className="obs-url" readOnly value={overlay.url} aria-label={overlay.name+' address'} onFocus={e=>e.currentTarget.select()}/>
   <button onClick={copy} aria-label={'Copy '+overlay.name+' address'}>{copied?<><Check size={14}/>Copied</>:<><Copy size={14}/>Copy</>}</button>
   <button className="ghost" aria-expanded={open} onClick={()=>setOpen(!open)}>{overlay.width}×{overlay.height} · Size &amp; options</button>
  </div>
  {open&&<div className="obs-row-detail">
   <SizeFrame overlay={overlay} onChange={onSize}/>
   <div className="obs-row-fields">
    <div className="obs-dims"><label>Width<input type="number" min={MIN_W} max={MAX_W} value={overlay.width} onChange={e=>onSize(clamp(Number(e.target.value)||overlay.width,MIN_W,MAX_W),overlay.height)}/></label><label>Height<input type="number" min={MIN_H} max={MAX_H} value={overlay.height} onChange={e=>onSize(overlay.width,clamp(Number(e.target.value)||overlay.height,MIN_H,MAX_H))}/></label>
    <button className="ghost" disabled={!changed} onClick={onReset}><RotateCcw size={13}/>Default size</button></div>
    <p className="subtle">Set the same numbers as the OBS Browser Source width and height. Resizing the source in OBS later also rescales the overlay on both axes.</p>
    <div className="obs-dims">
     <label>Title<input value={overlay.settings.title??''} maxLength={160} placeholder="Default" onChange={e=>onSettings({...overlay.settings,title:e.target.value||undefined})}/></label>
     <label>Rows<input type="number" min={1} max={32} value={overlay.settings.rows??''} placeholder="Auto" onChange={e=>onSettings({...overlay.settings,rows:e.target.value?clamp(Number(e.target.value),1,32):undefined})}/></label>
     <label>Opacity<input type="number" min={0} max={1} step={0.05} value={overlay.settings.opacity??''} placeholder="1" onChange={e=>onSettings({...overlay.settings,opacity:e.target.value===''?undefined:Math.min(1,Math.max(0,Number(e.target.value)))})}/></label>
    </div>
    {overlay.sharing.some(s=>s!=='basic')&&<p className="subtle">Needs {overlay.sharing.filter(s=>s!=='basic').join(' + ')} data. Shows “Unavailable” when that isn’t reported.</p>}
   </div>
  </div>}
 </div>;
}

export default function ObsOverlays(){
 const [state,setState]=useState<ObsState|null>(null),[config,setConfig]=useState<ObsConfig|null>(null),[error,setError]=useState(''),[saved,setSaved]=useState(false);
 const [hideTutorial,setHideTutorial]=useState(()=>{try{return localStorage.getItem(TUTORIAL_KEY)==='1'}catch{return false}});
 const [leagueTools,setLeagueTools]=useState(false);
 const dirty=useRef(false),timer=useRef<any>(null);
 const load=useCallback(async(first=false)=>{try{const s=await obsApi.state();setState(s);if(first||!dirty.current)setConfig(s.config);setError('')}catch(e:any){setError(e.message||'Could not load overlays')}},[]);
 useEffect(()=>{load(true);const t=setInterval(()=>load(),2000);return()=>{clearInterval(t);clearTimeout(timer.current)}},[load]);
 const persist=useCallback((next:ObsConfig)=>{
  dirty.current=true;setConfig(next);setSaved(false);clearTimeout(timer.current);
  timer.current=setTimeout(async()=>{try{const s=await obsApi.save(next);dirty.current=false;setState(s);setSaved(true);setError('')}catch(e:any){dirty.current=false;setError(e.message||'Could not save')}},400);
 },[]);
 const overlays=useMemo(()=>(state?.overlays||[]).map(o=>{const size=config?.sizes[o.id];return {...o,width:size?.width??o.default_width,height:size?.height??o.default_height,settings:config?.settings[o.id]??{}}}),[state,config]);
 const groups=useMemo(()=>{const m=new Map<string,ObsOverlay[]>();overlays.forEach(o=>{m.set(o.category,[...(m.get(o.category)||[]),o])});return [...m.entries()]},[overlays]);
 if(!state||!config)return <div className="obs-page card">{error?<p role="alert" className="amber-text">{error}</p>:<p className="subtle">Loading overlays…</p>}</div>;
 const solo=state.mode==='solo',drivers=state.drivers,focus=config.focus;
 const setFocus=(patch:Partial<ObsConfig['focus']>)=>persist({...config,focus:{...focus,...patch}});
 const setIdentity=(patch:Partial<ObsConfig['identity']>)=>persist({...config,identity:{...config.identity,...patch}});
 const setSize=(id:string,w:number,h:number)=>persist({...config,sizes:{...config.sizes,[id]:{width:w,height:h}}});
 const resetSize=(id:string)=>{const sizes={...config.sizes};delete sizes[id];persist({...config,sizes})};
 const setSettings=(id:string,s:ObsOverlay['settings'])=>{const clean=Object.fromEntries(Object.entries(s).filter(([,v])=>v!==undefined&&v!=='')),settings={...config.settings};if(Object.keys(clean).length)settings[id]=clean;else delete settings[id];persist({...config,settings})};
 const picker=(value:string,onChange:(v:string)=>void,empty:string,disabled=false)=><select value={value} disabled={disabled} onChange={e=>onChange(e.target.value)}><option value="">{empty}</option>{drivers.map(d=><option key={d.entry_id} value={d.entry_id}>{d.label}{d.stale?' (no data)':''}</option>)}</select>;
 const teams=[...new Set(drivers.map(d=>d.team).filter(Boolean))],classes=[...new Set(drivers.map(d=>d.class_name).filter(Boolean))];
 return <div className="obs-page">
  <header className="obs-head">
   <div><p className="subtle">Every overlay already has its own address. Paste it into an OBS Browser Source — no league, login or setup needed.</p></div>
   <span className={'badge '+(solo?'':'amber')}>{solo?'Local driver · your own telemetry':`League: ${state.group_name||'active event'}`}</span>
  </header>
  {error&&<p role="alert" className="amber-text">{error}</p>}

  <section className="card obs-tutorial">
   <div className="obs-tutorial-head"><h3>Add an overlay to OBS</h3><button className="ghost" onClick={()=>{const next=!hideTutorial;setHideTutorial(next);try{localStorage.setItem(TUTORIAL_KEY,next?'1':'0')}catch{}}}>{hideTutorial?'Show steps':'Hide steps'}</button></div>
   {!hideTutorial&&<ol>
    <li>In OBS, under <b>Sources</b>, click <b>+</b> and choose <b>Browser</b>.</li>
    <li>Paste an overlay’s address into <b>URL</b> (use <b>Copy</b> below). Example: <code>{state.base_url}/obs/timing</code>.</li>
    <li>Set <b>Width</b> and <b>Height</b> to the numbers on that overlay’s row (open <b>Size &amp; options</b> to change them) and <b>FPS</b> to 30. The background is transparent automatically.</li>
    <li>Start GT7 telemetry. The overlay fills in as data arrives; it stays blank rather than guessing when there’s none.</li>
    <li>Resize either dimension later by dragging the box’s edges here (both sides move together) or by resizing the source in OBS — the overlay rescales to fit.</li>
   </ol>}
   {!hideTutorial&&<p className="subtle">OBS on another PC? Open this app using this computer’s LAN address (for example <code>http://192.168.1.20:8000</code>) and the copied addresses will use it. Add that address to the app’s allowed origins in Settings first. Append <code>?fit=stretch</code> to fill an odd-shaped source without keeping proportions.</p>}
  </section>

  <section className="card">
   <h3>Driver focus <small className="subtle">· applies to every overlay</small></h3>
   <div className="obs-focus">
    <label>Main driver{picker(focus.primary_mode==='leader'?'':focus.primary,v=>setFocus({primary:v,primary_mode:'manual'}),solo?'You':'Automatic',focus.primary_mode==='leader')}</label>
    <label>Compare driver A{picker(focus.a,v=>setFocus({a:v}),'Same as main driver')}</label>
    <label>Compare driver B{picker(focus.b,v=>setFocus({b:v}),'None',solo)}</label>
    <label>Team{<select value={focus.team} onChange={e=>setFocus({team:e.target.value})}><option value="">Main driver’s team</option>{teams.map(t=><option key={t} value={t}>{t}</option>)}</select>}</label>
    <label>Class{<select value={focus.class} onChange={e=>setFocus({class:e.target.value})}><option value="">All classes</option>{classes.map(t=><option key={t} value={t}>{t}</option>)}</select>}</label>
    <label className="obs-check"><input type="checkbox" disabled={solo} checked={focus.primary_mode==='leader'} onChange={e=>setFocus({primary_mode:e.target.checked?'leader':'manual'})}/>Follow the race leader</label>
   </div>
   {solo&&<p className="subtle">Telemetry from GT7 covers only your own car, so comparisons and standings fill in when you host or join a league event. Until then the main driver is you.</p>}
   <h4>Your name on overlays</h4>
   <div className="obs-focus">
    <label>Display name<input value={config.identity.display_name} maxLength={80} onChange={e=>setIdentity({display_name:e.target.value})}/></label>
    <label>Number<input value={config.identity.number} maxLength={8} onChange={e=>setIdentity({number:e.target.value})}/></label>
    <label>Team<input value={config.identity.team} maxLength={160} onChange={e=>setIdentity({team:e.target.value})}/></label>
    <label>Class<input value={config.identity.class_name} maxLength={160} onChange={e=>setIdentity({class_name:e.target.value})}/></label>
   </div>
   <p className="subtle" role="status">{saved?'Saved — overlays update within a second.':'Changes save automatically.'}</p>
  </section>

  {groups.map(([category,rows])=><section className="card" key={category}>
   <h3>{CATEGORY_LABEL[category]||category}</h3>
   {rows.map(o=><OverlayRow key={o.id} overlay={o} onSize={(w,h)=>setSize(o.id,w,h)} onSettings={s=>setSettings(o.id,s)} onReset={()=>resetSize(o.id)}/>)}
  </section>)}

  <section className="card">
   <div className="obs-tutorial-head"><div><h3>League tools <small className="subtle">· optional</small></h3><p className="subtle">Leagues are not needed for overlays. Host an event here to fill the timing tower and comparisons with other drivers — the same overlay addresses keep working. Includes LAN hosting, invitations, replay and league branding.</p></div><button className="ghost" aria-expanded={leagueTools} onClick={()=>setLeagueTools(!leagueTools)}>{leagueTools?'Hide':'Open'}</button></div>
   {leagueTools&&<GroupControl mode="league"/>}
  </section>
 </div>;
}
