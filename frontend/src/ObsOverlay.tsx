// The page an OBS Browser Source loads: /obs/<graphic-id>. No league, token or setup needed - it polls the
// local app's read-only frame and draws one graphic scaled to whatever size the browser source is given,
// so resizing the source in OBS (either axis) resizes the overlay.
import {useEffect,useRef,useState} from 'react';
import {obsApi,type ObsFrame} from './domain/api/obs';
import {GraphicView} from './GroupGraphics';
const POLL_MS=250;
const STALE_AFTER_MS=5000;
const TRACE_MAX=2000;

export default function ObsOverlay(){
 const graphic=decodeURIComponent(location.pathname.split('/')[2]||'');
 const params=new URLSearchParams(location.search);
 const stretch=params.get('fit')==='stretch';
 const [frame,setFrame]=useState<ObsFrame|null>(null),[viewport,setViewport]=useState({w:innerWidth,h:innerHeight});
 const trace=useRef<number[][]>([]);
 useEffect(()=>{document.documentElement.classList.add('overlay-page');return()=>document.documentElement.classList.remove('overlay-page')},[]);
 useEffect(()=>{const onResize=()=>setViewport({w:innerWidth,h:innerHeight});addEventListener('resize',onResize);return()=>removeEventListener('resize',onResize)},[]);
 useEffect(()=>{
  if(!graphic)return;
  let stopped=false,timer:any,lastOk=0;
  const controller=new AbortController();
  const tick=async()=>{
   try{
    const next=await obsApi.frame(graphic,controller.signal);
    if(stopped)return;
    lastOk=Date.now();
    const me=next.state?.entries?.find((e:any)=>e.entry_id==='local');
    const pos=me?.fields?.position;
    if(next.mode==='solo'&&pos?.available&&Array.isArray(pos.value)){
     const t=trace.current,last=t[t.length-1],p=[pos.value[0],pos.value[2]];
     if(!last||Math.hypot(last[0]-p[0],last[1]-p[1])>2){t.push(p);if(t.length>TRACE_MAX)t.shift()}
    }
    if(next.mode==='solo'&&next.state)next.state.map_model={points:[...trace.current]};
    setFrame(next);
   }catch{
    if(!stopped&&Date.now()-lastOk>STALE_AFTER_MS)setFrame(null);
   }
   if(!stopped)timer=setTimeout(tick,POLL_MS);
  };
  tick();
  return()=>{stopped=true;clearTimeout(timer);controller.abort()};
 },[graphic]);

 if(!graphic)return <main style={{padding:24,color:'#e9eef7',fontFamily:'sans-serif'}}><h1>GT7 OBS overlays</h1><p>Add one of these addresses to an OBS Browser Source. Open the app's OBS Overlays page to copy them with the right size.</p><OverlayIndex/></main>;
 if(!frame||!frame.state||frame.state.buffering)return null;
 const g=frame.graphic,w=g.width,h=g.height;
 const sx=viewport.w/w,sy=viewport.h/h,scaleX=stretch?sx:Math.min(sx,sy),scaleY=stretch?sy:Math.min(sx,sy);
 return <div style={{width:w,height:h,transformOrigin:'0 0',transform:`scale(${scaleX},${scaleY})`}}>
  <GraphicView graphic={g} state={frame.state} workspace={frame.workspace} assetBase="/media" credential=""/>
 </div>;
}

function OverlayIndex(){
 const [ids,setIds]=useState<{id:string,name:string}[]>([]);
 useEffect(()=>{obsApi.state().then(s=>setIds(s.overlays)).catch(()=>setIds([]))},[]);
 return <ul>{ids.map(o=><li key={o.id}><a style={{color:'#9cc9ff'}} href={'/obs/'+o.id}>{o.name}</a> <code>{location.origin}/obs/{o.id}</code></li>)}</ul>;
}
