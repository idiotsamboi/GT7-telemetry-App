import {trainingApi} from './domain/api';
import {useEffect,useRef,useState} from 'react';
import {MapPinned,Play,Square,CheckCircle2,Target,Shuffle,Scan,RotateCcw,Trash2} from 'lucide-react';
import TrackVisualizer from './TrackVisualizer';
import RouletteWheel from './RouletteWheel';
const SPIN_MS=3000;

type Candidate={id:string,name:string,track:string,venue_id:string,direction:string,length_m:number};
type Goal={laps_saved:number,points_saved:number,points_per_km:number,points_per_km_target:number,percent:number,complete:boolean};
type Progress=Goal&{layout_id:string,name:string,venue_name:string,direction:string,length_m:number};

const fmt=(x:any,d=1)=>x==null?'—':Number(x).toFixed(d);

function GoalBar({goal}:{goal:Goal}){
 return <div className="training-goal-bar"><div className={'training-goal-fill '+(goal.complete?'complete':'')} style={{width:`${goal.percent}%`}}/></div>;
}

export default function Training({state}:{state:any}){
 const [candidates,setCandidates]=useState<Candidate[]>([]);
 const [progress,setProgress]=useState<Progress[]>([]);
 const [tab,setTab]=useState<'untrained'|'goals'>('untrained');
 const [selected,setSelected]=useState('');
 const [error,setError]=useState('');
 const [spinning,setSpinning]=useState(false);
 const [spinCandidates,setSpinCandidates]=useState<Candidate[]>([]);
 const [winnerIndex,setWinnerIndex]=useState<number|null>(null);
 const [rotation,setRotation]=useState(0);
 const [celebrating,setCelebrating]=useState(false);
 const spinTimer=useRef<number|undefined>(undefined);
 const rotationRef=useRef(0);
 const wasComplete=useRef(false);
 const training=state?.training;
 const refresh=async()=>{
  const [c,p]=await Promise.all([
   trainingApi.candidates().catch(e=>{setError(e.message);return null}),
   trainingApi.progress().catch(e=>{setError(e.message);return null}),
  ]);
  if(c)setCandidates(c);
  if(p)setProgress(p);
  return c as Candidate[]|null;
 };
 useEffect(()=>{refresh()},[]);
 useEffect(()=>{if(training&&!training.active&&!celebrating)refresh()},[training?.active]);
 useEffect(()=>()=>window.clearTimeout(spinTimer.current),[]);

 function spin(list:Candidate[]){
  window.clearTimeout(spinTimer.current);
  if(!list.length){setSelected('');return}
  const idx=Math.floor(Math.random()*list.length);
  const seg=360/list.length;
  const targetCenter=idx*seg+seg/2;
  const base=rotationRef.current,currentMod=((base%360)+360)%360;
  const spins=5+Math.floor(Math.random()*2);
  const needed=(((360-targetCenter)-currentMod)%360+360)%360;
  const next=base+spins*360+needed;
  rotationRef.current=next;
  setSpinCandidates(list);setWinnerIndex(null);setRotation(next);setSpinning(true);
  spinTimer.current=window.setTimeout(()=>{
   setSpinning(false);setWinnerIndex(idx);setSelected(list[idx].id);
  },SPIN_MS);
 }

 // When the mapping goal completes mid-recording: celebrate, stop, drop it from the
 // pool, and spin to a new random untrained layout - "select a track and tell me to drive it."
 useEffect(()=>{
  const nowComplete=!!training?.goal?.complete;
  if(nowComplete&&training?.active&&!wasComplete.current){
   setCelebrating(true);
   const t=window.setTimeout(async()=>{
    try{await trainingApi.stop()}catch(e:any){setError(e.message)}
    const fresh=await refresh();
    setCelebrating(false);
    if(fresh&&fresh.length)spin(fresh);
   },2600);
   wasComplete.current=true;
   return()=>window.clearTimeout(t);
  }
  if(!training?.active)wasComplete.current=false;
 },[training?.goal?.complete,training?.active]);

 async function start(){
  if(!selected)return;
  try{await trainingApi.start(selected);setError('')}catch(e:any){setError(e.message)}
 }
 async function stop(){try{await trainingApi.stop();setError('')}catch(e:any){setError(e.message)}}
 async function retryLap(){try{await trainingApi.retryLap();setError('')}catch(e:any){setError(e.message)}}
 async function resume(layoutId:string){try{await trainingApi.start(layoutId);setError('')}catch(e:any){setError(e.message)}}
 async function restart(layoutId:string,name:string){
  if(!window.confirm(`Permanently delete all captured laps for ${name} and start it over from zero? This can't be undone.`))return;
  try{await trainingApi.restart(layoutId);setError('');await refresh()}catch(e:any){setError(e.message)}
 }
 const grouped=candidates.reduce<Record<string,Candidate[]>>((acc,c)=>{(acc[c.track]=acc[c.track]||[]).push(c);return acc},{});
 const inProgress=progress.filter(p=>!p.complete).length;
 const showRecording=training?.active||celebrating;
 return <div className="training-page">
  {error&&<div className="notice critical" role="alert">{error}<button onClick={()=>setError('')}>Dismiss</button></div>}
  {showRecording?<div className="training-active-layout">
   <section className="card training-active">
    <div className="card-top"><h3><MapPinned size={16}/> {celebrating?'Mapping goal complete':`Recording: ${training.venue_name}`}</h3><span className="tiny-badge">{training?.direction}</span></div>
    <h2>{training?.layout_name}</h2>
    {celebrating?<p className="subtle training-celebrate">Nice lap set. This layout is dropping out of the pool — picking your next one…</p>:<>
     <p className="subtle">Drive this layout. Every completed lap (by the game's own lap counter) is saved automatically; the opening partial lap is discarded. Stop whenever the goal below is complete — or keep going for extra margin.</p>
     <div className="metric-pair">
      <span>Laps saved this session<b>{training.laps_this_session}</b></span>
      <span>Laps saved for this layout<b>{training.laps_saved_total}</b></span>
      <span>Points in current lap<b>{training.points_in_current_lap}</b></span>
      <span>Reference length<b>{fmt(training.length_m,0)} m</b></span>
     </div>
     {training.goal&&<div className="training-goal">
      <div className="training-goal-label"><span><Target size={14}/> Mapping goal</span><span>{training.goal.complete?<b className="green-text">Complete</b>:`${fmt(training.goal.points_per_km,0)} / ${training.goal.points_per_km_target} pts/km`}</span></div>
      <GoalBar goal={training.goal}/>
      <p className="subtle">Density of captured points along this layout's length. Reaching the target usually takes a few clean laps, so one fast or one slow lap alone won't finish it.</p>
     </div>}
     {training.error&&<p role="alert" className="amber-text">{training.error}</p>}
     <div className="chips-row">
      <button className="primary" onClick={stop}><Square size={15}/>Stop training</button>
      <button type="button" onClick={retryLap} disabled={!training.points_in_current_lap} title="Discard the lap in progress and start it over. Already-saved laps are kept."><RotateCcw size={15}/>Retry lap</button>
     </div>
    </>}
   </section>
   <section className="card training-visual">
    <div className="card-top"><h3><Scan size={16}/> Point cloud</h3><span className="tiny-badge">{training?.points_in_current_lap??0} pts</span></div>
    <TrackVisualizer active={!!training?.active} newPoints={training?.preview_points||[]} complete={celebrating||!!training?.goal?.complete} retakeId={training?.retake_id}/>
    <p className="subtle">Every accepted position sample this session, plotted live. Brighter dots were just captured; the shape settles in as you complete laps.</p>
   </section>
  </div>:<div className="training-single">
   <div className="chips training-tabs">
    <button className={tab==='untrained'?'active':''} onClick={()=>setTab('untrained')}>Untrained layouts ({candidates.length})</button>
    <button className={tab==='goals'?'active':''} onClick={()=>setTab('goals')}>Training goals ({inProgress} in progress)</button>
   </div>
   {tab==='untrained'?<section className="card">
    <div className="card-top"><h3><MapPinned size={16}/> Untrained layouts</h3><span className="tiny-badge">{candidates.length} remaining</span></div>
    <p className="subtle">These GT7 layouts have no built-in map yet. Pick one (or spin for a random one), drive it in-game, and this records raw position laps locally. Captured laps become permanent the next time the offline model bundle is rebuilt (highest merge precedence over other sources).</p>
    {!candidates.length?<p className="subtle">Every catalogue layout already has a model, or a local capture is already pending for the rest.</p>:<>
     <div className="training-pick-row">
      <label>Layout to train next<select aria-label="Layout to train" value={selected} disabled={spinning} onChange={e=>setSelected(e.target.value)}>
       <option value="">Choose a layout</option>
       {Object.entries(grouped).map(([track,layouts])=><optgroup label={track} key={track}>{layouts.map(l=><option value={l.id} key={l.id}>{l.name} ({l.direction}, {fmt(l.length_m,0)} m)</option>)}</optgroup>)}
      </select></label>
      <button type="button" disabled={spinning} onClick={()=>spin(candidates)} className={'training-shuffle '+(spinning?'spinning':'')}><Shuffle size={15}/>{spinning?'Spinning…':'Random pick'}</button>
     </div>
     {(spinning||winnerIndex!=null)&&<div className="roulette-panel">
      <RouletteWheel list={spinCandidates} rotation={rotation} spinning={spinning} winnerIndex={winnerIndex}/>
      <p className="training-spin-label" aria-live="polite">{spinning?'Spinning…':winnerIndex!=null?spinCandidates[winnerIndex]?.name:''}</p>
     </div>}
     <button className="primary" disabled={!selected||spinning} onClick={start}><Play size={15}/>Start training</button>
    </>}
   </section>:<section className="card training-goals">
    <div className="card-top"><h3><Target size={16}/> Training goals</h3><span className="tiny-badge">{progress.length} started</span></div>
    <p className="subtle">Every layout with at least one captured lap, and how close it is to a reasonably reliable point density. A layout drops off "Untrained" as soon as it has any capture, but stays listed here — with a goal to finish — until it clears the target. Not done yet? Resume it any time; if a capture went bad, restart it from scratch.</p>
    {!progress.length?<p className="subtle">Nothing captured yet. Start a layout from "Untrained layouts".</p>:<div className="training-goal-list">
     {progress.map(p=><div className="training-goal-row" key={p.layout_id}>
      <div className="training-goal-name"><b>{p.name}</b><small>{p.venue_name} · {p.direction} · {p.laps_saved} lap{p.laps_saved===1?'':'s'}</small></div>
      <GoalBar goal={p}/>
      <span className="training-goal-status">{p.complete?<><CheckCircle2 size={14}/> Complete</>:`${fmt(p.points_per_km,0)} / ${p.points_per_km_target} pts/km`}</span>
      <div className="training-goal-actions">
       {!p.complete&&<button type="button" onClick={()=>resume(p.layout_id)} title="Keep capturing laps for this layout"><Play size={13}/>Resume</button>}
       <button type="button" className="danger-ghost" onClick={()=>restart(p.layout_id,p.name)} title="Delete all captured laps for this layout and start over"><Trash2 size={13}/>Restart</button>
      </div>
     </div>)}
    </div>}
   </section>}
  </div>}
 </div>;
}
