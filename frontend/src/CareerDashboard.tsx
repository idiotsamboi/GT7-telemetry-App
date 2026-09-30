import {useCallback,useEffect,useRef,useState} from 'react'
import {ArrowUpRight,BookOpen,Flag,RefreshCw,ShieldCheck,Trophy} from 'lucide-react'
import {navigate} from './app/router'
import {gamificationApi,type CareerDashboardData,type CareerSkill,type CareerCorner,type DriverProfile} from './domain/api/gamification'
import {messageOf} from './domain/http'
import './CareerDashboard.css'

const views=['overview','skills','tracks','corners','challenges','achievements','training','engineer','seasons','history'] as const
type View=typeof views[number]
const title=(value:string)=>value.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase())
const date=(value:string)=>new Date(value).toLocaleString()
const unavailable:Partial<Record<View,string>>={
 seasons:'Career seasons and season rewards are not available yet.',
}
function Evidence({data,source}:{data:Record<string,unknown>,source?:string|null}){
 return <details className="career-evidence"><summary>View evidence</summary>{source&&<p>Source: <code>{source}</code></p>}<pre>{JSON.stringify(data,null,2)}</pre></details>
}
function Skill({skill}:{skill:CareerSkill}){
 const measured=skill.score!==null
 return <article className="card career-skill"><div className="career-row"><h3>{title(skill.category)}</h3><span className="badge">{measured?'Measured':'Unavailable'}</span></div>
 <strong className={'career-score '+(!measured?'career-unavailable':'')}>{measured?`${skill.score!.toFixed(1)} / 100`:'Insufficient evidence'}</strong>
 {measured&&<progress aria-label={`${title(skill.category)} score`} max={100} value={skill.score!}/>}
 <p>{Math.round(skill.confidence*100)}% confidence Â· {skill.evidence_count} evidence samples</p>
 <small>{skill.level_name&&`${skill.level_name} Â· `}{skill.xp.toLocaleString()} skill XP Â· Application progression, not a universal ranking.</small>
 <Evidence source={skill.source_id} data={skill.evidence??{score:skill.score,confidence:skill.confidence,evidence_count:skill.evidence_count,source_id:skill.source_id}}/>
 </article>
}

