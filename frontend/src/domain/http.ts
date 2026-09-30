// The ONLY place in the frontend that calls fetch() (enforced by scripts/check-arch.mjs).
// JSON in/out, same-origin credentials (the browser is paired via the gt7_token cookie set by
// POST /api/pair; no token header is used today), AppError mapping of backend `{detail}` bodies,
// AbortSignal + timeout, and retry with backoff for idempotent GETs only.

export type ResultCode='ok'|'rejected'|'not_authorized'|'invalid_state'|'invalid_input'|'timeout'|'connection_lost'|'rate_limited'|'not_found'|'conflict'|'unavailable'

export type CommandResult<T=unknown>={
 code:ResultCode
 ok:boolean
 message:string
 diagnostic:string|null
 data:T|null
 command_id:string
 audit_id:string|null
}

const RESULT_CODES:readonly string[]=['ok','rejected','not_authorized','invalid_state','invalid_input','timeout','connection_lost','rate_limited','not_found','conflict','unavailable']

export function isCommandResult(value:unknown):value is CommandResult{
 if(typeof value!=='object'||value===null)return false
 const v=value as Record<string,unknown>
 return typeof v.code==='string'&&RESULT_CODES.includes(v.code)&&typeof v.ok==='boolean'&&typeof v.message==='string'
}

export function codeFromStatus(status:number):ResultCode{
 if(status>=200&&status<300)return 'ok'
 switch(status){
  case 0:return 'connection_lost'
  case 401:case 403:return 'not_authorized'
  case 404:return 'not_found'
  case 408:case 504:return 'timeout'
  case 409:return 'conflict'
  case 400:case 413:case 422:return 'invalid_input'
  case 429:return 'rate_limited'
  case 502:case 503:return 'unavailable'
  default:return status>=500?'unavailable':'rejected'
 }
}

export class AppError extends Error{
 status:number
 code:string
 detail:unknown
 constructor(message:string,init:{status?:number,code?:string,detail?:unknown}={}){
  super(message)
  this.name='AppError'
  this.status=init.status??0
  this.code=init.code??codeFromStatus(this.status)
  this.detail=init.detail
 }
}

export const messageOf=(error:unknown,fallback='Request failed'):string=>error instanceof Error&&error.message?error.message:fallback

// Same rule the pre-domain code used: a string detail is shown as-is, anything else as JSON.
export function detailMessage(detail:unknown,fallback:string):string{
 if(typeof detail==='string'&&detail)return detail
 if(detail&&typeof detail==='object'){
  const m=(detail as {message?:unknown}).message
  if(typeof m==='string'&&m)return m
  return JSON.stringify(detail)
 }
 return fallback
}

export type Query=Record<string,string|number|boolean|null|undefined>

export type RequestOptions={
 method?:'GET'|'POST'|'PUT'|'DELETE'|'PATCH'
 query?:Query
 /** JSON body (sets Content-Type). */
 json?:unknown
 /** Raw body (File/Blob), sent without a Content-Type. */
 body?:BodyInit
 headers?:Record<string,string>
 signal?:AbortSignal
 timeoutMs?:number
 /** Extra attempts after the first; only honoured for GET. */
 retries?:number
 /** Message used when the failure body carries no detail. */
 fallbackMessage?:string
 /** How to read a successful body. */
 parse?:'json'|'text'|'blob'|'none'
}

export type RawResponse<T>={status:number,ok:boolean,body:T|null}

const DEFAULT_TIMEOUT=15000
const RETRYABLE=new Set([502,503,504])

export function buildUrl(path:string,query?:Query):string{
 if(!query)return path
 const params=new URLSearchParams()
 for(const [k,v] of Object.entries(query))if(v!==undefined&&v!==null)params.set(k,String(v))
 const qs=params.toString()
 return qs?path+(path.includes('?')?'&':'?')+qs:path
}

