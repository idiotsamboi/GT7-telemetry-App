import path from 'node:path';
import {test,expect} from '../../frontend/node_modules/@playwright/test';
test('live demo, engineer, settings, report and mobile layout',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.request.post('/api/pair',{data:{}});await page.request.post('/api/control',{data:{action:'live'}});
 await page.setViewportSize({width:1440,height:1050});await page.goto('/');
 await expect(page.getByRole('heading',{name:'Live Race',exact:true})).toBeVisible();
 if(await page.getByRole('button',{name:'Use PS5',exact:true}).isVisible()) await page.getByRole('button',{name:'Use PS5',exact:true}).click();
 await page.getByRole('button',{name:'Try demo',exact:true}).click();
 await expect(page.getByText('SYNTHETIC DEMO',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'End session',exact:true})).toBeEnabled();
 await page.waitForTimeout(1200);
 await expect(page.locator('.throttle').first()).toHaveCSS('background-color','rgb(37, 229, 139)');
 await expect(page.locator('.brake').first()).toHaveCSS('background-color','rgb(255, 53, 75)');
 await expect(page.locator('.clutch').first()).toHaveCSS('background-color','rgb(158, 219, 255)');
 await expect(page.locator('.brand-mark')).toHaveCSS('background-color','rgb(237, 27, 53)');
 await expect(page.locator('.flag-indicator')).toContainText('N/A');
 await page.screenshot({path:path.resolve(__dirname,'../../docs/screenshots/live-desktop.png'),fullPage:true});
 await page.getByRole('button',{name:'Engineer',exact:true}).click();
 await page.getByRole('textbox',{name:'Engineer command'}).fill('radio check');
 await page.getByRole('button',{name:'Send',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('Radio check');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.getByLabel('Fuel reserve',{exact:false}).count();
 await page.getByLabel('Track name',{exact:true}).fill('Demo circuit');
 await page.getByRole('button',{name:'Save settings',exact:true}).click();
 await expect(page.getByText('Console/UDP changes reconnect immediately. HTTP listen/origin changes need restart; audio device changes need microphone reinitialization.')).toBeVisible();
 await page.getByRole('button',{name:'Live Race',exact:true}).click();
 await page.setViewportSize({width:360,height:800});
 await page.screenshot({path:path.resolve(__dirname,'../../docs/screenshots/live-phone.png'),fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.getByRole('button',{name:'End session',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Analysis',exact:true})).toBeVisible();
 await page.setViewportSize({width:1440,height:1050});
 await page.screenshot({path:path.resolve(__dirname,'../../docs/screenshots/analysis-desktop.png'),fullPage:true});
 await page.getByRole('button',{name:'Sessions',exact:true}).click();
 await expect(page.getByRole('button',{name:'View analysis'}).first()).toBeVisible();
 expect(errors).toEqual([]);
});

test('live analysis and nonintrusive receiver test',async({page})=>{
 await page.request.post('/api/pair',{data:{}});await page.request.post('/api/control',{data:{action:'demo'}});
 await page.goto('/');
 await expect(page.getByRole('button',{name:'Use PS5',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Telemetry',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Real-time analysis',exact:true})).toBeVisible();
 await expect(page.getByText('Longitudinal acceleration',{exact:false})).toBeVisible();
 await page.getByRole('button',{name:'Use PS5',exact:true}).click();
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.getByRole('button',{name:'Test telemetry - 15 seconds',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('running');
 await expect(page.getByRole('button',{name:'Test telemetry - 15 seconds',exact:true})).toBeDisabled();
 await expect(page.getByRole('status')).toContainText('no_data',{timeout:20000});
});

test('offline car-brand panel follows telemetry identity',async({page})=>{
 await page.setViewportSize({width:1440,height:1050});
 await page.request.post('/api/pair',{data:{}});await page.request.post('/api/control',{data:{action:'demo'}});
 await page.routeWebSocket('**/ws',ws=>{const server=ws.connectToServer();server.onMessage(message=>{const data=JSON.parse(String(message));data.car={name:"Supra RZ '97",manufacturer:'Toyota',logo:'/brands/43.png'};data.source='demo';ws.send(JSON.stringify(data))})});
 await page.goto('/');
 await expect(page.getByRole('img',{name:'Toyota logo'})).toBeVisible();
 await expect(page.getByLabel('Current car manufacturer')).toContainText("Supra RZ '97");
 await expect(page.getByRole('img',{name:'Toyota logo'})).toHaveJSProperty('complete',true);
 expect(await page.getByRole('img',{name:'Toyota logo'}).evaluate((img:HTMLImageElement)=>img.naturalWidth)).toBeGreaterThan(0);
 await page.screenshot({path:path.resolve(__dirname,'../../docs/screenshots/broadcast-desktop.png'),fullPage:true});
});

test('one hundred engineer requests and speaker controls',async({page})=>{
 await page.request.post('/api/pair',{data:{}});await page.request.post('/api/control',{data:{action:'demo'}});
 await page.goto('/');await page.getByRole('button',{name:'Engineer',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Engineer request library · 100'})).toBeVisible();
 await page.getByLabel('Search engineer requests').fill('what is my speed');
 await expect(page.locator('.request-grid article')).toHaveCount(1);
 await page.locator('.request-grid button').click();await expect(page.getByRole('status')).toContainText('kilometres per hour');
 await page.getByText('Three answer variations',{exact:true}).click();await expect(page.locator('.request-grid li')).toHaveCount(3);
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await expect(page.getByRole('combobox',{name:'Speaker output',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Enable and test speaker',exact:true})).toBeVisible();
});

test('all screens, assets, optional settings and hands-free controls',async({page})=>{
 const errors:string[]=[];const missing:string[]=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(r.status()>=400)missing.push(`${r.status()} ${r.url()}`)});
 await page.request.post('/api/pair',{data:{}});
 await page.request.post('/api/control',{data:{action:'demo'}});
 await page.goto('/');
 for(const name of ['Live Race','Telemetry','Analysis','Strategy','Engineer','Sessions','Settings']){
   await page.getByRole('button',{name,exact:true}).click();
   await expect(page.getByRole('heading',{name,exact:true})).toBeVisible();
 }
 await page.getByLabel('Track name',{exact:true}).fill('');
 await page.getByLabel('Optional Piper .onnx model',{exact:true}).fill('');
 await page.getByLabel('Heartbeat interval · seconds',{exact:true}).fill('0.25');
 await page.getByRole('button',{name:'Save settings',exact:true}).click();
 await expect(page.getByRole('alert')).toHaveCount(0);
 const settings=await (await page.request.get('/api/settings')).json();
 expect(settings.track).toBe('');expect(settings.piper_model).toBe('');expect(settings.heartbeat).toBe(.25);
 await page.getByRole('button',{name:'Engineer',exact:true}).click();
 await page.getByRole('button',{name:'Enable hands-free',exact:true}).click();
 await expect(page.getByRole('button',{name:'Pause listening',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Hold to talk',exact:true})).toBeHidden();
 await page.getByRole('button',{name:'Pause listening',exact:true}).click();
 await expect(page.getByRole('button',{name:'Hold to talk',exact:true})).toBeVisible();
 expect(errors).toEqual([]);expect(missing).toEqual([]);
});

test('circuit selection, imported map and transparent car panel',async({page})=>{
 await page.request.post('/api/pair',{data:{}});
 await page.request.post('/api/control',{data:{action:'demo'}});
 await page.routeWebSocket('**/ws',ws=>{const server=ws.connectToServer();server.onMessage(message=>{const data=JSON.parse(String(message));data.car={name:"180SX Type X '96",manufacturer:'Nissan',logo:'/brands/28.png'};if(data.sample)data.sample.values.car_id=24;ws.send(JSON.stringify(data))})});
 await page.goto('/');
 await page.getByLabel('Circuit',{exact:true}).selectOption('29');
 await expect(page.getByLabel('Layout',{exact:true})).toHaveValue('10');
 const points=Array.from({length:100},(_,i)=>[200*Math.cos(i/99*Math.PI*2),200*Math.sin(i/99*Math.PI*2)]);
 await page.getByLabel('Import map JSON').setInputFiles({name:'suzuka.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({layout_id:'10',points}))});
 await expect(page.getByText('SAVED MAP',{exact:true})).toBeVisible();
 await expect(page.getByRole('img',{name:"180SX Type X '96",exact:true})).toHaveJSProperty('complete',true);
 expect(await page.locator('.current-car-image').evaluate((img:HTMLImageElement)=>img.naturalWidth)).toBeGreaterThan(0);
 await expect(page.locator('.circuit-logo')).toHaveJSProperty('complete',true);
 await page.getByLabel('Circuit',{exact:true}).selectOption('');
 await expect(page.getByLabel('Layout',{exact:true})).toBeDisabled();
 await page.waitForTimeout(2200);
 await page.setViewportSize({width:1440,height:1050});
 await page.screenshot({path:path.resolve(__dirname,'../../docs/screenshots/race-viewer.png'),fullPage:true});
 await page.setViewportSize({width:360,height:800});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.getByLabel('Circuit',{exact:true}).selectOption('');
 await expect(page.getByLabel('Layout',{exact:true})).toBeDisabled();
});
