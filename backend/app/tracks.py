"""Offline layout memory. Receiver collection is cheap; recognition and I/O run in a worker."""
import copy,hashlib,json,math,os,threading,time,uuid
from collections import deque
from pathlib import Path
from .track_geometry import Fingerprint,shape_fit,transform,length
CATALOG=json.loads((Path(__file__).parent/'data/tracks.json').read_text(encoding='utf-8'))
LAYOUTS={l['id']:{**l,'track':t['name'],'venue_id':t['id'],'logo':t['logo']} for t in CATALOG for l in t['layouts']}
try:REFERENCES=json.loads((Path(__file__).parent/'data/track-references.json').read_text(encoding='utf-8'))['layouts']
except (OSError,ValueError,KeyError):REFERENCES={}

def validate_points(points):
 if not isinstance(points,list) or not 20<=len(points)<=4096:raise ValueError('Map needs 20 to 4096 [x, z] points')
 for p in points:
  if not isinstance(p,list) or len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or abs(v)>1000000 for v in p):raise ValueError('Map coordinates must be finite world-space metres')
 return [[round(float(v),2) for v in p] for p in points]

def revision(points):return hashlib.sha256(json.dumps(points,separators=(',',':')).encode()).hexdigest()[:20]
def atomic(path,data):
 temp=path.with_suffix('.tmp')
 with temp.open('w',encoding='utf-8') as stream:
  stream.write(json.dumps(data,separators=(',',':'),allow_nan=False));stream.flush();os.fsync(stream.fileno())
 temp.replace(path)

CORPUS_MAX_BYTES=40*1024*1024

