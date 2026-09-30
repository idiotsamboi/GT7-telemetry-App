import {get,post,put} from '../http'
import type {TrackMapSnapshot} from '../types'

export const tracksApi={
 map:()=>get<TrackMapSnapshot>('/api/track-map'),
 importMap:(layout_id:string,points:number[][])=>put<TrackMapSnapshot>('/api/track-map',{layout_id,points}),
 select:(layout_id:string)=>post<TrackMapSnapshot>('/api/track-map/select',{layout_id}),
 confirm:(candidate_id:string,layout_id:string)=>post<TrackMapSnapshot>('/api/track-map/confirm',{candidate_id,layout_id}),
 restore:(layout_id:string,revision:string)=>post<TrackMapSnapshot>('/api/track-map/restore',{layout_id,revision}),
 library:()=>get<{layouts:Record<string,unknown>[]}>('/api/track-map/library'),
}
