// Service health (receiver, audio, storage, ...). Reads `services` from the live '/ws' snapshot
// when the backend includes it; otherwise polls GET /api/services at <= 0.5 Hz.
import {createStore,useStore} from '../../app/store'
import {liveStore} from '../../app/liveStore'
import {platformApi} from '../api/platform'
import type {ServiceStatus} from '../types'

export type ServicesState={items:ServiceStatus[],source:'none'|'live'|'poll',loadedAt:number|null,error:string|null}
export const servicesStore=createStore<ServicesState>({items:[],source:'none',loadedAt:null,error:null})

export const POLL_MS=2500 // 0.4 Hz

function fromRaw(raw:any):ServiceStatus[]|null{
 const s=raw?.services
 if(Array.isArray(s))return s as ServiceStatus[]
 if(s&&typeof s==='object')return Object.entries(s).map(([id,v])=>({id,...(typeof v==='object'&&v?v as object:{state:String(v)})}) as ServiceStatus)
 return null
}

let stop:(()=>void)|null=null

export async function refreshServices():Promise<void>{
 try{
  const items=await platformApi.services()
  servicesStore.setState({items,source:'poll',loadedAt:Date.now(),error:null})
 }catch(e){servicesStore.setState({error:e instanceof Error?e.message:'Could not load services'})}
}

/** Starts feeding servicesStore. Idempotent; returns the stop function. */
export function startServices():()=>void{
 if(stop)return stop
 let live=false
 const onLive=()=>{
  const items=fromRaw(liveStore.getState().raw)
  if(items){live=true;servicesStore.setState({items,source:'live',loadedAt:Date.now(),error:null})}
 }
 const off=liveStore.subscribe(onLive)
 onLive()
 const tick=async()=>{if(!live&&document.visibilityState!=='hidden')await refreshServices()}
 void tick()
 const timer=window.setInterval(tick,POLL_MS)
 stop=()=>{off();window.clearInterval(timer);stop=null}
 return stop
}

export const useServices=()=>useStore(servicesStore,s=>s.items)
export const useService=(id:string)=>useStore(servicesStore,s=>s.items.find(x=>x.id===id))
