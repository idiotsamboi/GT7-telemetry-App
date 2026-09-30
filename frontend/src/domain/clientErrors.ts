// Client-side error reporting to POST /api/client-errors. Rate limited (5/min), truncated, and
// scrubbed: no tokens, no URL fragment/query (overlay credentials live in the fragment).
import {diagnosticsApi} from './api/diagnostics'

const MAX_PER_MINUTE=5
const MAX_MESSAGE=500
const MAX_STACK=4000
let sent:number[]=[]

const scrub=(text:string):string=>text
 .replace(/(access|token|credential|ticket|authorization)([=:]\s*|"\s*:\s*")(bearer\s+)?[A-Za-z0-9._~+/=-]{6,}/gi,'$1$2[redacted]')
 .replace(/#[^\s)"']*/g,'#[redacted]')

export function safeLocation():string{
 try{return location.origin+location.pathname}catch{return ''}
}

/** Returns true if a report was sent (false when rate limited or the request failed). */
export async function reportClientError(error:unknown,component:string):Promise<boolean>{
 const now=Date.now()
 sent=sent.filter(t=>now-t<60000)
 if(sent.length>=MAX_PER_MINUTE)return false
 sent.push(now)
 const err=error instanceof Error?error:new Error(String(error))
 try{
  await diagnosticsApi.reportClientError({
   message:scrub(err.message||'Error').slice(0,MAX_MESSAGE),
   stack:scrub(err.stack||'').slice(0,MAX_STACK),
   component:component.slice(0,120),
   url:safeLocation(),
  })
  return true
 }catch{return false}
}

/** Fetches the redacted diagnostics bundle and copies it to the clipboard. Returns the JSON text. */
export async function copyDiagnostics():Promise<string>{
 const bundle=await diagnosticsApi.copy()
 const text=JSON.stringify(bundle,null,2)
 await navigator.clipboard.writeText(text)
 return text
}

export function installGlobalErrorReporting():()=>void{
 const onError=(e:ErrorEvent)=>{void reportClientError(e.error??e.message,'window.onerror')}
 const onRejection=(e:PromiseRejectionEvent)=>{void reportClientError(e.reason,'unhandledrejection')}
 window.addEventListener('error',onError)
 window.addEventListener('unhandledrejection',onRejection)
 return ()=>{window.removeEventListener('error',onError);window.removeEventListener('unhandledrejection',onRejection)}
}