export default function CareerDashboard({tab}:{tab:string}){
 const view:View=views.includes(tab as View)?tab as View:'overview'
 const [data,setData]=useState<CareerDashboardData|null>(null),[profiles,setProfiles]=useState<DriverProfile[]>([])
 const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('')
 const [name,setName]=useState(''),[confirmation,setConfirmation]=useState(''),[updated,setUpdated]=useState<string|null>(null)
 const [corners,setCorners]=useState<CareerCorner[]>([]),[cornerLayout,setCornerLayout]=useState('')
 const flight=useRef<AbortController|null>(null),actionLock=useRef(false),mounted=useRef(false),lastStart=useRef(0)
 const load=useCallback(async(force=false)=>{
  if(document.hidden||flight.current||actionLock.current||(!force&&Date.now()-lastStart.current<10000))return
  const controller=new AbortController();flight.current=controller;lastStart.current=Date.now();setLoading(true)
  try{
   const dashboard=await gamificationApi.dashboard(controller.signal)
   const drivers=await gamificationApi.profiles(controller.signal)
   if(mounted.current&&!controller.signal.aborted){setData(dashboard);setProfiles(drivers);setError('');setUpdated(new Date().toLocaleTimeString())}
  }catch(err){if(mounted.current&&!controller.signal.aborted)setError(messageOf(err,'Career could not be loaded.'))}
  finally{if(flight.current===controller)flight.current=null;if(mounted.current)setLoading(false)}
 },[])
 useEffect(()=>{
  mounted.current=true;void load(true)
  const timer=window.setInterval(()=>void load(),10000)
  const visibility=()=>{if(document.hidden)flight.current?.abort();else void load()}
  document.addEventListener('visibilitychange',visibility)
  return()=>{mounted.current=false;clearInterval(timer);flight.current?.abort();document.removeEventListener('visibilitychange',visibility)}
 },[load])
 async function act(task:()=>Promise<unknown>,message:string){
  if(actionLock.current||flight.current)return
  actionLock.current=true;setBusy(true);setNotice('');setError('')
  try{await task();if(mounted.current)setNotice(message)}
  catch(err){if(mounted.current)setError(messageOf(err,'Career action failed.'));return}
  finally{actionLock.current=false;if(mounted.current)setBusy(false)}
  if(mounted.current)await load(true)
 }
 async function exportCareer(){
  const bundle=await gamificationApi.export(),url=URL.createObjectURL(new Blob([JSON.stringify(bundle,null,2)],{type:'application/json'}))
  const link=document.createElement('a');link.href=url;link.download='driver-career.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
 }
 const disabled=busy||loading
 const measured=data?.skills.filter(s=>s.score!==null)??[]
 const level=data?.level
 const progress=level&&level.next_level_xp!==null?Math.max(0,Math.min(100,(level.total_xp-level.level_start_xp)/Math.max(1,level.next_level_xp-level.level_start_xp)*100)):100
 return <div className="career-page">
  <nav className="career-tabs" aria-label="Career sections">{views.map(item=><a key={item} aria-current={view===item?'page':undefined} href={'#/driver/career'+(item==='overview'?'':'/'+item)}>{title(item)}</a>)}</nav>
  <div className="career-row career-refresh"><p>Local driver career Â· {updated?`Updated ${updated}`:'Waiting for career data'}</p><button disabled={disabled} onClick={()=>void load(true)}><RefreshCw size={14}/>{loading?'Refreshingâ€¦':'Refresh'}</button></div>
  {error&&<div className="notice critical" role="alert"><span>{error}{data&&' Â· Previously loaded data is shown.'}</span><button disabled={disabled} onClick={()=>void load(true)}>Retry career</button></div>}
  {notice&&<p className="notice" role="status">{notice}</p>}
  {!data&&!error&&<section className="card" role="status">Loading driver careerâ€¦</section>}
  {data&&<>
   <section className="card career-profile"><div><span className="eyebrow">ACTIVE DRIVER</span><h2>{data.profile.name}</h2>{data.titles?.equipped&&<span className="badge title-badge">Title: {data.titles.equipped}</span>}{data.profile.provenance==='imported_profile'&&<span className="badge amber">IMPORTED ARCHIVE · LIVE REWARDS DISABLED</span>}<p>{data.profile.eligible_sessions} eligible sessions · {data.profile.comparable_laps} comparable laps</p></div>
    <div className="career-profile-selectors">
     <label>Driver profile<select disabled={disabled} value={data.profile.id} onChange={event=>void act(()=>gamificationApi.selectProfile(event.target.value),'Active driver changed. Existing session attribution is retained.')}>{profiles.map(profile=><option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
     {data.titles&&<label>Equipped title<select disabled={disabled} value={data.titles.equipped} onChange={event=>void act(()=>gamificationApi.equipTitle(event.target.value),'Equipped title updated.')}>{data.titles.titles.map(t=><option key={t.id} value={t.name} disabled={!t.unlocked}>{t.name} {!t.unlocked?'(Locked)':''}</option>)}</select></label>}
    </div>
    <details className="career-manage"><summary>Manage career</summary><div className="career-management">
     <form onSubmit={event=>{event.preventDefault();if(name.trim())void act(async()=>{await gamificationApi.createProfile(name.trim());setName('')},'Driver profile created. Select it to make it active.')}}><label>New driver name<input maxLength={80} required value={name} onChange={event=>setName(event.target.value)}/></label><button disabled={disabled||!name.trim()}>Create driver</button></form>
     <label className="check"><input type="checkbox" checked={data.settings.enabled} disabled={disabled} onChange={event=>void act(()=>gamificationApi.saveSettings(event.target.checked),'Career settings saved.')}/>Enable career rewards</label>
     <label>Import career archive<input type="file" accept="application/json,.json" disabled={disabled} onChange={event=>{const file=event.target.files?.[0];if(file)void act(async()=>{if(file.size>8*1024*1024)throw new Error("Archive exceeds 8 MiB");await gamificationApi.import(JSON.parse(await file.text()))},"Imported read-only career archive. Select it in Driver profile to inspect.");event.target.value=""}}/></label><button disabled={disabled} onClick={()=>void act(exportCareer,'Career archive downloaded.')}>Export career archive</button>
     <form className="career-reset" onSubmit={event=>{event.preventDefault();if(confirmation==='RESET CAREER')void act(async()=>{await gamificationApi.reset();setConfirmation('');setCorners([])},'Career reset completed.')}}><h3>Reset career</h3><p>Resets this driver's XP, skills, achievements and mastery. Recorded telemetry and reward integrity guards are retained. Export first to preserve an imported, read-only archive of your current progress.</p><label>Type RESET CAREER to confirm<input autoComplete="off" value={confirmation} onChange={event=>setConfirmation(event.target.value)}/></label><button className="danger-ghost" disabled={disabled||confirmation!=='RESET CAREER'}>Reset career permanently</button></form>
    </div></details>
   </section>
   {!data.settings.enabled&&<p className="notice">Career rewards are paused. Enable them in Manage career to record future progress.</p>}
   {view==='overview'&&<>
    <div className="career-hero"><section className="card career-next"><span className="eyebrow"><Flag size={14}/> NEXT ACTION</span><h2>{data.next_action.title}</h2><p>{data.next_action.reason}</p><a className="button primary" href="#/driver/pit-wall/live">Open Pit Wall <ArrowUpRight size={16}/></a><p className="career-note">Rewards are assessed after a live session is finalized. Replay, demo and imported evidence do not earn live rewards.</p></section>
     <section className="card career-level"><span className="eyebrow">CAREER PROGRESS</span><div className="career-level-value">Level <strong>{data.level.current}</strong></div><progress aria-label="Progress to next career level" max={100} value={progress}/><p>{data.level.total_xp.toLocaleString()} total XP{data.level.next_level_xp===null?' · Maximum level reached':` · ${(data.level.next_level_xp-data.level.total_xp).toLocaleString()} XP to next level`}</p><small>Level reflects earned progress. Skill confidence comes from evidence.</small></section></div>
    {data.recent_gains&&<section className="card career-gains"><h3>Recent Gains</h3><p>Recent XP: +{data.recent_gains.recent_xp} XP {data.recent_gains.latest_grade?`· Latest Grade: ${data.recent_gains.latest_grade}`:''} {data.recent_gains.delta_score!=null?`· Consistency Delta: ${data.recent_gains.delta_score>0?'+':''}${data.recent_gains.delta_score}`:''}</p></section>}
    <div className="career-section-heading"><h2>Skills with evidence</h2><a href="#/driver/career/skills">View all skills <ArrowUpRight size={14}/></a></div>
    {measured.length?<div className="career-grid">{measured.map(skill=><Skill key={skill.category} skill={skill}/>)}</div>:<section className="card career-empty"><BookOpen size={24}/><h3>Your skill profile is still learning</h3><p>No supported skill has enough evidence yet. Unknown scores stay unavailable; XP alone does not establish driving ability.</p></section>}
    <section className="card career-integrity"><ShieldCheck size={20}/><div><h3>Evidence before rewards</h3><p>Reward source: {data.integrity.reward_source}. Algorithm version {data.integrity.algorithm_version}. Unsupported metrics remain {data.integrity.unknown_metrics}.</p><small>Track and corner scores are application calculations against your own evidence. Full track mastery requires all component evidence.</small></div></section>
   </>}
   {view==='skills'&&<><h2>Skill profile</h2><p className="career-note">A score is only shown when supported by evidence. Confidence and sample count describe how much evidence supports it.</p>{data.skills.length?<div className="career-grid">{data.skills.map(skill=><Skill key={skill.category} skill={skill}/>)}</div>:<section className="card">No skill evidence recorded yet.</section>}</>}
   {view==='engineer'&&<><h2>Engineer development</h2>{data.engineer?<><section className="card"><p>Relationship level {data.engineer.level} · {data.engineer.xp} relationship XP</p><h3>{data.engineer.briefing.title}</h3><p>{data.engineer.briefing.why}</p><p>{data.engineer.briefing.focus_note}</p><p>{data.engineer.briefing.confidence===null?'Limited evidence':`${Math.round(data.engineer.briefing.confidence*100)}% confidence`}</p><label>Current focus<select disabled={disabled} value={data.engineer.focus} onChange={event=>void act(()=>gamificationApi.setFocus(event.target.value),'Focus saved.')} >{['pace','consistency','braking','cornering','fuel','strategy','track_learning'].map(focus=><option key={focus} value={focus}>{title(focus)}</option>)}</select></label>{data.engineer.briefing.challenge_id&&<button disabled={disabled} onClick={()=>void act(()=>gamificationApi.startMission(data.engineer!.briefing.challenge_id!),'Engineer mission accepted. Start a new session to work on it.')}>Accept engineer mission</button>}</section><section className="card"><h3>Inspectable memory</h3><Evidence data={data.engineer.memory}/><button disabled={disabled} onClick={()=>void act(()=>gamificationApi.clearMemory(),'Engineer memory deleted.')}>Delete engineer memory</button></section>{data.engineer.missions.map(mission=><section className="card" key={mission.id}><h3>{mission.challenge?.title??'Archived mission'}</h3><p>{mission.status}</p>{mission.challenge&&<progress max={100} value={mission.challenge.progress} aria-label="Mission progress"/>}<small>Completing this objective grants its challenge reward once and 25 relationship XP.</small></section>)}</>:<section className="card">No engineer career evidence available.</section>}</>}
   {view==='training'&&<><h2>Career curriculum</h2><p>{data.career?.scope??'No career curriculum evidence available.'}</p><div className="career-grid">{data.career?.chapters.map(chapter=><article className="card" key={chapter.id}><span className="badge">{chapter.completed?'Completed':'In progress'}</span><h3>{chapter.title}</h3><p>{chapter.required_laps} comparable laps · {chapter.required_challenges} completed challenges</p></article>)}</div><button onClick={()=>navigate('/driver/training')}>Open Driver Training <ArrowUpRight size={16}/></button><section className="card"><h3>Practice streaks</h3>{data.streaks?.length?data.streaks.map(streak=><p key={streak.kind}>{title(streak.kind)}: {streak.current_count} · Best {streak.best_count}<br/>{streak.reason}</p>):<p>No qualifying consistency-session streak yet.</p>}</section></>}
   {view==='achievements'&&<><h2>Earned achievements & Badges</h2>{data.badges&&<div className="career-grid">{data.badges.map(b=><article className="card" key={b.id}><span className={'badge '+(b.unlocked?'':'gray')}>{b.unlocked?'Unlocked':'Locked'}</span><h3>{b.name}</h3>{!b.unlocked&&b.progress&&<p>Progress {b.progress.current}/{b.progress.target}</p>}</article>)}</div>}{data.achievements.length?<div className="career-grid">{data.achievements.map(item=><article className="card" key={item.definition_id}><Trophy size={22}/><h3>{item.title}</h3><p>Earned {date(item.earned_at)}</p><Evidence data={item.evidence} source={item.source_id}/></article>)}</div>:<section className="card career-empty"><Trophy size={24}/><h3>No achievements earned yet</h3><p>Achievements appear here when qualifying live evidence has been processed.</p></section>}</>}
   {view==='tracks'&&<><h2>Track learning</h2><p>Personal references stay separate by layout and car. Missing components remain unavailable.</p><div className="career-grid">{(data.tracks??[]).map(track=><article className="card" key={`${track.layout_id}:${track.car_id}`}><h3>{track.layout_id}</h3><p>Car {track.car_id} · {track.visit_count} sessions · {track.lap_count} comparable laps</p><strong>PB {(track.pb_ms/1000).toFixed(3)} s</strong><p>Full mastery: {track.overall_score===null?'Insufficient component evidence':`${track.overall_score}%`}</p><p>{Math.round(track.component_coverage*100)}% component coverage · {Math.round(track.confidence*100)}% confidence</p><Evidence source={track.source_id} data={track.components}/></article>)}</div>{!data.tracks?.length&&<section className="card">No eligible track evidence yet. Ambiguous layouts do not receive progression.</section>}</>}
   {view==='corners'&&<><h2>Corner learning</h2><p>Calculated segment comparisons against your recorded reference. A driven reference is not an ideal line.</p><label>Layout<select value={cornerLayout} disabled={disabled} onChange={event=>{const layout=event.target.value;setCornerLayout(layout);setCorners([]);if(layout)void act(async()=>setCorners(await gamificationApi.corners(layout)),'Corner evidence loaded.')}}><option value="">Select a recorded layout</option>{[...new Set((data.tracks??[]).map(t=>t.layout_id))].map(id=><option key={id}>{id}</option>)}</select></label><div className="career-grid">{corners.map(corner=><article className="card" key={`${corner.car_id}:${corner.corner_id}`}><h3>{corner.name} · Car {corner.car_id}</h3><strong>{corner.score===null?'Insufficient evidence':`${corner.score.toFixed(1)} / 100`}</strong><p>{corner.sample_count} samples · {Math.round(corner.confidence*100)}% confidence</p><p>{corner.method}</p><Evidence source={corner.source_id} data={{reference_lap_id:corner.reference_lap_id,loss_s:corner.current_loss_s}}/></article>)}</div>{!corners.length&&<section className="card">No supported corner observations for this selection.</section>}</>}
   {view==='challenges'&&<><h2>Practice challenges</h2><p>Accept before starting your next session. Skipping has no XP penalty.</p><div className="career-grid">{(data.challenges??[]).map(challenge=><article className="card" key={challenge.id}><span className="badge">{challenge.kind} Â· {challenge.status}</span><h3>{challenge.title}</h3><p>{challenge.why}</p><p>{challenge.description}</p><progress max={100} value={challenge.progress} aria-label={`${challenge.title} progress`}/><p>{challenge.progress}% Â· +{challenge.reward_xp} XP on verified completion Â· {Math.round(challenge.confidence*100)}% confidence</p>{challenge.expires_at&&<small>Expires {date(challenge.expires_at)}</small>}<div className="career-row">{challenge.status==='offered'&&<button disabled={disabled} onClick={()=>void act(()=>gamificationApi.challengeAction(challenge.id,'accept'),'Challenge accepted for future sessions.')}>Accept challenge</button>}{['offered','accepted'].includes(challenge.status)&&<button disabled={disabled} onClick={()=>void act(()=>gamificationApi.challengeAction(challenge.id,'skip'),'Challenge set aside. No XP penalty.')}>Not now</button>}</div><Evidence data={{requirements:challenge.requirements,baseline:challenge.evidence,result:challenge.completion_evidence}}/></article>)}</div>{!data.challenges?.length&&<section className="card">Complete at least three comparable live laps in a finalized session to establish a measurable challenge baseline.</section>}</>}
   {view==='history'&&<><h2>Recent career history</h2><p className="career-note">The latest 20 sessions and reward events are shown. Export includes stored career records, within the archive size limit.</p><section className="card"><h3>Session scorecards</h3>{data.scorecards.length?data.scorecards.map(item=><article className="career-history-item" key={item.session_id}><div className="career-row"><b>{title(item.status)} session</b><span className="badge">{item.xp_awarded} XP</span></div><p>{date(item.created_at)} Â· Session <code>{item.session_id}</code></p>{item.exclusions.length>0&&<p>Excluded evidence: {item.exclusions.join(' Â· ')}</p>}<Evidence data={item.evidence}/></article>):<p>No finalized session scorecards yet.</p>}</section><section className="card"><h3>XP ledger</h3>{data.recent_events.length?data.recent_events.map(item=><article className="career-history-item" key={item.id}><div className="career-row"><b>{title(item.category)}</b><span>{item.amount>0?'+':''}{item.amount} XP</span></div><p>{date(item.created_at)} Â· Session <code>{item.session_id}</code></p><Evidence data={item.evidence} source={item.source_id}/></article>):<p>No XP events recorded yet.</p>}</section></>}
   {unavailable[view]&&<section className="card career-empty"><span className="badge">Unavailable Â· Foundation release</span><h2>{title(view)}</h2><p>{unavailable[view]}</p>{view==='training'&&<button onClick={()=>navigate('/driver/training')}>Open Driver Training <ArrowUpRight size={16}/></button>}</section>}
  </>}
 </div>
}
