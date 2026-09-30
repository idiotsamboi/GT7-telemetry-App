// /api/group/* (backend/app/group/admin.py). The state payloads are large and owned by the
// backend, so they stay loosely typed; request bodies are typed where the UI builds them.
import {send,get,post,put,del} from '../http'
import type {GroupState,GroupRecording,WorkspaceCredential} from '../types'

const B='/api/group/'
const enc=encodeURIComponent
export type GroupMethod='POST'|'PUT'|'DELETE'
export type GroupPolling={signal?:AbortSignal}

export const groupApi={
 /**
  * Path-relative generic call used by the host desk components. Same semantics as the old
  * per-component helper: no body -> GET, otherwise `method` (default POST) with a JSON body.
  * Failures reject with AppError (message = backend `detail`).
  */
 call:<T=any>(path:string,body?:unknown,method:GroupMethod='POST'):Promise<T>=>
  body===undefined?get<T>(B+path):send<T>(B+path,{method,json:body}),
 state:()=>get<GroupState>(B+'state'),
 projection:(o:GroupPolling={})=>get<GroupState|null>(B+'projection',o),
 recordings:()=>get<GroupRecording[]>(B+'recordings'),
 events:()=>get<unknown[]>(B+'events'),
 battles:()=>get<unknown[]>(B+'battles'),
 stewardCues:()=>get<unknown[]>(B+'steward-cues'),
 workspaceProgram:(id:string,o:GroupPolling={})=>get<GroupState>(B+'workspaces/'+enc(id)+'/program',o),

 createLeague:(name:string)=>post(B+'leagues',{name}),
 updateLeague:(id:string,draft:unknown)=>put(B+'leagues/'+enc(id),draft),
 /** Raw image body (the caller enforces the 5 MiB limit before calling). */
 uploadLeagueAsset:(leagueId:string,file:Blob)=>send<any>(B+'leagues/'+enc(leagueId)+'/assets',{method:'POST',body:file,timeoutMs:60000,fallbackMessage:'Upload failed'}),
 createGroup:(body:{name:string,event_name:string,league_id:string,layout_id:string})=>post(B+'create',body),
 configure:(body:Record<string,unknown>)=>put(B+'configure',body),
 hosting:(body:Record<string,unknown>)=>post(B+'hosting',body),
 invite:(role:string)=>post<WorkspaceCredential>(B+'invitations',{role}),
 revoke:(body:Record<string,unknown>)=>post(B+'revoke',body),
 participant:(id:string,status:'admitted'|'removed')=>post(B+'participants/'+enc(id),{status}),
 sessionAction:(action:string)=>post(B+'session/'+enc(action),{}),
 demo:(body:Record<string,unknown>)=>post(B+'demo',body),
 replay:(body:Record<string,unknown>)=>post(B+'replay',body),
 connection:(body:Record<string,unknown>)=>post(B+'connection',body),
 connectionResponse:(body:Record<string,unknown>)=>post(B+'connection/response',body),
 instruction:(body:Record<string,unknown>)=>post(B+'instructions',body),
 removeInstruction:(id:string)=>del(B+'instructions/'+enc(id),{}),
 message:(body:Record<string,unknown>)=>post(B+'messages',body),
 decision:(body:Record<string,unknown>)=>post(B+'decisions',body),
 focusBattle:(id:string,body:{workspace_id:string,take:boolean,ensure_graphics:boolean})=>post(B+'battles/'+enc(id)+'/focus',body),
 dismissBattle:(id:string)=>post(B+'battles/'+enc(id)+'/dismiss',{}),

 createWorkspace:(body:Record<string,unknown>)=>post(B+'workspaces',body),
 saveWorkspace:(id:string,draft:unknown)=>put(B+'workspaces/'+enc(id),draft),
 takeWorkspace:(id:string)=>post(B+'workspaces/'+enc(id)+'/take',{}),
 clearWorkspace:(id:string)=>post(B+'workspaces/'+enc(id)+'/clear',{}),
 shareWorkspace:(id:string,participants:string[])=>post(B+'workspaces/'+enc(id)+'/share',{participants}),
 issueCredential:(id:string)=>post<WorkspaceCredential>(B+'workspaces/'+enc(id)+'/credential',{}),
}
