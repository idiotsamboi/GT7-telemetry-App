import {get,post,put,del} from '../http'

export type DriverProfile={id:string,name:string,created_at:string,total_xp:number,eligible_sessions:number,comparable_laps:number,provenance?:string}
export type CareerLevel={current:number,total_xp:number,level_start_xp:number,next_level_xp:number|null,max_level:number}
export type CareerSkill={category:string,score:number|null,confidence:number,xp:number,evidence_count:number,source_id:string|null,level?:number,level_name?:string,evidence?:Record<string,unknown>|null}
export type CareerAchievement={definition_id:string,title:string,earned_at:string,source_id:string,evidence:Record<string,unknown>}
export type CareerEvent={id:string,driver_id:string,session_id:string,source_id:string,category:string,amount:number,created_at:string,evidence:Record<string,unknown>}
export type CareerScorecard={session_id:string,driver_id:string,created_at:string,status:'eligible'|'excluded'|'imported',xp_awarded:number,exclusions:string[],evidence:Record<string,unknown>}
export type CareerSettings={active_driver_id:string,enabled:boolean}
export type CareerTrack={layout_id:string,car_id:number,visit_count:number,lap_count:number,pb_ms:number,previous_pb_ms:number|null,pb_improvement_ms:number|null,overall_score:number|null,observed_component_score:number|null,component_coverage:number,components:Record<string,number|null>,confidence:number,source_id:string,last_visit:string}
export type CareerCorner={corner_id:string,name:string,layout_id:string,car_id:number,score:number|null,confidence:number,sample_count:number,current_loss_s:number|null,reference_lap_id:string,source_id:string,method:string}
export type CareerChallenge={id:string,title:string,description:string,why:string,status:string,kind:string,progress:number,reward_xp:number,confidence:number,expires_at:string|null,requirements:Record<string,unknown>,evidence:Record<string,unknown>,completion_evidence:Record<string,unknown>|null}
export type CareerEngineer={focus:string,xp:number,level:number,memory:Record<string,unknown>,missions:{id:string,status:string,challenge:CareerChallenge|null,source_id:string|null}[],briefing:{title:string,why:string,challenge_id:string|null,confidence:number|null,focus_note:string}}
export type CareerChapters={current:string,scope:string,chapters:{id:string,title:string,required_laps:number,required_challenges:number,completed:boolean}[]}
export type DriverTitle={id:string,name:string,description:string,unlocked:boolean}
export type DriverBadge={id:string,name:string,icon:string,unlocked:boolean}
export type RecentGains={recent_xp:number,sessions_evaluated:number,latest_grade?:string|null,delta_score?:number|null}

export type CareerDashboardData={
 profile:DriverProfile
 level:CareerLevel
 skills:CareerSkill[]
 titles?:{equipped:string,titles:DriverTitle[]}
 badges?:DriverBadge[]
 recent_gains?:RecentGains
 achievements:CareerAchievement[]
 recent_events:CareerEvent[]
 scorecards:CareerScorecard[]
 next_action:{title:string,reason:string}
 settings:CareerSettings
 integrity:{algorithm_version:number,reward_source:string,unknown_metrics:string,scope:string}
 tracks?:CareerTrack[]
 challenges?:CareerChallenge[]
 engineer?:CareerEngineer
 career?:CareerChapters
 streaks?:{kind:string,current_count:number,best_count:number,reason:string}[]
}
const root='/api/gamification'
export const gamificationApi={
 dashboard:(signal?:AbortSignal)=>get<CareerDashboardData>(root+'/dashboard',{signal}),
 profiles:(signal?:AbortSignal)=>get<DriverProfile[]>(root+'/profiles',{signal}),
 createProfile:(display_name:string)=>post<DriverProfile>(root+'/profiles',{display_name}),
 selectProfile:(id:string)=>post<unknown>(root+'/profiles/'+encodeURIComponent(id)+'/select',{}),
 settings:()=>get<CareerSettings>(root+'/settings'),
 saveSettings:(enabled:boolean)=>put<CareerSettings>(root+'/settings',{enabled}),
 titles:()=>get<{equipped:string,titles:DriverTitle[]}>(root+'/titles'),
 equipTitle:(name:string)=>post<{equipped:string}>(root+'/titles/equip?title_name='+encodeURIComponent(name),{}),
 badges:()=>get<DriverBadge[]>(root+'/badges'),
 reset:()=>post<unknown>(root+'/reset',{confirmation:'RESET CAREER'}),
 export:()=>get<unknown>(root+'/export'),
 import:(bundle:unknown)=>post<{driver_id:string}>(root+'/import',{bundle}),
 corners:(layout:string)=>get<CareerCorner[]>(root+'/corners/'+encodeURIComponent(layout)),
 challengeAction:(id:string,action:'accept'|'skip')=>post<CareerChallenge>(root+'/challenges/'+encodeURIComponent(id)+'/'+action,{}),
 startMission:(challengeId:string)=>post<unknown>(root+'/missions/'+encodeURIComponent(challengeId)+'/accept',{}),
 setFocus:(focus:string)=>put<CareerEngineer>(root+'/engineer/focus',{focus}),
 clearMemory:()=>del<unknown>(root+'/engineer/memory'),
}
