import {test,expect,type Page} from '../../frontend/node_modules/@playwright/test'
import type {CareerDashboardData,DriverProfile} from '../../frontend/src/domain/api/gamification'

const driver:DriverProfile={id:'driver-a',name:'Test driver',created_at:'2026-09-30T12:00:00Z',total_xp:140,eligible_sessions:2,comparable_laps:6}
const dashboard:CareerDashboardData={
 profile:driver,level:{current:2,total_xp:140,level_start_xp:100,next_level_xp:300,max_level:100},
 skills:[{category:'consistency',score:72.5,confidence:.3,xp:60,evidence_count:6,source_id:'session-2'},{category:'pace',score:null,confidence:0,xp:0,evidence_count:0,source_id:null}],
 achievements:[{definition_id:'first-session',title:'First eligible session',earned_at:'2026-09-30T12:00:00Z',source_id:'session-1',evidence:{eligible_laps:3}}],
 recent_events:[{id:'xp-1',driver_id:driver.id,session_id:'session-2',source_id:'session-2',category:'consistency',amount:30,created_at:'2026-09-30T12:00:00Z',evidence:{algorithm_version:1,comparable_laps:3}}],
 scorecards:[{session_id:'session-demo',driver_id:driver.id,created_at:'2026-09-30T12:00:00Z',status:'excluded',xp_awarded:0,exclusions:['non_live_source'],evidence:{source:'demo'}}],
 next_action:{title:'Build a repeatable rhythm',reason:'Record comparable live laps to strengthen your consistency evidence.'},
 settings:{active_driver_id:driver.id,enabled:true},integrity:{algorithm_version:1,reward_source:'finalized live sessions',unknown_metrics:'unavailable',scope:'foundation'},
}
async function mockCareer(page:Page,{empty=false,fail=false}:{empty?:boolean,fail?:boolean}={}){
 let data=structuredClone(dashboard),profiles=[structuredClone(driver)],failure=fail,requests=0
 const mutations:Array<{path:string,body:unknown}>=[]
 if(empty){data.skills=data.skills.map(skill=>({...skill,score:null,confidence:0,evidence_count:0,xp:0,source_id:null}));data.achievements=[];data.recent_events=[];data.scorecards=[]}
 await page.routeWebSocket('**/ws',()=>{})
 await page.route('**/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname
  if(!path.startsWith('/api/'))return route.continue()
  const reply=(body:unknown,status=200)=>route.fulfill({status,json:body})
  if(!path.startsWith('/api/gamification'))return reply({})
  if(path.endsWith('/dashboard')){requests++;return failure?reply({detail:'Career storage temporarily unavailable'},503):reply(data)}
  if(request.method()==='GET')return reply(path.endsWith('/profiles')?profiles:path.endsWith('/export')?{version:1,profiles}:data.settings)
  const body=request.postDataJSON() as Record<string,unknown>;mutations.push({path,body})
  if(path.endsWith('/profiles')){const profile={...driver,id:'driver-b',name:String(body.display_name)};profiles.push(profile);return reply(profile)}
  if(path.endsWith('/select')){data={...data,profile:profiles.find(item=>path.includes(item.id))??driver};return reply(data.profile)}
  if(path.endsWith('/settings')){data={...data,settings:{...data.settings,enabled:Boolean(body.enabled)}};return reply(data.settings)}
  if(path.endsWith('/reset')){data=structuredClone(dashboard);return reply({ok:true})}
  return reply({})
 })
 return {mutations,recover:()=>{failure=false},requests:()=>requests}
}
test('career routes show evidence, unavailable subsystems and excluded history',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));await mockCareer(page)
 await page.goto('/#/driver/career')
 await expect(page.getByRole('heading',{name:'Build a repeatable rhythm'})).toBeVisible()
 await expect(page.getByText('30% confidence · 6 evidence samples')).toBeVisible()
 await page.getByRole('link',{name:'Skills',exact:true}).click()
 await expect(page.getByText('Insufficient evidence',{exact:true})).toBeVisible()
 const measured=page.locator('.career-skill').filter({has:page.getByRole('heading',{name:'Consistency',exact:true})})
 await measured.getByText('View evidence',{exact:true}).click();await expect(measured.locator('pre')).toContainText('session-2')
 for(const name of ['Seasons']){
  await page.getByRole('link',{name,exact:true}).click();await expect(page.getByText('Unavailable · Foundation release',{exact:true})).toBeVisible()
 }
 await page.getByRole('link',{name:'Tracks',exact:true}).click();await expect(page.getByText('No eligible track evidence yet. Ambiguous layouts do not receive progression.')).toBeVisible()
 await page.getByRole('link',{name:'Challenges',exact:true}).click();await expect(page.getByText(/Complete at least three comparable live laps/)).toBeVisible()
 await page.getByRole('link',{name:'History',exact:true}).click()
 await expect(page.getByText('Excluded evidence: non_live_source')).toBeVisible()
 await page.getByRole('link',{name:'Achievements',exact:true}).click()
 await expect(page.getByRole('heading',{name:'First eligible session'})).toBeVisible()
 expect(errors).toEqual([])
})
test('profiles, settings and explicit reset confirmation use typed API actions',async({page})=>{
 const state=await mockCareer(page);await page.goto('/#/driver/career')
 await page.getByText('Manage career',{exact:true}).click()
 await page.getByLabel('New driver name').fill('Second driver');await page.getByRole('button',{name:'Create driver',exact:true}).click()
 await expect(page.getByRole('status')).toContainText('Driver profile created')
 await expect(page.getByLabel('Driver profile')).toBeEnabled();await page.getByLabel('Driver profile').selectOption('driver-b')
 await expect(page.getByRole('heading',{name:'Second driver',exact:true})).toBeVisible()
 await expect(page.getByLabel('Enable career rewards')).toBeEnabled();await page.getByLabel('Enable career rewards').click()
 await expect(page.getByText(/Career rewards are paused/)).toBeVisible()
 const reset=page.getByRole('button',{name:'Reset career permanently'});await expect(reset).toBeDisabled()
 await page.getByLabel('Type RESET CAREER to confirm').fill('RESET');await expect(reset).toBeDisabled()
 await page.getByLabel('Type RESET CAREER to confirm').fill('RESET CAREAR');await expect(reset).toBeDisabled()
 await page.getByLabel('Type RESET CAREER to confirm').fill('RESET CAREER');await expect(reset).toBeEnabled();await reset.click()
 await expect(page.getByRole('status')).toContainText('Career reset completed')
 expect(state.mutations).toEqual([{path:'/api/gamification/profiles',body:{display_name:'Second driver'}},{path:'/api/gamification/profiles/driver-b/select',body:{}},{path:'/api/gamification/settings',body:{enabled:false}},{path:'/api/gamification/reset',body:{confirmation:'RESET CAREER'}}])
})
test('failed load can recover and empty career never invents a score',async({page})=>{
 const state=await mockCareer(page,{empty:true,fail:true});await page.goto('/#/driver/career')
 await expect(page.getByRole('alert')).toContainText('Career storage temporarily unavailable')
 state.recover();await page.getByRole('button',{name:'Retry career'}).click()
 await expect(page.getByRole('heading',{name:'Your skill profile is still learning'})).toBeVisible()
 await page.getByRole('link',{name:'Achievements',exact:true}).click();await expect(page.getByRole('heading',{name:'No achievements earned yet'})).toBeVisible()
 await page.getByRole('link',{name:'History',exact:true}).click();await expect(page.getByText('No finalized session scorecards yet.')).toBeVisible()
})
test('mobile layout stays within viewport and refresh is bounded',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.clock.install();const state=await mockCareer(page)
 await page.goto('/#/driver/career');await expect(page.getByRole('heading',{name:'Build a repeatable rhythm'})).toBeVisible()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 const initial=state.requests();await page.clock.runFor(20000)
 expect(state.requests()-initial).toBeLessThanOrEqual(2)
 expect(state.requests()).toBeGreaterThan(initial)
 const beforeLeave=state.requests();await page.getByRole('link',{name:'Open Pit Wall'}).click();await page.clock.runFor(20000);expect(state.requests()).toBe(beforeLeave)
})
