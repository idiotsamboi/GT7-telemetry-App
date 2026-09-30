// What the server says this browser may do (GET /api/me/capabilities). The server is
// authoritative; this is only used to hide/disable controls. Until the endpoint exists the store
// falls back to the paired-local-operator set (mirror of ROLES['local'] in core/permissions.py).
import {createStore,useStore} from '../../app/store'
import {platformApi} from '../api/platform'
import type {CapabilityId} from '../permissions'

export const LOCAL_DEFAULT:readonly CapabilityId[]=[
 'local.admin','settings.write','sessions.manage','sessions.purge',
 'telemetry.viewOwn','telemetry.viewAll','telemetry.publishOwn',
 'raceControl.setFlag','raceControl.message','raceControl.messageAll','raceControl.steward','raceControl.session','raceControl.zones','raceControl.admit',
 'graphics.view','graphics.edit','graphics.take','graphics.issueOutput',
 'league.configure','branding.edit',
]

export type CapabilitiesState={granted:readonly string[],source:'default'|'server',loaded:boolean,error:string|null}
export const capabilitiesStore=createStore<CapabilitiesState>({granted:LOCAL_DEFAULT,source:'default',loaded:false,error:null})

export async function refreshCapabilities():Promise<void>{
 try{
  const grant=await platformApi.myCapabilities()
  capabilitiesStore.setState(grant?{granted:grant.capabilities,source:'server',loaded:true,error:null}:{granted:LOCAL_DEFAULT,source:'default',loaded:true,error:null})
 }catch(e){capabilitiesStore.setState({loaded:true,error:e instanceof Error?e.message:'Could not load capabilities'})}
}

export const useGranted=()=>useStore(capabilitiesStore,s=>s.granted)
