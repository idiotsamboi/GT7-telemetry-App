// Local OBS overlays (backend/app/obs.py). `frame` is tokenless and read-only (OBS cannot pair); the rest
// need the paired browser like every other /api call.
import {get,post,put} from '../http'

export type ObsIdentity={display_name:string,number:string,team:string,class_name:string}
export type ObsFocus={primary:string,a:string,b:string,team:string,class:string,primary_mode:'manual'|'leader'}
export type ObsOverlaySettings={title?:string,rows?:number,opacity?:number}
export type ObsConfig={
 identity:ObsIdentity
 focus:ObsFocus
 preset:string
 sizes:Record<string,{width:number,height:number}>
 settings:Record<string,ObsOverlaySettings>
}
export type ObsOverlay={
 id:string,name:string,category:string,url:string
 default_width:number,default_height:number,width:number,height:number
 settings:ObsOverlaySettings,sharing:string[],slots:string[]
}
export type ObsDriver={entry_id:string,label:string,team:string,class_name:string,stale:boolean}
export type ObsState={
 mode:'solo'|'league',base_url:string,config:ObsConfig,overlays:ObsOverlay[],drivers:ObsDriver[]
 slots:Record<string,string>,provenance:string|null,group_name:string|null
}
export type ObsFrame={
 mode:'solo'|'league'
 state:any
 workspace:{preset:string,slots:Record<string,string>,branding:Record<string,unknown>,auto_steward:boolean}
 graphic:{id:string,template:string,visible:boolean,x:number,y:number,width:number,height:number,entry_id:string,slot:string,duration_s:number,settings:ObsOverlaySettings}
}

export const obsApi={
 state:()=>get<ObsState>('/api/obs'),
 save:(config:ObsConfig)=>put<ObsState>('/api/obs/config',config),
 reset:()=>post<ObsState>('/api/obs/reset',{}),
 frame:(graphic:string,signal?:AbortSignal)=>get<ObsFrame>('/obs-api/frame',{query:{graphic},signal,timeoutMs:4000}),
}
