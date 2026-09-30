// Typed slice selectors over liveStore's raw '/ws' payload. liveStore's public shape is untouched;
// these are plain (LiveState)=>slice functions usable with useStore(liveStore, selectX, shallowEqual).
import {useStore,shallowEqual} from '../../app/store'
import {liveStore,type LiveState} from '../../app/liveStore'
import type {ServiceStatus} from '../types'

export type ReceiverSlice={connected?:boolean,packets?:number,age_s?:number|null,[key:string]:unknown}|undefined

export const selectReceiver=(s:LiveState):ReceiverSlice=>s.raw?.receiver
export const selectServices=(s:LiveState):ServiceStatus[]|undefined=>Array.isArray(s.raw?.services)?s.raw.services:undefined
export const selectSource=(s:LiveState):string|undefined=>s.raw?.source
export const selectSessionId=(s:LiveState):string|null=>s.raw?.session_id??null

export const useReceiver=()=>useStore(liveStore,selectReceiver,shallowEqual)
export const useLiveServices=()=>useStore(liveStore,selectServices)
