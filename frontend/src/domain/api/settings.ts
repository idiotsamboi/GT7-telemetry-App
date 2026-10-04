import {get,post,put} from '../http'
import type {Settings,SettingsSaved,AudioDevices,TrackVenue} from '../types'

export type Capabilities={fields:unknown,unsupported:unknown,rules:unknown,upstream:unknown,[key:string]:unknown}

export const settingsApi={
 get:()=>get<Settings>('/api/settings',{retries:2}),
 put:(settings:Settings|Record<string,unknown>)=>put<SettingsSaved>('/api/settings',settings),
 /** Opens the OS folder dialog on the PC running the app; resolves with '' when cancelled. */
 pickFolder:()=>post<{path:string}>('/api/pick-folder',{},{timeoutMs:300000}),
 tracks:()=>get<TrackVenue[]>('/api/tracks',{retries:2}),
 /** Telemetry field capability matrix (GET /api/capabilities). Distinct from user permissions. */
 capabilities:()=>get<Capabilities>('/api/capabilities',{retries:2}),
 audio:()=>get<AudioDevices>('/api/audio',{timeoutMs:30000}),
}
