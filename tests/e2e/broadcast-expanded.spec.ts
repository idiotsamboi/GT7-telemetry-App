import path from 'node:path';
import {test,expect} from '../../frontend/node_modules/@playwright/test';
test('expanded graphics, draft retention, flag precedence and scoped OBS data',async({page})=>{
 test.setTimeout(90000);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.request.post('/api/pair',{data:{}});
 const old=await (await page.request.get('/api/group/state')).json();if(old.group)await page.request.post('/api/group/session/close',{data:{}});
 expect((await page.request.post('/api/group/demo',{data:{action:'start',members:4}})).ok()).toBeTruthy();
 await page.request.post('/api/group/instructions',{data:{flag:'red',scope:'global',reason:'Synthetic red restriction',expires_in:120}});await page.request.post('/api/group/instructions',{data:{flag:'green',scope:'global',reason:'Later green instruction',expires_in:120}});
 await page.goto('/');await page.getByRole('button',{name:'Race Control',exact:true}).click();await expect(page.locator('.rc-alarm-main')).toContainText('RED FLAG');
 await page.getByRole('button',{name:'Studio',exact:true}).click();await page.getByRole('button',{name:'Edit',exact:true}).click();await page.getByText('Add a graphic',{exact:true}).click();
 for(const name of ['Classification strip','Team roster','Lap-time board','Speed comparison','Connection status','Event information'])await page.getByRole('button',{name:'+ '+name,exact:true}).click();
 await expect(page.locator('.studio-layers>div')).toHaveCount(16);await page.getByLabel('Title',{exact:true}).fill('Synthetic event card');
 await page.getByRole('button',{name:'Color',exact:true}).click();await page.getByRole('button',{name:'Edit',exact:true}).click();await expect(page.getByLabel('Title',{exact:true})).toHaveValue('Synthetic event card');
 await page.getByRole('button',{name:'Take to program',exact:true}).click();await expect(page.locator('.studio-monitors>div').nth(1).locator('.graphic-event_info')).toContainText('Synthetic event card');
 const state=await (await page.request.get('/api/group/state')).json(),w=state.workspaces.find((w:any)=>w.group_id===state.group.id);expect(w.program.graphics).toHaveLength(16);
 expect((await page.request.post('/api/group/hosting',{data:{enabled:true,bind:'127.0.0.1',port:18594,origins:['http://127.0.0.1:18594']}})).ok()).toBeTruthy();
 await page.request.put('/api/group/configure',{data:{publication:['basic']}});
 const credential=await (await page.request.post('/api/group/workspaces/'+w.id+'/credential',{data:{}})).json();const output=await page.context().newPage();output.on('pageerror',e=>errors.push(e.message));
 const speed=w.program.graphics.find((g:any)=>g.template==='speed_comparison');await output.goto('http://127.0.0.1:18594/overlay/'+w.id+'#access='+credential.credential+'&graphic='+speed.id);
 await expect(output.locator('.graphic-speed_comparison')).toContainText('Unavailable');await expect(output.locator('.graphic-speed_comparison')).not.toContainText('km/h');
 await page.request.put('/api/group/configure',{data:{publication:['basic','telemetry']}});await expect(output.locator('.graphic-speed_comparison')).toContainText('km/h');
 await output.reload();await expect(output.locator('.graphic-speed_comparison')).toContainText('km/h');
 for(const template of ['classification_strip','team_roster','lap_board','connection_status','event_info']){const g=w.program.graphics.find((g:any)=>g.template===template);await output.goto('http://127.0.0.1:18594/overlay/'+w.id+'#access='+credential.credential+'&graphic='+g.id);await expect(output.locator('.graphic-'+template)).toBeVisible()}
 await output.setViewportSize({width:780,height:440});await output.screenshot({path:path.resolve(__dirname,'../../docs/screenshots/broadcast-event-info.png')});
 await output.close();await page.request.post('/api/group/hosting',{data:{enabled:false}});await page.request.post('/api/group/demo',{data:{action:'stop'}});expect(errors).toEqual([]);
});
