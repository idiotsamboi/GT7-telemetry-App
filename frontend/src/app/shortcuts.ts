// Data-driven shortcut registry (§9.4): scopes GLOBAL/BROADCAST/DRIVER/PAGE/CONTEXT.
// Registering a key already claimed in an overlapping scope throws in dev, so
// collisions are caught while building pages rather than discovered by a user.
export type Scope='global'|'broadcast'|'driver'|'page'|'context'
export type ShortcutDef={
 id:string
 keys:string // e.g. 'ctrl+k', 'ctrl+shift+b', 'f'
 scope:Scope
 label:string
 run():void
}

const registry=new Map<string,ShortcutDef>()

function normalize(keys:string):string{
 return keys.toLowerCase().split('+').map(k=>k.trim()).sort((a,b)=>a==='ctrl'||a==='cmd'?-1:b==='ctrl'||b==='cmd'?1:a.localeCompare(b)).join('+')
}

function overlaps(a:Scope,b:Scope):boolean{
 if(a===b)return true
 if(a==='global'||b==='global')return true
 return false
}

export function register(def:ShortcutDef):()=>void{
 const key=normalize(def.keys)
 for(const existing of registry.values()){
  if(normalize(existing.keys)===key&&overlaps(existing.scope,def.scope)&&existing.id!==def.id){
   if(import.meta.env.DEV)throw new Error(`Shortcut collision: '${def.keys}' already registered as '${existing.id}' (scope ${existing.scope}), cannot also register '${def.id}' (scope ${def.scope})`)
  }
 }
 registry.set(def.id,def)
 return ()=>registry.delete(def.id)
}

export function list():ShortcutDef[]{return [...registry.values()]}

function eventKey(e:KeyboardEvent):string{
 const parts:string[]=[]
 if(e.ctrlKey||e.metaKey)parts.push('ctrl')
 if(e.shiftKey)parts.push('shift')
 if(e.altKey)parts.push('alt')
 const k=e.key.length===1?e.key.toLowerCase():e.key.toLowerCase()
 if(!['control','shift','alt','meta'].includes(k))parts.push(k)
 return normalize(parts.join('+'))
}

let installed=false
export function installGlobalListener():()=>void{
 if(installed)return ()=>{}
 installed=true
 const handler=(e:KeyboardEvent)=>{
  const target=e.target as HTMLElement|null
  const typing=target&&(target.tagName==='INPUT'||target.tagName==='TEXTAREA'||target.isContentEditable)
  if(typing&&normalize('ctrl+k')!==eventKey(e))return
  const key=eventKey(e)
  for(const def of registry.values()){
   if(normalize(def.keys)===key){e.preventDefault();def.run();return}
  }
 }
 window.addEventListener('keydown',handler)
 installed=true
 return ()=>{window.removeEventListener('keydown',handler);installed=false}
}
