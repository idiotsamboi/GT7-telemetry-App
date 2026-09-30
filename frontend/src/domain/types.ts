// Hand-written mirrors of the backend contracts the frontend actually uses. Only what is used is
// typed; everything else stays `unknown`/loose on purpose. Server payloads are authoritative.
export type {CommandResult,ResultCode} from './http'
export {isCommandResult} from './http'

export type Page<T>={items:T[],next:string|null,total?:number}

// ---- sessions (backend/app/storage/store.py) ----
export type SessionMeta={track?:string,layout?:string,direction?:'unknown'|'forward'|'reverse',car_id?:number|null,notes?:string,tags?:string[],reference_lap?:string,[key:string]:unknown}
export type SessionSummary={
 id:string
 started:string
 ended:string|null
 status:string
 provenance:string
 protected:boolean|number
 archived_at:string|null
 meta:SessionMeta
 report:Record<string,unknown>|null
}
export type Lap={id:string,complete?:boolean,partial?:boolean,comparable?:boolean,user_excluded?:boolean,user_correction?:string,[key:string]:unknown}
export type SessionDetail=SessionSummary&{laps:Lap[],events:Record<string,unknown>[]}
export type SampleRow={mono:number,lap_id?:string,values:Record<string,number|null>,[key:string]:unknown}
export type SamplesPage={rows:SampleRow[],next:number|null,limit:number,more_possible:boolean}
export type MetadataUpdate={notes:string,tags:string[],protected:boolean,track?:string|null,layout?:string|null,direction?:'unknown'|'forward'|'reverse'|null,reference_lap?:string|null}
export type CorrectionRequest={status?:'completed'|'interrupted'|null,lap_id?:string|null,exclude?:boolean,reason:string}
export type ComparisonRequest={reference_session:string,reference_lap:string,candidate_session:string,candidate_lap:string}
export type Profile={name:string,payload:string,[key:string]:unknown}

// ---- settings (backend/app/config.py Settings) ----
export type Units={speed:'kmh'|'mph',temperature:'C'|'F',fuel:'L'|'gal_us'|'gal_uk',distance:'m'|'km'|'mi',pressure:'bar'|'psi'}
export type Settings={
 schema_version:number
 ps5_ip:string|null
 udp_bind:string
 udp_port:number
 remote_port:number
 http_host:string
 http_port:number
 allowed_origins:string[]
 variant:'A'|'B'|'~'|'C'
 heartbeat:number
 ui_hz:number
 stale_seconds:number
 interrupt_seconds:number
 reserve_l:number
 race_laps:number|null
 race_minutes:number|null
 extra_lap:boolean
 target_ms:number|null
 mode:'Quiet'|'Normal'|'Detailed'|'Coaching'|'Critical-only'
 hard_mute:boolean
 speech_enabled:boolean
 speech_gap:number
 speech_per_min:number
 speech_seconds:number
 tts:'espeak'|'piper'
 voice:string
 voice_rate:number
 voice_volume:number
 piper_model:string
 vosk_model:string
 input_device:number|null
 output_device:number|null
 mic_rate:number
 recognition_confidence:number
 retain_transcripts:boolean
 hands_free:boolean
 local_ai_enabled:boolean
 local_ai_model:string
 local_ai_binary:string
 local_ai_port:number
 local_ai_interval:number
 trust_c_fields:boolean
 low_fuel_l:number
 tyre_limit_c:number|null
 tyre_imbalance_c:number
 alert_cooldown:number
 raw_capture:boolean
 track_id:string
 track:string
 layout:string
 direction:'unknown'|'forward'|'reverse'
 setup_notes:string
 pit_limit_kmh:number|null
 pit_region:number[]|null
 theme:'dark'|'light'
 minimal:boolean
 reduced_motion:boolean
 retention_days:number
 battles_desk_chime:boolean
 local_ai_rephrase:boolean
 max_save_percent:number
 fuel_time_slope_s_per_l:number|null
 pit_loss_s:number|null
 refuel_rate_lps:number|null
 tyre_heat_rate_c_s:number
 tyre_heat_anomaly_c:number
 coaching_min_loss_s:number
 // schema v2
 units:Units
 performance_profile:'AUTO'|'DESKTOP'|'LOW_POWER'
 log_level:'DEBUG'|'INFO'|'WARNING'|'ERROR'
 feature_flags:Record<string,boolean>
 safe_mode_on_crash:boolean
 developer_mode:boolean
}
export type SettingsSaved={settings:Settings,restart_required:string}
export type AudioDevices={devices:{name:string,[key:string]:unknown}[],[key:string]:unknown}

// ---- tracks / training ----
export type TrackLayout={id:string,name:string,[key:string]:unknown}
export type TrackVenue={id:string,name:string,logo?:string,logo_kind?:string,layouts:TrackLayout[],[key:string]:unknown}
export type TrackMapSnapshot={layout_id?:string,status?:string,points?:number[][],versions?:{revision:string,updated?:number|null}[],unnamed_candidates?:{id:string,created:number,quality:{length_m:number},suggestions?:{layout_id:string,name:string}[]}[],save_error?:string,save_pending?:boolean,[key:string]:unknown}
export type TrainingCandidate={id:string,name:string,track:string,venue_id:string,direction:string,length_m:number}
export type TrainingGoal={laps_saved:number,points_saved:number,points_per_km:number,points_per_km_target:number,percent:number,complete:boolean}
export type TrainingProgress=TrainingGoal&{layout_id:string,name:string,venue_name:string,direction:string,length_m:number}

// ---- engineer ----
export type EngineerRequest={request:string,category:string,[key:string]:unknown}

// ---- control ----
export type ControlAction=string
export type ControlResponse={ok?:boolean,message?:string,[key:string]:unknown}
export type CommandAnswer={answer:string,navigate?:string,[key:string]:unknown}
export type RecoveryAction='live'|'display'|'connection'|'audio'

// ---- v2 platform (services / features / diagnostics / capabilities / audit) ----
export type ServiceState='ok'|'degraded'|'down'|'starting'|'stopped'|'unknown'
export type ServiceStatus={id:string,name?:string,state:ServiceState|string,detail?:string|null,since?:number|null,[key:string]:unknown}
export type FeatureFlag={id:string,enabled:boolean,default?:boolean,description?:string,stability?:string,[key:string]:unknown}
export type Diagnostics={version?:string,uptime_s?:number,platform?:Record<string,unknown>,services?:ServiceStatus[],[key:string]:unknown}
export type DiagnosticsBundle=Record<string,unknown>
export type AuditEntry={id:string,ts:number|string,command?:string,code?:string,principal?:string,message?:string,[key:string]:unknown}
export type ChannelInfo={id:string,[key:string]:unknown}
export type CapabilityGrant={capabilities:string[],principal?:{kind:string,subject?:string,group_id?:string|null}}
export type ClientErrorReport={message:string,stack:string,component:string,url:string}

// ---- group (backend/app/group/*) - loose: the state payloads are large and owned by the backend ----
export type GroupState=Record<string,any>
export type GroupWorkspace=Record<string,any>
export type GroupRecording={session_id:string,name:string,event_name:string,started:number|null,[key:string]:unknown}
export type GroupInfo={name?:string,[key:string]:unknown}
export type WorkspaceCredential={credential:string,[key:string]:unknown}
export type OverlayTicket={ticket:string}
export type GroupJoinRequest={credential:string,identity:{display_name:string},accepted_sharing:string[]}

