// Session index cache (domain data only; never persisted). Views read it, commands refresh it.
import {createStore,useStore} from '../../app/store'
import {sessionsApi} from '../api/sessions'
import type {SessionSummary} from '../types'

export type SessionsState={items:SessionSummary[],includeArchived:boolean,loaded:boolean,loading:boolean,error:string|null,loadedAt:number|null}
export const sessionsStore=createStore<SessionsState>({items:[],includeArchived:false,loaded:false,loading:false,error:null,loadedAt:null})

let inflight:Promise<SessionSummary[]>|null=null

export function refreshSessions(includeArchived:boolean=sessionsStore.getState().includeArchived):Promise<SessionSummary[]>{
 if(inflight&&includeArchived===sessionsStore.getState().includeArchived)return inflight
 sessionsStore.setState({loading:true,includeArchived})
 const p=sessionsApi.list(includeArchived).then(items=>{
  sessionsStore.setState({items,loaded:true,loading:false,error:null,loadedAt:Date.now()})
  return items
 }).catch(e=>{
  sessionsStore.setState({loading:false,error:e instanceof Error?e.message:'Could not load sessions'})
  throw e
 }).finally(()=>{inflight=null})
 inflight=p
 return p
}

export const patchSession=(id:string,patch:Partial<SessionSummary>)=>sessionsStore.setState(s=>({items:s.items.map(x=>x.id===id?{...x,...patch}:x)}))

export const useSessions=()=>useStore(sessionsStore,s=>s.items)
export const useSessionsStatus=()=>useStore(sessionsStore,s=>({loaded:s.loaded,loading:s.loading,error:s.error}),(a,b)=>a.loaded===b.loaded&&a.loading===b.loading&&a.error===b.error)
