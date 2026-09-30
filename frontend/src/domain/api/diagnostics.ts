import {get,post} from '../http'
import type {Diagnostics,DiagnosticsBundle,ClientErrorReport} from '../types'

export const diagnosticsApi={
 get:()=>get<Diagnostics>('/api/diagnostics',{retries:1}),
 /** Redacted JSON bundle for support; contains no tokens. */
 copy:()=>post<DiagnosticsBundle>('/api/diagnostics/copy',{}),
 reportClientError:(report:ClientErrorReport)=>post<unknown>('/api/client-errors',report,{timeoutMs:5000}),
}
