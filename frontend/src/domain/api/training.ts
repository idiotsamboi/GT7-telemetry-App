import {get,post} from '../http'
import type {TrainingCandidate,TrainingProgress} from '../types'

export type TrainingStatus=Record<string,unknown>

export const trainingApi={
 candidates:()=>get<TrainingCandidate[]>('/api/training/candidates'),
 progress:()=>get<TrainingProgress[]>('/api/training/progress'),
 start:(layout_id:string)=>post<TrainingStatus>('/api/training/start',{layout_id}),
 stop:()=>post<TrainingStatus>('/api/training/stop',{}),
 retryLap:()=>post<TrainingStatus>('/api/training/retry-lap',{}),
 restart:(layout_id:string)=>post<TrainingProgress[]>('/api/training/restart',{layout_id}),
}
