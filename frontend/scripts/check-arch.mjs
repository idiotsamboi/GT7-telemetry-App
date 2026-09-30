// Architecture guard (npm run check:arch):
//  (a) src/domain/** must not import .tsx modules / React components (hooks from 'react' are fine).
//  (b) fetch() may only be called from src/domain/http.ts (plus ALLOWLIST, which must stay empty).
import {readdirSync,readFileSync,existsSync,statSync} from 'node:fs'
import {join,resolve,dirname,relative,sep} from 'node:path'
import {fileURLToPath} from 'node:url'

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..')
const src=join(root,'src')
const HTTP_FILE='domain/http.ts'
// Files (relative to src, forward slashes) allowed to call fetch() besides domain/http.ts.
const ALLOWLIST=[]

const walk=dir=>readdirSync(dir).flatMap(name=>{
 const p=join(dir,name)
 return statSync(p).isDirectory()?walk(p):[p]
})
const rel=p=>relative(src,p).split(sep).join('/')
const stripComments=text=>text.replace(/\/\*[\s\S]*?\*\//g,'').replace(/(^|[^:'"`\\])\/\/.*$/gm,'$1')

const files=walk(src).filter(f=>/\.(ts|tsx)$/.test(f))
const problems=[]

const importRe=/(?:import|export)\s+(?:type\s+)?(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)/g
function resolveTarget(fromFile,spec){
 const base=resolve(dirname(fromFile),spec)
 for(const cand of [base,base+'.ts',base+'.tsx',join(base,'index.ts'),join(base,'index.tsx')])
  if(existsSync(cand)&&statSync(cand).isFile())return cand
 return null
}

for(const file of files){
 const r=rel(file)
 const text=stripComments(readFileSync(file,'utf8'))
 if(r.startsWith('domain/')){
  for(const m of text.matchAll(importRe)){
   const spec=m[1]??m[2]
   if(!spec||!spec.startsWith('.'))continue
   const target=resolveTarget(file,spec)
   const targetRel=target?rel(target):spec
   if(spec.endsWith('.tsx')||(target&&target.endsWith('.tsx'))||targetRel.startsWith('ui/')&&!targetRel.endsWith('.ts')&&!targetRel.endsWith('.css'))
    problems.push(`${r}: domain must not import a React component (${spec})`)
  }
 }
 if(r!==HTTP_FILE&&!ALLOWLIST.includes(r)&&/(?<![.\w$])fetch\s*\(/.test(text))
  problems.push(`${r}: fetch() is only allowed in src/${HTTP_FILE}`)
}

if(ALLOWLIST.length)console.warn('check:arch - fetch ALLOWLIST is not empty:',ALLOWLIST.join(', '))
if(problems.length){
 console.error('Architecture check failed:\n'+problems.map(p=>' - '+p).join('\n'))
 process.exit(1)
}
console.log(`Architecture check passed (${files.length} files).`)
