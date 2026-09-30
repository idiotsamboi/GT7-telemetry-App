import {get,post,put,del} from '../http'

export type DriverProfile={id:string,name:string,created_at:string,total_xp:number,eligible_sessions:number,comparable_laps:number,provenance?:string}
export type CareerLevel={current:number,total_xp:number,level_start_xp:number,next_level_xp:number|null,max_level:number}
export type CareerSkill={category:string,score:number|null,confidence:number,xp:number,evidence_count:number,source_id:string|null,level?:number,level_name?:string,evidence?:Record<string,unknown>|null}
export type CareerAchievement={definition_id:string,title:string,earned_at:string,source_id:string,evidence:Record<string,unknown>}
export type CareerEvent={id:string,driver_id:string,session_id:string,source_id:string,category:string,amount:number,created_at:string,evidence:Record<string,unknown>}
export type CareerScorecard={session_id:string,driver_id:string,created_at:string,status:'eligible'|'excluded'|'imported',xp_awarded:number,exclusions:string[],evidence:Record<string,unknown>}
export type CareerSettings={active_driver_id:string,enabled:boolean}
export type CornerCoverage={available:boolean,sampled:number,catalogued:number|null,percentage:number|null,provenance:string,reason?:string}
export type CareerTrack={layout_id:string,car_id:number,visit_count:number,lap_count:number,pb_ms:number,previous_pb_ms:number|null,pb_improvement_ms:number|null,overall_score:number|null,observed_component_score:number|null,component_coverage:number,components:Record<string,number|null>,confidence:number,source_id:string,last_visit:string,mastery_level?:string,score_confidence?:number,corner_coverage?:CornerCoverage}
export type CareerCorner={corner_id:string,name:string,layout_id:string,car_id:number,score:number|null,confidence:number,sample_count:number,current_loss_s:number|null,reference_lap_id:string,source_id:string,method:string}
export type CornerFinding={corner_id:string,name:string,loss_s:number,best_segment_ms:number,typical_segment_ms:number,confidence:number|null,sample_count:number,consistency:number|null,provenance:string,reason:string,estimated_gain_s?:number,repeatability?:number,evidence:Record<string,unknown>}
export type CornerInsights={layout_id:string,car_id:number,provenance:string,min_samples:number,corners_considered:number,biggest_loss:CornerFinding|null,easiest_gain:CornerFinding|null,challenge:{id:string,status:string,expires_at:string|null,title:string,description:string,corner_id:string,target_segment_ms:number,current:number,target:number,confidence:number|null}|null,streaks:{kind:string,corner_id:string,current_count:number,best_count:number,reason:string|null}[],badges:{id:string,name:string,threshold:number,mastered_on_layout:number,unlocked:boolean,earned_at:string|null}[],note:string}
export type CareerChallenge={id:string,title:string,description:string,why:string,status:string,kind:string,progress:number,reward_xp:number,confidence:number,expires_at:string|null,requirements:Record<string,unknown>,evidence:Record<string,unknown>,completion_evidence:Record<string,unknown>|null,provenance?:string,label?:string,chain?:{chain_id:string,step:number,length:number,prerequisite_id:string|null,title:string}}
export type CareerEngineer={focus:string,xp:number,level:number,memory:Record<string,unknown>,missions:{id:string,status:string,challenge:CareerChallenge|null,source_id:string|null}[],briefing:{title:string,why:string,challenge_id:string|null,confidence:number|null,focus_note:string}}
export type CareerChapters={current:string,scope:string,chapters:{id:string,title:string,required_laps:number,required_challenges:number,completed:boolean}[]}
export type ProgressInfo={current:number,target:number,fraction:number}
export type DriverTitle={id:string,name:string,description:string,unlocked:boolean,stage?:number,progress?:ProgressInfo,evidence?:Record<string,unknown>|null}
export type DriverBadge={id:string,name:string,icon:string,unlocked:boolean,description?:string,earned_at?:string|null,progress?:ProgressInfo|null,evidence?:Record<string,unknown>|null}
export type RecentGainSession={session_id:string,created_at:string,xp_awarded:number,xp_by_category:Record<string,number>,grade:string|null,consistency_score:number|null,consistency_delta:number|null,skill_deltas:Record<string,number>|null,pb_events:number}
export type RecentGains={recent_xp:number,sessions_evaluated:number,latest_grade?:string|null,delta_score?:number|null,provenance?:string,sessions?:RecentGainSession[]}
export type NextUnlock={kind:'title'|'badge',id:string,name:string,progress:ProgressInfo}
export type CareerOverview={profile:{id:string,name:string,total_xp:number,eligible_sessions:number,comparable_laps:number},level:CareerLevel,equipped_title:{id:string,name:string}|null,top_badges:{id:string,name:string,icon:string,earned_at:string|null}[],next_unlock:NextUnlock|null,recent_gains:RecentGains|null,provenance:string}
export type TimelineEvent={id:string,kind:string,title:string,body:string|null,source:string,source_id:string,provenance:string,confidence:number|null,evidence:Record<string,unknown>,created_at:string}
export type CareerTimeline={items:TimelineEvent[],next_cursor:string|null,provenance:string}
export type CareerStats={sessions_processed:number,eligible_sessions:number,excluded_sessions:number,comparable_laps:number,personal_bests:number,tracks_visited:number,total_xp:number,level:number,xp_by_category:Record<string,number>,provenance:string,scope:string}

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
 overview:(signal?:AbortSignal)=>get<CareerOverview>(root+'/overview',{signal}),
 timeline:(limit=50,cursor?:string,signal?:AbortSignal)=>get<CareerTimeline>(root+'/timeline?limit='+limit+(cursor?'&cursor='+encodeURIComponent(cursor):''),{signal}),
 stats:(signal?:AbortSignal)=>get<CareerStats>(root+'/stats',{signal}),
 reset:()=>post<unknown>(root+'/reset',{confirmation:'RESET CAREER'}),
 export:()=>get<unknown>(root+'/export'),
 import:(bundle:unknown)=>post<{driver_id:string}>(root+'/import',{bundle}),
 cornerInsights:(layout:string,car:number)=>get<CornerInsights>(root+'/corners/insights?layout_id='+encodeURIComponent(layout)+'&car_id='+car),
 corners:(layout:string)=>get<CareerCorner[]>(root+'/corners/'+encodeURIComponent(layout)),
 challengeAction:(id:string,action:'accept'|'skip')=>post<CareerChallenge>(root+'/challenges/'+encodeURIComponent(id)+'/'+action,{}),
 startMission:(challengeId:string)=>post<unknown>(root+'/missions/'+encodeURIComponent(challengeId)+'/accept',{}),
 setFocus:(focus:string)=>put<CareerEngineer>(root+'/engineer/focus',{focus}),
 clearMemory:()=>del<unknown>(root+'/engineer/memory'),
}
