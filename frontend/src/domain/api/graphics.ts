// Public group / overlay endpoints (backend/app/group/public.py), used by the spectator page and
// the OBS overlay. Overlay tokens live in the URL FRAGMENT (never sent to the server, never in a
// query string) and are sent only as a Bearer header when requesting a subscribe ticket.
import {get,post} from '../http'
import type {GroupInfo,GroupJoinRequest,OverlayTicket} from '../types'

const P='/group-api/'

export type OverlayLocation={overlay:boolean,workspaceId:string,credential:string,graphic:string}

export const graphicsApi={
 info:()=>get<GroupInfo>(P+'info'),
 join:(body:GroupJoinRequest)=>post<unknown>(P+'join',body),
 me:()=>get<Record<string,unknown>>(P+'me'),
 state:()=>get<Record<string,unknown>>(P+'state'),
 workspaces:()=>get<Record<string,unknown>[]>(P+'workspaces'),
 /** Ticket for the /group-api/subscribe WebSocket. The credential travels as a Bearer header. */
 ticket:(o:{overlay:boolean,workspaceId?:string,credential?:string})=>post<OverlayTicket>(P+'ticket',
  {overlay:o.overlay,workspace_id:o.overlay?o.workspaceId:undefined},
  {headers:o.credential?{Authorization:'Bearer '+o.credential}:undefined}),
 /** ws(s):// URL of the subscribe socket; the socket itself stays in the component. */
 subscribeUrl:(origin:string=location.origin)=>origin.replace(/^http/,'ws')+P+'subscribe',
 /** Overlay URL with the credential in the fragment. */
 overlayUrl:(origin:string,workspaceId:string,credential:string,graphicId?:string)=>
  `${origin}/overlay/${workspaceId}#access=${credential}`+(graphicId?`&graphic=${encodeURIComponent(graphicId)}`:''),
 /** Reads the overlay context from a Location-like object (path + fragment). */
 parseLocation:(loc:{pathname:string,hash:string}=location):OverlayLocation=>{
  const params=new URLSearchParams(loc.hash.slice(1))
  return {overlay:loc.pathname.startsWith('/overlay/'),workspaceId:loc.pathname.split('/')[2]||'',credential:params.get('access')||'',graphic:params.get('graphic')||''}
 },
}
