// Minimal external store (no Redux/Zustand): getState/setState/subscribe, plus a
// useStore hook via useSyncExternalStore so components only re-render when their
// own selector's result actually changes. This is what fixes main.tsx's problem
// of one giant `state` useState causing every page to re-render on every /ws frame.
import {useCallback,useRef,useSyncExternalStore} from 'react'

export type Store<T> = {
 getState():T
 setState(partial:Partial<T>|((s:T)=>Partial<T>)):void
 subscribe(listener:()=>void):()=>void
}

export function createStore<T extends object>(initial:T):Store<T>{
 let state=initial
 const listeners=new Set<()=>void>()
 return {
  getState:()=>state,
  setState(partial){
   const next=typeof partial==='function'?(partial as (s:T)=>Partial<T>)(state):partial
   state={...state,...next}
   listeners.forEach(l=>l())
  },
  subscribe(listener){listeners.add(listener);return ()=>listeners.delete(listener)},
 }
}

const refEqual=(a:unknown,b:unknown)=>a===b

export function useStore<T extends object,S>(store:Store<T>,selector:(s:T)=>S,equality:(a:S,b:S)=>boolean=refEqual):S{
 const selectorRef=useRef(selector);selectorRef.current=selector
 const equalityRef=useRef(equality);equalityRef.current=equality
 const lastRef=useRef<{value:S,has:boolean}>({value:undefined as S,has:false})
 const getSnapshot=useCallback(()=>{
  const next=selectorRef.current(store.getState())
  if(lastRef.current.has&&equalityRef.current(lastRef.current.value,next))return lastRef.current.value
  lastRef.current={value:next,has:true}
  return next
 },[store])
 return useSyncExternalStore(store.subscribe,getSnapshot,getSnapshot)
}

export const shallowEqual=(a:unknown,b:unknown):boolean=>{
 if(Object.is(a,b))return true
 if(typeof a!=='object'||a===null||typeof b!=='object'||b===null)return false
 const ak=Object.keys(a as object),bk=Object.keys(b as object)
 if(ak.length!==bk.length)return false
 return ak.every(k=>Object.is((a as any)[k],(b as any)[k]))
}
