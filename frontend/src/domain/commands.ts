// Command dispatcher over POST /api/commands/{id}. run() never throws for a normal backend
// refusal: the CommandResult is returned as-is. Only a transport failure is mapped to a local
// `connection_lost` result. UI reacts to `code`/`message`, never to inferred state changes.
import {AppError,codeFromStatus,detailMessage,isCommandResult,type CommandResult,type ResultCode} from './http'
import {platformApi} from './api/platform'

export type CommandId=
 |'session.start'|'session.end'|'session.mark_incident'|'session.set_reference'|'session.set_target'|'session.box'|'session.unbox'
 |'source.live'|'source.demo'|'source.replay'|'source.replay_pause'|'source.replay_seek'|'source.replay_speed'
 |'audio.mute'|'audio.resume'|'audio.ptt_start'|'audio.ptt_stop'|'audio.hands_free'|'audio.speaker_test'|'audio.mic_test'
 |'engineer.ask'|'engineer.ai_brief'
 |'track.select'|'track.confirm'|'track.restore'|'track.import'
 |'training.start'|'training.stop'|'training.retry'|'training.restart'
 |'settings.update'
 |'group.create'|'group.configure'|'group.hosting'|'group.invite'|'group.revoke'|'group.admit'|'group.remove'|'group.lock'
 |'raceControl.setFlag'|'raceControl.cancelFlag'|'raceControl.message'|'raceControl.decision'
 |'graphics.saveDraft'|'graphics.take'|'graphics.clearProgram'|'graphics.focusBattle'|'graphics.credential.issue'
 |'branding.update'|'branding.asset.upload'

export type CommandOutcome={id:CommandId,payload:unknown,result:CommandResult<unknown>,at:number,silent:boolean}
export type ResultListener=(outcome:CommandOutcome)=>void

const listeners=new Set<ResultListener>()

/** Subscribe to every command result (toast / inline notification hook). Returns unsubscribe. */
export function onResult(listener:ResultListener):()=>void{
 listeners.add(listener)
 return ()=>{listeners.delete(listener)}
}

function emit(outcome:CommandOutcome):void{
 // A broken subscriber must not break command flow.
 listeners.forEach(l=>{try{l(outcome)}catch{/* ignored */}})
}

const local=(code:ResultCode,message:string,diagnostic:string|null=null):CommandResult<never>=>({
 code,ok:code==='ok',message,diagnostic,data:null,command_id:'local-'+Math.random().toString(36).slice(2,10),audit_id:null,
})

export type RunOptions={
 /** Skip notification subscribers (e.g. for high-frequency commands like ptt). */
 silent?:boolean
}

export async function run<T=unknown>(id:CommandId,payload?:unknown,options:RunOptions={}):Promise<CommandResult<T>>{
 let result:CommandResult<unknown>
 try{
  const r=await platformApi.command(id,payload)
  if(isCommandResult(r.body))result=r.body
  else if(r.ok)result=local('ok','')
  else{
   const detail=r.body&&typeof r.body==='object'?(r.body as {detail?:unknown}).detail:r.body
   const missing=r.status===404
   result=local(missing?'unavailable':codeFromStatus(r.status),missing?'This command is not available on the connected backend':detailMessage(detail,`Command failed (${r.status})`),`HTTP ${r.status}`)
  }
 }catch(error){
  const timeout=error instanceof AppError&&error.code==='timeout'
  result=local(timeout?'timeout':'connection_lost',timeout?'The command timed out':'Connection to the app was lost',error instanceof Error?error.message:null)
 }
 emit({id,payload,result,at:Date.now(),silent:!!options.silent})
 return result as CommandResult<T>
}