const sleep=(ms:number,signal?:AbortSignal)=>new Promise<void>(resolve=>{
 const t=setTimeout(resolve,ms)
 signal?.addEventListener('abort',()=>{clearTimeout(t);resolve()},{once:true})
})

async function attempt<T>(path:string,o:RequestOptions):Promise<RawResponse<T>>{
 const controller=new AbortController()
 let timedOut=false
 const timer=setTimeout(()=>{timedOut=true;controller.abort()},o.timeoutMs??DEFAULT_TIMEOUT)
 const onAbort=()=>controller.abort()
 if(o.signal){if(o.signal.aborted)controller.abort();else o.signal.addEventListener('abort',onAbort,{once:true})}
 const headers:Record<string,string>={...(o.json!==undefined?{'Content-Type':'application/json'}:{}),...o.headers}
 try{
  const response=await fetch(buildUrl(path,o.query),{
   method:o.method??'GET',
   headers,
   credentials:'same-origin',
   body:o.json!==undefined?JSON.stringify(o.json):o.body,
   signal:controller.signal,
  })
  let body:unknown=null
  if(response.ok&&o.parse==='none')body=null
  else if(response.ok&&o.parse==='blob')body=await response.blob()
  else{
   const text=await response.text()
   if(o.parse==='text'&&response.ok)body=text
   else if(text){try{body=JSON.parse(text)}catch{body=response.ok?null:text}}
  }
  return {status:response.status,ok:response.ok,body:body as T|null}
 }catch(error){
  if(timedOut)throw new AppError('Request timed out',{status:0,code:'timeout'})
  if(o.signal?.aborted)throw new AppError('Request cancelled',{status:0,code:'aborted'})
  if(error instanceof AppError)throw error
  throw new AppError(messageOf(error,'Network error'),{status:0,code:'connection_lost'})
 }finally{
  clearTimeout(timer)
  o.signal?.removeEventListener('abort',onAbort)
 }
}

/** Never throws for an HTTP error status; still throws AppError on network failure/timeout/abort. */
export async function sendRaw<T=unknown>(path:string,o:RequestOptions={}):Promise<RawResponse<T>>{
 const retries=(o.method??'GET')==='GET'?o.retries??0:0
 for(let n=0;;n++){
  try{
   const result=await attempt<T>(path,o)
   if(n<retries&&RETRYABLE.has(result.status)){await sleep(250*2**n,o.signal);continue}
   return result
  }catch(error){
   if(n<retries&&error instanceof AppError&&(error.code==='connection_lost'||error.code==='timeout')&&!o.signal?.aborted){await sleep(250*2**n,o.signal);continue}
   throw error
  }
 }
}

export function errorFrom(result:RawResponse<unknown>,fallback='Request failed'):AppError{
 const body=result.body
 const detail=typeof body==='object'&&body!==null?(body as {detail?:unknown}).detail:body
 const code=typeof detail==='object'&&detail!==null&&typeof (detail as {code?:unknown}).code==='string'?(detail as {code:string}).code:undefined
 return new AppError(detailMessage(detail,fallback),{status:result.status,code,detail})
}

/** JSON request; resolves with the parsed body, rejects with AppError on any non-2xx. */
export async function send<T=unknown>(path:string,o:RequestOptions={}):Promise<T>{
 const result=await sendRaw<T>(path,o)
 if(!result.ok)throw errorFrom(result,o.fallbackMessage)
 return result.body as T
}

type Rest=Omit<RequestOptions,'method'|'json'|'body'>
export const get=<T>(path:string,o:Rest={})=>send<T>(path,{...o,method:'GET'})
export const post=<T>(path:string,json?:unknown,o:Rest={})=>send<T>(path,{...o,method:'POST',json})
export const put=<T>(path:string,json?:unknown,o:Rest={})=>send<T>(path,{...o,method:'PUT',json})
export const del=<T>(path:string,json?:unknown,o:Rest={})=>send<T>(path,{...o,method:'DELETE',json})
