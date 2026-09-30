// The '/ws' payload, sliced so a component subscribing to e.g. `s.fuel` doesn't
// re-render when `s.sample.values.speed_kmh` changes 12x/second. This is the fix
// for main.tsx's single `useState<any>(null)` holding the entire payload (see
// docs/UI_MIGRATION_MAP.md's baseline note). Field shapes intentionally mirror the
// existing '/ws' message body (main.tsx:24-37) - this store does not reshape data,
// only exposes it through narrower selectors.
import {createStore,useStore,shallowEqual} from './store'

export type LiveState={raw:any|null,stale:boolean,connected:boolean}

export const liveStore=createStore<LiveState>({raw:null,stale:true,connected:false})

export function setLiveMessage(raw:any):void{
 liveStore.setState({raw,stale:raw?.stale!==false})
}

export function setConnected(connected:boolean):void{
 liveStore.setState(s=>({connected,stale:connected?s.stale:true}))
}

const selectors={
 raw:(s:LiveState)=>s.raw,
 connected:(s:LiveState)=>s.connected,
 stale:(s:LiveState)=>s.stale,
 sampleValues:(s:LiveState)=>s.raw?.sample?.values||{},
 health:(s:LiveState)=>s.raw?.health,
 audio:(s:LiveState)=>s.raw?.audio,
 session:(s:LiveState)=>({status:s.raw?.status,session_id:s.raw?.session_id,source:s.raw?.source,box:s.raw?.box}),
 fuel:(s:LiveState)=>s.raw?.fuel||s.raw?.report?.fuel,
 track:(s:LiveState)=>s.raw?.track_selection,
 events:(s:LiveState)=>s.raw?.events,
 training:(s:LiveState)=>s.raw?.training,
 replay:(s:LiveState)=>s.raw?.replay,
 receiver:(s:LiveState)=>s.raw?.receiver,
 liveAnalysis:(s:LiveState)=>s.raw?.live_analysis,
 liveDelta:(s:LiveState)=>s.raw?.live_delta,
} as const

export function useLive<K extends keyof typeof selectors>(key:K):ReturnType<(typeof selectors)[K]>{
 return useStore(liveStore,selectors[key] as any,shallowEqual) as any
}
