import {get} from '../http'
import type {EngineerRequest} from '../types'

export const engineerApi={
 requests:()=>get<{count:number,requests:EngineerRequest[]}>('/api/engineer/requests',{retries:2,fallbackMessage:'Could not load engineer requests'}),
}
