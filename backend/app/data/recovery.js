const status=document.getElementById('status');
async function post(path,body){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await r.json();if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail));return result;}
async function pair(){try{await post('pair',{token:document.getElementById('token').value});status.textContent='Connected. Choose a recovery action.'}catch(e){status.textContent=e.message}}
document.getElementById('pair').onclick=pair;
for(const button of document.querySelectorAll('[data-action]'))button.onclick=async()=>{button.disabled=true;try{const result=await post('recovery',{action:button.dataset.action});status.textContent=result.message}catch(e){status.textContent=e.message}finally{button.disabled=false}};
pair();
