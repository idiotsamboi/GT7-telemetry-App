// Hash router: '#/broadcast/obs', '#/driver/pit-wall/telemetry', '#/settings/audio'.
// Hash routes work unmodified in the browser, in pywebview, and behind the FastAPI
// SPA fallback (backend only serves index.html at '/' - see docs/UI_MIGRATION_MAP.md).
// Never call this for '/group', '/overlay/*' or '/recovery' - those are separate pages.
import {useSyncExternalStore} from 'react'

export const DEFAULT_ROUTE='/driver/pit-wall/live'
const VIEW_STATE_KEY='ui:v1:lastRoute'

export type Route={
 workspace:'driver'|'broadcast'|'settings'|'pair'
 section:string
 tab:string
 path:string
}

function parse(hash:string):Route{
 const path=(hash.replace(/^#/,'')||DEFAULT_ROUTE)
 const parts=path.replace('/broadcast/studio','/broadcast/obs').split('/').filter(Boolean)
 const workspace=(parts[0]==='broadcast'||parts[0]==='settings'||parts[0]==='pair')?parts[0]:'driver'
 if(workspace!=='driver')return {workspace,section:parts[1]||'',tab:parts[2]||'',path}
 return {workspace,section:parts[1]||'pit-wall',tab:parts[2]||(parts[1]==='pit-wall'?'live':''),path}
}

function known(route:Route):boolean{
 if(route.workspace==='pair')return true
 if(route.workspace==='settings')return true
 if(route.workspace==='broadcast')return route.section==='race-control'||route.section==='obs'
 return route.section==='pit-wall'||route.section==='wheel'||route.section==='training'||route.section==='career'
}

let current=parse(location.hash)
const listeners=new Set<()=>void>()

function commit(){
 const next=parse(location.hash)
 current=known(next)?next:parse(DEFAULT_ROUTE)
 try{localStorage.setItem(VIEW_STATE_KEY,current.path)}catch{}
 listeners.forEach(l=>l())
}

if(typeof window!=='undefined'){
 window.addEventListener('hashchange',commit)
 if(!location.hash){
  let restored=DEFAULT_ROUTE
  try{restored=localStorage.getItem(VIEW_STATE_KEY)||DEFAULT_ROUTE}catch{}
  history.replaceState(null,'','#'+restored)
  current=parse(restored)
 }
}

export function navigate(path:string,opts?:{replace?:boolean}):void{
 const hash='#'+path
 if(opts?.replace)history.replaceState(null,'',hash)
 else history.pushState(null,'',hash)
 // pushState/replaceState don't fire 'hashchange' - commit manually either way.
 commit()
}

export function useRoute():Route{
 return useSyncExternalStore(
  listener=>{listeners.add(listener);return ()=>listeners.delete(listener)},
  ()=>current,
  ()=>current,
 )
}
