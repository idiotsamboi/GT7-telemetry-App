// Toast/inline notification queue, fed by commands.ts results and by reported errors.
// Not persisted; the shell decides how to render it.
import {createStore,useStore} from '../../app/store'
import {onResult,type CommandOutcome} from '../commands'

export type NotificationLevel='success'|'info'|'warning'|'error'
export type Notification={
 id:number
 level:NotificationLevel
 message:string
 at:number
 commandId?:string
 code?:string
 diagnostic?:string|null
}

const MAX=50
let seq=0
export const notificationsStore=createStore<{items:Notification[]}>({items:[]})

export function notify(level:NotificationLevel,message:string,extra:Partial<Notification>={}):number{
 const id=++seq
 notificationsStore.setState(s=>({items:[...s.items,{id,level,message,at:Date.now(),...extra}].slice(-MAX)}))
 return id
}
export const notifyError=(error:unknown,fallback='Something went wrong')=>notify('error',error instanceof Error&&error.message?error.message:fallback)
export const dismissNotification=(id:number)=>notificationsStore.setState(s=>({items:s.items.filter(n=>n.id!==id)}))
export const clearNotifications=()=>notificationsStore.setState({items:[]})

export function notificationFromOutcome(o:CommandOutcome):Omit<Notification,'id'>|null{
 if(o.silent)return null
 const {result}=o
 if(result.ok&&!result.message)return null
 const level:NotificationLevel=result.ok?'success':result.code==='rate_limited'||result.code==='invalid_input'||result.code==='invalid_state'?'warning':'error'
 return {level,message:result.message||`Command ${o.id} failed (${result.code})`,at:o.at,commandId:o.id,code:result.code,diagnostic:result.diagnostic}
}

let off:(()=>void)|null=null
/** Subscribes the store to command results. Idempotent; returns the unsubscribe. */
export function startNotifications():()=>void{
 if(off)return off
 const unsubscribe=onResult(o=>{const n=notificationFromOutcome(o);if(n)notify(n.level,n.message,{commandId:n.commandId,code:n.code,diagnostic:n.diagnostic})})
 off=()=>{unsubscribe();off=null}
 return off
}

export const useNotifications=()=>useStore(notificationsStore,s=>s.items)
