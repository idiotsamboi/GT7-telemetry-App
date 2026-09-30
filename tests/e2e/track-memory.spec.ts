import path from 'node:path';
import {test,expect} from '../../frontend/node_modules/@playwright/test';

test('reference preview, candidate confirmation and shared OBS map',async({page})=>{
 test.setTimeout(90000);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.request.post('/api/pair',{data:{}});await page.goto('/');
 const panel=page.locator('.circuit-panel');await expect(panel).toBeVisible();
 const tracks=await (await page.request.get('/api/tracks')).json(),venue=tracks.find((t:any)=>t.layouts.some((l:any)=>l.id==='10'));
 await panel.getByLabel('Circuit',{exact:true}).first().selectOption(venue.id);
 await panel.getByLabel('Layout',{exact:true}).first().selectOption('10');
 await expect(panel.getByRole('img',{name:'Approximate reference outline',exact:true})).toBeVisible();
 await panel.getByLabel('Reference outline',{exact:true}).uncheck();await expect(panel.getByRole('img',{name:'Approximate reference outline',exact:true})).toHaveCount(0);await panel.getByLabel('Reference outline',{exact:true}).check();
 const candidate=panel.locator('.map-confirmation');await expect(candidate).toBeVisible();await candidate.getByLabel('Circuit',{exact:true}).selectOption(venue.id);await candidate.getByLabel('Layout',{exact:true}).selectOption('10');await candidate.getByRole('button',{name:'Save this lap as selected layout'}).first().click();
 await expect(panel.locator('.tiny-badge')).toHaveText('Saved map');await expect(panel.getByRole('img',{name:'Position-derived circuit map and delta-colored driving line',exact:true})).toBeVisible();
 await panel.screenshot({path:path.resolve(__dirname,'../../docs/screenshots/track-memory.png')});
 await page.getByRole('button',{name:'Race Control',exact:true}).click();await page.getByLabel('League name',{exact:true}).fill('Track memory synthetic test');await page.getByRole('button',{name:'Create league',exact:true}).click();
 await page.getByLabel('Circuit',{exact:true}).selectOption(venue.id);await page.getByLabel('Layout',{exact:true}).selectOption('10');await page.getByRole('button',{name:'Create event',exact:true}).click();
 await page.getByRole('button',{name:'start',exact:true}).click();await expect(page.getByText('Shared circuit map',{exact:false})).toBeVisible();
 const state=await (await page.request.get('/api/group/state')).json();expect(state.snapshot.map_model.layout_id).toBe('10');expect(state.snapshot.map_revision).toBeTruthy();
 await page.request.post('/api/group/session/close',{data:{}});expect(errors).toEqual([]);
});
