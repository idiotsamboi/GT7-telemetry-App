import React,{useEffect,useState} from 'react';
import {engineerApi} from './domain/api';
import {AppError} from './domain/http';
function RequestLibrary({onRequest}:{onRequest:(text:string)=>void}){
 const [requests,setRequests]=useState<any[]>([]),[search,setSearch]=useState(''),[category,setCategory]=useState('All'),[error,setError]=useState('');
 useEffect(()=>{engineerApi.requests().then(data=>setRequests(data.requests)).catch(e=>setError(e instanceof AppError&&e.status>0?'Could not load engineer requests':e.message))},[]);
 const visible=requests.filter(r=>(category==='All'||r.category===category)&&`${r.request} ${r.category}`.toLowerCase().includes(search.toLowerCase()));
 return <section className="card request-library"><h3>Engineer request library · {requests.length}</h3><p>Say a request using Hold to talk, type it, or select it below. Replies rotate through three variations. Live values replace the placeholders; unavailable facts stay unavailable.</p><div className="toolbar"><input aria-label="Search engineer requests" placeholder="Search fuel, tyres, timing…" value={search} onChange={e=>setSearch(e.target.value)}/><label>Category<select value={category} onChange={e=>setCategory(e.target.value)}>{['All',...new Set(requests.map(r=>r.category))].map(c=><option key={c}>{c}</option>)}</select></label><span>{visible.length} requests</span></div>{error&&<p role="alert">{error}</p>}<div className="request-grid">{visible.map(r=><article key={r.id}><small>{r.category}</small><button onClick={()=>onRequest(r.request)}>{r.request}</button><details><summary>Three answer variations</summary><ol>{r.answers.map((a:string,i:number)=><li key={i}>{a.replaceAll('{value}','[live value]').replaceAll('{answer}','[telemetry answer]')}</li>)}</ol></details></article>)}</div></section>
}

export default React.memo(RequestLibrary);