class TrackMap:
 def __init__(self,root):
  self.root=Path(root)/'track-maps';self.root.mkdir(exist_ok=True);self.lock=threading.RLock();self.io_lock=threading.RLock()
  self.corpus_path=self.root/'_corpus.jsonl';self.corpus_bytes=self.corpus_path.stat().st_size if self.corpus_path.exists() else 0;self.corpus_records=0;self.corpus_layouts=set();self.corpus_full=False
  if self.corpus_path.exists():
   try:
    with self.corpus_path.open(encoding='utf-8') as stream:
     for line in stream:
      if not line.strip():continue
      self.corpus_records+=1
      try:self.corpus_layouts.add(json.loads(line).get('layout_id'))
      except (ValueError,TypeError):pass
   except OSError:pass
  self.library={};self.fingerprints={};self.alignments={};self.queue=deque(maxlen=8);self.candidates=[];self.pending=None;self.error=None;self.generation=0;self.last_scan=-1e30;self.scan_count=0
  self.layout_id='';self.preferred='';self.saved=None;self.bound=False;self.manual=False;self.suggestions=[];self.provenance='live';self.status='Recognizing';self.reason='Drive a clean lap to recognize a saved layout.';self.reset()
  for path in self.root.glob('*.json'):
   if path.stem not in LAYOUTS or path.stat().st_size>4*1024*1024:continue
   try:
    data=json.loads(path.read_text(encoding='utf-8'));data['points']=validate_points(data['points']);data['layout_id']=path.stem;data.setdefault('revision',revision(data['points']));data.setdefault('schema',1);data.setdefault('versions',[]);data.setdefault('kind','legacy learned driving line')
    if data['schema']==1:
     data['schema']=2;data.setdefault('quality',{'source':'legacy migration','continuous':'unverified'})
     try:atomic(path,data)
     except OSError:self.error='Legacy map loaded; migration write failed. Original points retained.'
    versions=[]
    for old in data.get('versions',[]) if isinstance(data.get('versions'),list) else []:
     try:
      old['points']=validate_points(old['points']);old.setdefault('revision',revision(old['points']));old.setdefault('kind','legacy learned driving line');versions.append(old)
     except (ValueError,TypeError,KeyError):continue
    data['versions']=versions[-8:];self._cache(data)
   except (OSError,ValueError,KeyError,TypeError):continue
  try:
   path=self.root/'_candidates.json'
   if path.stat().st_size<=4*1024*1024:
    for item in json.loads(path.read_text(encoding='utf-8'))[-8:]:item['points']=validate_points(item['points']);self.candidates.append(item)
  except (OSError,ValueError,KeyError,TypeError):pass
 def _cache(self,data):
  key=data['layout_id'];self.library[key]=data;self.fingerprints[key]=Fingerprint(data['points']);self.alignments.pop(key,None)
 def reset(self):
  with self.lock:
   self.points=[];self.probe=deque(maxlen=256);self.lap=None;self.partial=True;self.bad=False;self.last=None;self.start=None;self.distance=0;self.generation+=1;self.suggestions=[]
 def leave(self):
  with self.lock:
   self.reset();self.preferred=self.layout_id or self.preferred;self.layout_id='';self.saved=None;self.bound=False;self.manual=False;self.status='Recognizing';self.reason='Circuit exited. Saved maps are retained.'
 def select(self,layout_id,force=False,manual=True):
  if layout_id and layout_id not in LAYOUTS:raise ValueError('Unknown GT7 layout')
  with self.lock:
   if layout_id==self.layout_id and not force and self.manual==manual:return
   self.reset();self.preferred=layout_id;self.layout_id=layout_id if manual else '';self.bound=bool(layout_id) and manual;self.manual=self.bound;self.saved=self.library.get(self.layout_id)
   self.status='Saved map' if self.saved else 'Reference outline' if self.reference(self.layout_id) else 'Learning' if self.bound else 'Recognizing';self.reason='Manual layout selection.' if self.bound else 'Previous selection is a hint; the driven route must match before automatic saving.'
 def reference(self,layout_id):
  item=REFERENCES.get(layout_id,{})
  return item if item.get('status')=='verified' and item.get('points') else None
 def consume(self,s):
  with self.lock:
   v=s.values;flags=v.get('flags',0);pos=v.get('position');lap=v.get('lap')
   if not flags&1:
    if self.last is not None or self.points or self.bound:self.leave()
    return
   if s.provenance!=self.provenance:self.leave();self.provenance=s.provenance
   if flags&6:self.bad=True;self.last=s.mono;return
   if not pos or len(pos)!=3 or any(x is None or not math.isfinite(x) for x in pos):self.bad=True;return
   p=[pos[0],pos[2]]
   if self.last is not None and (s.mono-self.last>.5 or s.mono<=self.last):self.bad=True;self.probe.clear()
   if s.quality:self.bad=True
   self.last=s.mono
   if self.lap is None:self.lap=lap;self.start=s.mono
   elif lap!=self.lap:
    complete=(isinstance(lap,int) and isinstance(self.lap,int) and lap==self.lap+1 and not self.partial and not self.bad and len(self.points)>=20 and self.distance>=100 and s.mono-self.start>=10 and math.dist(self.points[0],p)<75)
    if complete:
     points=validate_points(self.points+[p] if len(self.points)<4096 else self.points)
     candidate={'id':uuid.uuid4().hex,'points':points,'created':time.time(),'kind':'learned driving line','provenance':s.provenance,'layout_id':self.layout_id if self.bound else '', 'generation':self.generation,'quality':{'continuous':True,'length_m':round(length(points),1),'source':'completed telemetry lap'}}
     if s.provenance=='live':
      if len(self.queue)==self.queue.maxlen:self.error='Map processing backlog: oldest unsaved lap replaced.'
      self.queue.append(candidate);self.pending=candidate
     else:self.saved={'points':points,'kind':s.provenance+' driving line','provenance':s.provenance,'revision':revision(points)}
    if not isinstance(lap,int) or not isinstance(self.lap,int) or lap!=self.lap+1:self.probe.clear();self.bound=False;self.manual=False
    self.points=[];self.distance=0;self.partial=not isinstance(lap,int) or not isinstance(self.lap,int) or lap!=self.lap+1;self.bad=False;self.lap=lap;self.start=s.mono
   if self.probe and math.dist(self.probe[-1],p)>200:
    self.leave();self.last=s.mono;self.lap=lap;self.start=s.mono;self.bad=True;self.reason='Position discontinuity; re-establish the circuit before saving.'
   if not self.probe or math.dist(self.probe[-1],p)>=10:self.probe.append(p)
   if self.points:
    distance=math.dist(self.points[-1],p)
    if distance<10:return
    if distance>200:self.bad=True
    self.distance+=distance
   if len(self.points)>=4096:self.bad=True;return
   self.points.append([round(p[0],2),round(p[1],2)])
   if self.bound and not self.saved and len(self.points)>1:self.status='Learning'
 def _matches(self,points,complete=False):
  result=[]
  for key,fp in list(self.fingerprints.items()):
   match=fp.match(points,complete)
   if match:result.append({'layout_id':key,'name':LAYOUTS[key]['name'],'source':'saved telemetry','evidence':match})
  return sorted(result,key=lambda r:r['evidence']['mean_error_m'])
 def _distinct(self,matches):
  if len(matches)!=1:return False
  key=matches[0]['layout_id'];layout=LAYOUTS[key]
  # Same-length variants may differ only by pit lane or start/finish convention.
  return not any(other!=key and v['venue_id']==layout['venue_id'] and v['direction']==layout['direction'] and abs(v['length_m']-layout['length_m'])/max(layout['length_m'],1)<.01 for other,v in LAYOUTS.items())
 def _write(self,key,points,kind='learned driving line',quality=None,restored_from=None):
  with self.io_lock:
   previous=self.library.get(key);history=copy.deepcopy(previous.get('versions',[])) if previous else []
   if previous and previous['points']!=points:
    history=[v for v in history if v.get('revision') not in (revision(points),previous['revision'])]
    history.append({k:v for k,v in previous.items() if k!='versions'})
   data={'schema':2,'layout_id':key,'revision':revision(points),'kind':kind,'provenance':'live','points':points,'updated':time.time(),'quality':quality or {},'versions':history[-8:]}
   if restored_from:data['restored_from']=restored_from
   atomic(self.root/(key+'.json'),data)
   fp=Fingerprint(points)
   with self.lock:
    self.library[key]=data;self.fingerprints[key]=fp;self.alignments.pop(key,None)
    if self.layout_id==key:self.saved=data;self.status='Saved map'
   return data
 def _log_corpus(self,layout_id,points,quality,source):
  """Append-only training corpus: every recognized/confirmed clean lap ever
  seen, kept alongside (not instead of) the current-best map per layout so
  the recognition system accumulates more matched geometry over time. Bounded
  total size; stops appending rather than growing without limit."""
  with self.io_lock:
   if self.corpus_bytes>=CORPUS_MAX_BYTES:
    self.corpus_full=True;return
   record=json.dumps({'ts':time.time(),'layout_id':layout_id,'source':source,'points':points,'quality':quality or {}},separators=(',',':'),allow_nan=False)+'\n'
   try:
    with self.corpus_path.open('a',encoding='utf-8') as stream:stream.write(record)
    self.corpus_bytes+=len(record.encode('utf-8'));self.corpus_records+=1;self.corpus_layouts.add(layout_id)
   except OSError as error:self.error='Training corpus not written: '+str(error)[:160]
 def _retain(self,candidate,suggestions):
  with self.io_lock:
   item={**candidate,'suggestions':suggestions};items=[x for x in self.candidates if x['id']!=item['id']]+[item];items=items[-8:]
   atomic(self.root/'_candidates.json',items)
   with self.lock:self.candidates=items
 def _reference_matches(self,points):
  result=[];metres=length(points)
  for key,item in REFERENCES.items():
   if not self.reference(key) or abs(LAYOUTS[key]['length_m']-metres)/max(metres,1)>.12:continue
   fits=[shape_fit(item['points'],points),shape_fit(list(reversed(item['points'])),points)];fit=min((x for x in fits if x),key=lambda x:x['error_m'],default=None)
   if fit and fit['relative_error']<.02:result.append({'layout_id':key,'name':LAYOUTS[key]['name'],'source':'approximate reference shape','evidence':{'relative_error':round(fit['relative_error'],4),'requires_confirmation':True}})
  return sorted(result,key=lambda x:x['evidence']['relative_error'])[:6]
 def maintenance(self,now=None):
  now=time.monotonic() if now is None else now
  with self.lock:
   if now-self.last_scan<.5:return
   self.last_scan=now;self.scan_count+=1;generation=self.generation;probe=list(self.probe);candidate=self.queue[0] if self.queue else None;live=self.provenance=='live';bound=self.bound
  if candidate:
   try:
    key=candidate['layout_id'];matches=self._matches(candidate['points'],True);same_generation=candidate['generation']==generation
    if key and key in self.library and not self.fingerprints[key].match(candidate['points'],True):key=''
    if not key and self._distinct(matches):key=matches[0]['layout_id']
    if key:
     saved=self._write(key,candidate['points'],quality=candidate['quality'])
     self._log_corpus(key,candidate['points'],candidate['quality'],'automatic match')
     with self.lock:
      if self.generation==candidate['generation'] and live:self.layout_id=key;self.bound=True;self.saved=saved;self.status='Saved map';self.reason='Clean lap matched a unique saved layout.' if not candidate['layout_id'] else 'Clean lap saved under the selected layout.'
    else:
     suggestions=matches or self._reference_matches(candidate['points']);self._retain(candidate,suggestions)
     with self.lock:
      if self.generation==candidate['generation'] and self.provenance=='live':self.status='Needs confirmation';self.suggestions=suggestions;self.reason='Clean lap retained. Confirm its exact layout before naming this map.'
    with self.lock:
     if self.queue and self.queue[0]['id']==candidate['id']:self.queue.popleft()
     self.pending=self.queue[-1] if self.queue else None;self.error=None
   except (OSError,ValueError) as error:self.error='Map not saved: '+str(error)[:180]
  elif live and not bound and len(probe)>=12:
   matches=self._matches(probe)
   with self.lock:
    if self.generation==generation and not self.bound:
     self.suggestions=matches[:6]
     if self.status!='Needs confirmation':self.status='Recognizing';self.reason='Candidate routes found; a complete clean lap is required to distinguish shared sections.' if matches else 'Learning an unfamiliar route. Finish a continuous lap.'
 def flush(self):
  # Shutdown and explicit tests flush queued work; background loop is rate limited.
  for _ in range(8):
   with self.lock:
    if not self.queue:break
    self.last_scan=-1e30
   self.maintenance()
   if self.error:break
 def confirm(self,candidate_id,layout_id):
  if layout_id not in LAYOUTS:raise ValueError('Select a known GT7 layout')
  with self.lock:item=next((copy.deepcopy(x) for x in self.candidates if x['id']==candidate_id),None)
  if not item or item.get('provenance')!='live':raise ValueError('Live candidate not found')
  data=self._write(layout_id,item['points'],quality={**item['quality'],'identity':'user confirmed'})
  self._log_corpus(layout_id,item['points'],item['quality'],'user confirmed')
  with self.lock:self.reset();self.layout_id=layout_id;self.preferred=layout_id;self.bound=True;self.manual=True;self.saved=data;self.status='Saved map';self.reason='Layout confirmed and saved.';self.suggestions=[];self.generation+=1
  with self.io_lock:
   items=[x for x in self.candidates if x['id']!=candidate_id];atomic(self.root/'_candidates.json',items)
   with self.lock:self.candidates=items
  return self.snapshot()
 def restore(self,layout_id,revision_id):
  data=self.library.get(layout_id)
  if not data:raise ValueError('Saved layout not found')
  old=next((v for v in data.get('versions',[]) if v.get('revision')==revision_id),None)
  if not old:raise ValueError('Revision not found')
  self._write(layout_id,validate_points(old['points']),kind=old['kind'],quality=old.get('quality'),restored_from=revision_id);return self.snapshot()
 def import_map(self,layout_id,points):
  if layout_id not in LAYOUTS:raise ValueError('Select a known GT7 layout first')
  self._write(layout_id,validate_points(points),'imported world-space driving line',{'identity':'user imported'})
 def alignment(self,key):
  if key in self.alignments:return self.alignments[key]
  data=self.library.get(key);reference=self.reference(key);result={'status':'unavailable','points':[]}
  if data and reference:
   fits=[shape_fit(reference['points'],data['points'])];fit=min((x for x in fits if x),key=lambda x:x['error_m'],default=None)
   if fit and fit['error_m']<=25 and fit['relative_error']<=.008:result={'status':'validated similarity fit','points':transform(reference['points'],fit),'fit':fit,'revision':data['revision']}
   else:result={'status':'unverified; displayed separately','points':[]}
  
  with self.lock:
   if self.library.get(key) is data:self.alignments[key]=result
  return result
 def map_for(self,key):
  data=self.library.get(key)
  return {'schema':2,'layout_id':key,'points':data['points'] if data else [],'revision':data.get('revision') if data else None,'reference':self.reference(key),'alignment':copy.deepcopy(self.alignments.get(key,{'status':'unavailable','points':[]})),'kind':data.get('kind') if data else 'reference outline','complete':bool(data and self.fingerprints[key].closed)}
 def snapshot(self):
  with self.lock:
   data=self.saved;reference=self.reference(self.layout_id);versions=(self.library.get(self.layout_id) or {}).get('versions',[])
   return {'schema':2,'layout_id':self.layout_id,'preferred_layout_id':self.preferred,'selection':LAYOUTS.get(self.layout_id),'kind':data['kind'] if data else 'learning current lap','points':list(data['points'] if data else self.points),'complete':bool(data),'recording_points':len(self.points),'status':self.status,'reason':self.reason,'recognition':{'mode':'automatic with fallback','bound':self.bound,'manual':self.manual,'candidates':copy.deepcopy(self.suggestions),'requires_complete_lap':True},'revision':data.get('revision') if data else None,'versions':[{'revision':v['revision'],'updated':v.get('updated'),'kind':v['kind']} for v in versions],'reference':reference,'alignment':copy.deepcopy(self.alignments.get(self.layout_id,{'status':'unavailable','points':[]})) if self.provenance=='live' else {'status':'unavailable for demo/replay','points':[]},'reference_coverage':REFERENCES.get(self.layout_id,{}).get('status','unavailable'),'unnamed_candidates':[{k:v for k,v in c.items() if k not in ('points','generation')} for c in reversed(self.candidates)],'save_pending':bool(self.queue),'save_error':self.error,'provenance':self.provenance,'corpus':{'records':self.corpus_records,'layouts':len(self.corpus_layouts),'bytes':self.corpus_bytes,'full':self.corpus_full}}
