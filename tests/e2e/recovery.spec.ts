import {test,expect} from '../../frontend/node_modules/@playwright/test';
test('independent recovery works with a missing dashboard bundle',async({page})=>{
 await page.request.post('/api/pair',{data:{}});
 const settings=await (await page.request.get('/api/settings')).json();await page.request.put('/api/settings',{data:{...settings,minimal:true,hands_free:false}});await page.request.post('/api/control',{data:{action:'demo'}});
 await page.route('**/assets/*.js',route=>route.abort());await page.goto('/');await page.getByRole('link',{name:'Open recovery if the dashboard does not load'}).click();
 await expect(page.getByRole('heading',{name:'GT7 recovery',exact:true})).toBeVisible();await expect(page.getByRole('status')).toContainText('Connected');
 await page.getByRole('button',{name:'Restore full dashboard',exact:true}).click();await expect(page.getByRole('status')).toContainText('Recovery applied');
 await page.getByRole('button',{name:'Return to PS5 / leave host-only mode',exact:true}).click();await expect.poll(async()=>(await (await page.request.get('/api/state')).json()).source).toBe('live');
 expect((await (await page.request.get('/api/settings')).json()).minimal).toBe(false);
 await page.unroute('**/assets/*.js');await page.getByRole('link',{name:'Open dashboard',exact:true}).click();await expect(page.getByRole('button',{name:'Settings',exact:true})).toBeVisible();
});

test('render errors have a working recovery exit',async({page})=>{
 await page.request.post('/api/pair',{data:{}});await page.route('**/api/audio',route=>route.fulfill({json:{devices:'malformed data'}}));await page.goto('/');await page.getByRole('button',{name:'Settings',exact:true}).click();await expect(page.getByRole('heading',{name:'Dashboard could not render'})).toBeVisible();await page.getByRole('link',{name:'Open recovery',exact:true}).click();await expect(page.getByRole('heading',{name:'GT7 recovery',exact:true})).toBeVisible();
});
