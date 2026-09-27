"""Import attributed circuit metadata, logos and official transparent car thumbnails."""
import csv,json,urllib.request,concurrent.futures,hashlib,html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REV='b05de685c63c6df2eb86887c8929883e66f93956'
def fetch(url):
 return urllib.request.urlopen(url,timeout=30).read()
def main():
 base=f'https://raw.githubusercontent.com/ddm999/gt7info/{REV}/'
 venues=list(csv.DictReader(fetch(base+'_data/db/crsbase.csv').decode().splitlines()))
 courses=list(csv.DictReader(fetch(base+'_data/db/course.csv').decode().splitlines()))
 tracks=[];provenance={'catalogue':base+'_data/db/course.csv','revision':REV,'assets':{}}
 folder=ROOT/'frontend/public/tracks';folder.mkdir(parents=True,exist_ok=True)
 for venue in venues:
  name=venue['Name'];key=venue['ID'];logo=folder/(key+'.png');url=base+'img/track/'+venue['LogoName']+'.png'
  try:
   logo.write_bytes(fetch(url));kind='source logo'
  except urllib.error.HTTPError as e:
   if e.code!=404:raise
   logo=folder/(key+'.svg');label=html.escape(name)
   logo.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 100"><path fill="#ff354b" d="M0 10h9v80H0z M20 10h50L20 60z"/><text x="85" y="52" fill="white" font-family="sans-serif" font-size="19" font-weight="bold" textLength="255" lengthAdjust="spacingAndGlyphs">{label}</text><text x="85" y="77" fill="#aaa" font-family="sans-serif" font-size="10">CIRCUIT / {key}</text></svg>');kind='original typographic badge';url=None
  layouts=[{'id':c['ID'],'name':c['Name'],'direction':'reverse' if c['IsReverse']=='1' else 'forward','length_m':float(c['Length'])} for c in courses if c['Base']==key]
  tracks.append({'id':key,'name':name,'logo':'/tracks/'+logo.name,'logo_kind':kind,'layouts':layouts})
  provenance['assets']['/tracks/'+logo.name]={'source':url,'kind':kind,'sha256':hashlib.sha256(logo.read_bytes()).hexdigest()}
 (ROOT/'backend/app/data/tracks.json').write_text(json.dumps(tracks,indent=2))
 cars=json.loads((ROOT/'backend/app/data/cars.json').read_text());out=ROOT/'frontend/public/cars';out.mkdir(exist_ok=True)
 def car(key):
  url=f'https://www.gran-turismo.com/common/dist/gt7/carlist/car_thumbnails/car{key}.png';path=out/(key+'.png')
  try:
   if not path.exists():path.write_bytes(fetch(url))
   if not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Not PNG')
   return key,{'source':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
  except Exception as e:return key,{'unavailable':str(e)}
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for key,result in pool.map(car,cars):
   if 'source' in result:provenance['assets']['/cars/'+key+'.png']=result
 (ROOT/'frontend/src/carImages.json').write_text(json.dumps(sorted(int(p.stem) for p in out.glob('*.png'))))
 provenance['missing_car_ids']=[key for key in cars if '/cars/'+key+'.png' not in provenance['assets']]
 provenance['car_artwork']='Sony Interactive Entertainment / Polyphony Digital and vehicle rights holders; identification artwork, no affiliation. Not covered by the catalogue MIT-0 license.'
 (ROOT/'docs/track-car-assets-provenance.json').write_text(json.dumps(provenance,indent=2))
 print(f'{len(tracks)} venues, {sum(len(t["layouts"]) for t in tracks)} layouts; {len(list(out.glob("*.png")))} car thumbnails',flush=True)
if __name__=='__main__':main()
