import {get,post,put,send,type RequestOptions} from '../http'
import type {SessionSummary,SessionDetail,SamplesPage,MetadataUpdate,CorrectionRequest,ComparisonRequest,Profile,Settings} from '../types'

type Signal={signal?:AbortSignal}
const enc=encodeURIComponent

export const sessionsApi={
 list:(includeArchived=false,o:Signal={})=>get<SessionSummary[]>('/api/sessions',{...o,query:includeArchived?{include_archived:true}:undefined,retries:2}),
 detail:(id:string,o:Signal={})=>get<SessionDetail>('/api/sessions/'+enc(id),{...o,retries:2}),
 samples:(id:string,q:{channel?:string,after?:number,overview?:boolean}={},o:Signal={})=>get<SamplesPage>(`/api/sessions/${enc(id)}/samples`,{...o,query:q,retries:2}),
 /** The HTML report is a page, not JSON: link to it, don't fetch it. */
 reportUrl:(id:string)=>`/api/sessions/${enc(id)}/report`,
 report:(id:string,o:Signal={})=>send<string>(`/api/sessions/${enc(id)}/report`,{...o,parse:'text',retries:2}),
 metadata:(id:string,body:MetadataUpdate)=>put<{ok:boolean}>(`/api/sessions/${enc(id)}/metadata`,body),
 correct:(id:string,body:CorrectionRequest)=>post<SessionDetail>(`/api/sessions/${enc(id)}/correct`,body),
 archive:(id:string,archived=true)=>post<{ok:boolean}>(`/api/sessions/${enc(id)}/archive`,{archived}),
 retentionPreview:()=>get<{id:string,started:string,status:string,provenance:string}[]>('/api/retention'),
 retentionApply:()=>post<{archived:number,note:string}>('/api/retention'),
 purge:(id:string)=>post<{ok:boolean,note:string}>(`/api/sessions/${enc(id)}/purge`,{confirmation:'DELETE ARCHIVED SESSION'}),
 /** Bundle download: a navigation target (zip), not a fetch. */
 exportUrl:(id:string)=>`/api/sessions/${enc(id)}/export`,
 import:(file:Blob,o:Pick<RequestOptions,'timeoutMs'>={timeoutMs:120000})=>send<{id:string}>('/api/import',{...o,method:'POST',body:file}),
 compare:(body:ComparisonRequest)=>post<Record<string,unknown>>('/api/compare',body,{timeoutMs:60000}),
 profiles:()=>get<Profile[]>('/api/profiles',{retries:2}),
 saveProfile:(name:string,settings:Settings|Record<string,unknown>)=>put<{ok:boolean}>('/api/profiles',{name,settings}),
}
