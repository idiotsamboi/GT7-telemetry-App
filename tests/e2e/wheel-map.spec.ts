import {test,expect} from '../../frontend/node_modules/@playwright/test';

test('circuit map is visible on Live Race and the Wheel pager includes a MAP page',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.request.post('/api/pair',{data:{}});await page.request.post('/api/control',{data:{action:'demo'}});
 await page.goto('/');
 await expect(page.locator('.circuit-panel')).toBeVisible();
 await expect(page.locator('.circuit-panel .circuit-map')).toBeVisible();
 await page.getByRole('button',{name:'Wheel',exact:true}).click();
 await expect(page.locator('.wd-shell')).toBeVisible();
 const pager=page.locator('.wd-pager');
 await expect(pager.getByRole('button',{name:'MAP',exact:true})).toBeVisible();
 await pager.getByRole('button',{name:'MAP',exact:true}).click();
 await expect(page.locator('.wd-map-full')).toBeVisible();
 expect(errors).toEqual([]);
});
