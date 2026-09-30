// Capabilities as seen by the UI. The SERVER is authoritative (core/permissions.py enforces every
// command); can() only decides whether to show/enable a control. UI hiding is never enforcement.
import {capabilitiesStore,useGranted} from './stores/capabilitiesStore'

export type CapabilityId=
 |'local.admin'|'settings.write'|'sessions.manage'|'sessions.purge'
 |'telemetry.viewOwn'|'telemetry.viewAll'|'telemetry.publishOwn'
 |'raceControl.setFlag'|'raceControl.message'|'raceControl.messageAll'|'raceControl.steward'|'raceControl.session'|'raceControl.zones'|'raceControl.admit'
 |'graphics.view'|'graphics.edit'|'graphics.take'|'graphics.issueOutput'
 |'league.configure'|'branding.edit'
 |'driver.respond'
 |'overlay.read'

/**
 * Optional resource for scope-aware checks. The server evaluates ownership/sharing rules; the
 * client only mirrors the coarse case where a resource is explicitly marked as not permitted.
 */
export type Resource={id?:string,ownerId?:string,denied?:boolean,[key:string]:unknown}

const check=(granted:readonly string[],cap:CapabilityId,resource?:Resource)=>{
 if(resource?.denied)return false
 return granted.includes(cap)
}

/** Synchronous check against the current grant (use outside React). */
export function can(cap:CapabilityId,resource?:Resource):boolean{
 return check(capabilitiesStore.getState().granted,cap,resource)
}

/** React hook: re-renders when the grant changes. */
export function useCapabilities():{can:(cap:CapabilityId,resource?:Resource)=>boolean,granted:readonly string[]}{
 const granted=useGranted()
 return {granted,can:(cap,resource)=>check(granted,cap,resource)}
}
