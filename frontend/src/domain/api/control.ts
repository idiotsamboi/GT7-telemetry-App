import {get,post} from '../http'
import type {ControlResponse,CommandAnswer,RecoveryAction,Settings} from '../types'

export const controlApi={
 /** POST /api/control. Audio probes can take several seconds, so the timeout is generous. */
 control:(action:string,value?:string|number|null)=>post<ControlResponse>('/api/control',{action,value},{timeoutMs:60000}),
 command:(text:string)=>post<CommandAnswer>('/api/command',{text}),
 recovery:(action:RecoveryAction)=>post<{ok:boolean,action:RecoveryAction,message:string,settings:Settings}>('/api/recovery',{action}),
 health:()=>get<{ok:boolean,service:string}>('/api/health',{retries:1}),
 /** Pairs this browser (sets the gt7_token cookie). Loopback browsers may omit the token. */
 pair:(token:string)=>post<{paired:boolean}>('/api/pair',{token}),
 state:()=>get<Record<string,unknown>>('/api/state'),
}
