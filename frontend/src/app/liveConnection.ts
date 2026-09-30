// Singleton '/ws' connection (spec §11): created once at app start, never torn
// down by navigation. Reconnect/stale-marking logic is copied from the existing
// main.tsx:30 effect verbatim - this is a correctness-sensitive pattern (the
// 1500ms backoff, marking stale rather than clearing state on close), not a
// rewrite. main.tsx keeps its own useEffect until Phase 2 wires this in; both
// must not run at the same time once that happens (one WebSocket per client).
import {setConnected,setLiveMessage} from './liveStore'

export type ConnectionEvent={onSessionEnded?():void}

let started=false
let socket:WebSocket|null=null
let timeout:number|undefined
let closedByUser=false
let prevSessionId:string|null=null
let prevSource:string|null=null

export function startLiveConnection(events:ConnectionEvent={}):()=>void{
 if(started)return stopLiveConnection
 started=true
 closedByUser=false
 connect(events)
 return stopLiveConnection
}

export function stopLiveConnection():void{
 closedByUser=true
 started=false
 window.clearTimeout(timeout)
 socket?.close()
 socket=null
}

function connect(events:ConnectionEvent):void{
 socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`)
 socket.onopen=()=>setConnected(true)
 socket.onmessage=e=>{
  const s=JSON.parse(e.data)
  setLiveMessage(s)
  if(prevSessionId&&!s.session_id&&s.report&&prevSource===s.source)events.onSessionEnded?.()
  prevSessionId=s.session_id
  prevSource=s.source
 }
 socket.onclose=()=>{
  setConnected(false)
  if(!closedByUser)timeout=window.setTimeout(()=>connect(events),1500)
 }
}
