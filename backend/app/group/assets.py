"""Isolated raster decoding. Originals are private; only normalized variants are served."""
import io,multiprocessing,hashlib,time
from pathlib import Path
from .repository import uid
from .service import fail
MAX_UPLOAD=5*1024*1024

from .asset_worker import decode_worker

class Assets:
 def __init__(self,service):self.service=service;self.root=service.runtime.config.root/'league-assets';self.root.mkdir(exist_ok=True)
 def upload(self,league,raw):
  if league not in self.service.leagues:fail(404,'League not found')
  if not raw or len(raw)>MAX_UPLOAD:fail(413,'Image exceeds 5 MiB')
  context=multiprocessing.get_context('spawn');receive,send=context.Pipe(duplex=False);process=context.Process(target=decode_worker,args=(raw,send),daemon=True);process.start();send.close()
  try:
   if not receive.poll(5):fail(422,'Image processing exceeded five seconds')
   result=receive.recv()
  finally:
   receive.close();process.join(.2)
   if process.is_alive():process.terminate();process.join(2)
  if result.get('error'):fail(422,result['error'])
  size=len(raw)+sum(len(v) for v in result['variants'].values());existing=self.service.repo.docs('asset')
  if size+sum(a['bytes'] for a in existing if a['league_id']==league)>50*1024*1024 or size+sum(a['bytes'] for a in existing)>1024*1024*1024:fail(413,'Branding storage quota reached')
  id=uid();folder=self.root/id;folder.mkdir();(folder/'original.bin').write_bytes(raw)
  for key,value in result['variants'].items():(folder/(key+'.png')).write_bytes(value)
  asset={'id':id,'league_id':league,'bytes':size,'width':result['width'],'height':result['height'],'sha256':hashlib.sha256(result['variants']['1024']).hexdigest(),'created':time.time()}
  self.service.repo.commit([('asset',id,league,asset)]);return asset
 def path(self,id,size='1024'):
  if size not in ('512','1024','2048'):fail(404,'Variant not found')
  if not self.service.repo.get('asset',id):fail(404,'Asset not found')
  path=self.root/id/(size+'.png')
  if not path.is_file():fail(404,'Asset not found')
  return path
