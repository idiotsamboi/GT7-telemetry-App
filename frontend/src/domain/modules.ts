// Module registration: what a feature contributes (routes, panels, commands, settings sections) so
// the shell, router and command palette can discover features later. Data only; the shell does not
// consume this yet.
import type {CommandId} from './commands'
import type {CapabilityId} from './permissions'

export type ModuleDef={
 id:string
 title:string
 /** Hash routes (see app/router.ts) the module owns. */
 routes:readonly string[]
 /** Panel ids from panels.ts. */
 panels:readonly string[]
 commands:readonly CommandId[]
 /** Settings section ids (Settings page). */
 settingsSections:readonly string[]
 /** Capability needed to show the module at all. */
 requires?:CapabilityId
}

const registry=new Map<string,ModuleDef>()

export function registerModule(def:ModuleDef):void{
 if(registry.has(def.id))throw new Error(`module '${def.id}' registered twice`)
 registry.set(def.id,def)
}
export const modules=():ModuleDef[]=>[...registry.values()]
export const getModule=(id:string):ModuleDef|undefined=>registry.get(id)

const BUILTIN:ModuleDef[]=[
 {id:'live',title:'Pit wall',routes:['/driver/pit-wall/live','/driver/pit-wall/telemetry','/driver/pit-wall/analysis'],panels:['telemetry.chart','track.map','driver.identity','driver.flags','driver.line','track.select'],commands:['session.start','session.end','session.mark_incident','session.set_reference','session.set_target','session.box','session.unbox','source.live','source.demo','source.replay','source.replay_pause','source.replay_seek','source.replay_speed'],settingsSections:['connection','display']},
 {id:'wheel',title:'Wheel dash',routes:['/driver/wheel'],panels:['driver.wheel'],commands:[],settingsSections:[]},
 {id:'engineer',title:'Engineer',routes:['/driver/pit-wall/engineer'],panels:['engineer.brief','engineer.requests'],commands:['engineer.ask','engineer.ai_brief','audio.mute','audio.resume','audio.ptt_start','audio.ptt_stop','audio.hands_free','audio.speaker_test','audio.mic_test'],settingsSections:['audio','engineer']},
 {id:'sessions',title:'Sessions',routes:['/driver/pit-wall/sessions'],panels:[],commands:[],settingsSections:['storage'],requires:'sessions.manage'},
 {id:'training',title:'Track training',routes:['/driver/training'],panels:['training.session','track.visualizer'],commands:['training.start','training.stop','training.retry','training.restart','track.select','track.confirm','track.restore','track.import'],settingsSections:['tracks']},
 {id:'raceControl',title:'Race control',routes:['/broadcast/race-control'],panels:['raceControl.desk'],commands:['group.create','group.configure','group.hosting','group.invite','group.revoke','group.admit','group.remove','group.lock','raceControl.setFlag','raceControl.cancelFlag','raceControl.message','raceControl.decision'],settingsSections:['league'],requires:'league.configure'},
 {id:'obs',title:'OBS overlays',routes:['/broadcast/obs'],panels:['obs.overlays','league.branding'],commands:['branding.update','branding.asset.upload'],settingsSections:['branding'],requires:'graphics.view'},
 {id:'settings',title:'Settings',routes:['/settings'],panels:[],commands:['settings.update'],settingsSections:['general','units','advanced'],requires:'settings.write'},
]
BUILTIN.forEach(registerModule)
