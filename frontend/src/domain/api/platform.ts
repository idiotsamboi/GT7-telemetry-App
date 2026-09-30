// Clients for the v2 platform endpoints. Typed defensively: while the backend lags they resolve
// to []/null on 404 instead of throwing, so stores can poll them unconditionally.
import {AppError,get,sendRaw,type CommandResult} from '../http'
import type {ServiceStatus,FeatureFlag,ChannelInfo,CapabilityGrant,AuditEntry} from '../types'

async function optional<T>(path:string,fallback:T,query?:Record<string,string|number|undefined>):Promise<T>{
 try{return await get<T>(path,{query,retries:1})}
 catch(e){if(e instanceof AppError&&(e.status===404||e.status===405))return fallback;throw e}
}
function list<T>(value:unknown,key:string):T[]{
 if(Array.isArray(value))return value as T[]
 const inner=(value as Record<string,unknown>|null)?.[key]
 return Array.isArray(inner)?inner as T[]:[]
}

export const platformApi={
 services:async()=>list<ServiceStatus>(await optional<unknown>('/api/services',[]),'services'),
 features:async()=>list<FeatureFlag>(await optional<unknown>('/api/features',[]),'features'),
 channels:async()=>list<ChannelInfo>(await optional<unknown>('/api/channels',[]),'channels'),
 /** null while the endpoint does not exist yet (callers then fall back to local defaults). */
 myCapabilities:async():Promise<CapabilityGrant|null>=>{
  const v=await optional<unknown>('/api/me/capabilities',null)
  if(Array.isArray(v))return {capabilities:v.filter((x):x is string=>typeof x==='string')}
  if(v&&typeof v==='object'&&Array.isArray((v as CapabilityGrant).capabilities))return v as CapabilityGrant
  return null
 },
 audit:async(q:{limit?:number,since?:string|number,command?:string}={})=>list<AuditEntry>(await optional<unknown>('/api/audit',[],q),'entries'),
 /**
  * POST /api/commands/{id}. HTTP status follows the result code and the body is a CommandResult
  * on both success and refusal, so this returns the raw response and lets commands.ts interpret it.
  */
 command:(id:string,payload?:unknown)=>sendRaw<CommandResult<unknown>|{detail?:unknown}>('/api/commands/'+encodeURIComponent(id),{method:'POST',json:payload??{},timeoutMs:60000}),
}
