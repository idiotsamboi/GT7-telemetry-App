// Registry of the panels that exist today (data only; no React imports). `component` is a key the
// shell resolves to a lazily-imported component later - the domain never imports components.
export type PanelDef={
 id:string
 title:string
 /** Key resolved to a component by the shell (e.g. 'Chart' -> src/Chart.tsx). */
 component:string
 /** Live '/ws' slices or telemetry channels the panel reads. */
 channels:readonly string[]
 minSize:{w:number,h:number}
 /** Wrap in an ErrorBoundary panel variant. */
 boundary?:boolean
}

export const PANELS:readonly PanelDef[]=[
 {id:'telemetry.chart',title:'Telemetry chart',component:'Chart',channels:['speed_kmh','throttle','brake'],minSize:{w:320,h:200},boundary:true},
 {id:'track.map',title:'Circuit & driving line',component:'MapCard',channels:['position','track_selection'],minSize:{w:280,h:220},boundary:true},
 {id:'track.visualizer',title:'Track capture',component:'TrackVisualizer',channels:['training'],minSize:{w:280,h:220},boundary:true},
 {id:'track.select',title:'Circuit & layout',component:'RaceVisuals',channels:['track_selection'],minSize:{w:320,h:320}},
 {id:'driver.identity',title:'Car identity',component:'CarIdentity',channels:['car'],minSize:{w:240,h:120}},
 {id:'driver.flags',title:'Flags',component:'FlagIndicator',channels:['flags'],minSize:{w:160,h:80}},
 {id:'driver.line',title:'Driving line',component:'DrivingLine',channels:['position'],minSize:{w:240,h:200}},
 {id:'driver.wheel',title:'Wheel dash',component:'WheelDash',channels:['speed_kmh','rpm','gear','fuel'],minSize:{w:480,h:270}},
 {id:'engineer.brief',title:'Local AI brief',component:'LocalBrief',channels:['local_ai'],minSize:{w:280,h:160}},
 {id:'engineer.requests',title:'Engineer request library',component:'RequestLibrary',channels:[],minSize:{w:320,h:240}},
 {id:'training.session',title:'Track training',component:'Training',channels:['training'],minSize:{w:480,h:360}},
 {id:'raceControl.desk',title:'Race desk',component:'RaceDesk',channels:[],minSize:{w:640,h:480}},
 {id:'graphics.preview',title:'Graphics preview',component:'Composition',channels:[],minSize:{w:320,h:180},boundary:true},
 {id:'graphics.studio',title:'Broadcast studio',component:'GroupStudio',channels:[],minSize:{w:800,h:480}},
 {id:'league.branding',title:'League branding',component:'LeagueBranding',channels:[],minSize:{w:400,h:320}},
]

const byId=new Map(PANELS.map(p=>[p.id,p]))
export const getPanel=(id:string):PanelDef|undefined=>byId.get(id)
