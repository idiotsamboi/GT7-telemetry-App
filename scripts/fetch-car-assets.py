"""Build the offline car catalogue and manufacturer-image cache from pinned sources."""
import csv,io,json,re,urllib.request,concurrent.futures
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def fetch(url):return urllib.request.urlopen(url,timeout=30).read()
def commit(repo,branch):return json.loads(fetch(f'https://api.github.com/repos/{repo}/commits/{branch}'))['sha']
dbsha=commit('ddm999/gt7info','web-new');logosha=commit('filippofilip95/car-logos-dataset','master')
db=f'https://raw.githubusercontent.com/ddm999/gt7info/{dbsha}/'
logo=f'https://raw.githubusercontent.com/filippofilip95/car-logos-dataset/{logosha}/'
makers={r['ID']:r['Name'] for r in csv.DictReader(io.StringIO(fetch(db+'_data/db/maker.csv').decode()))}
cars=list(csv.DictReader(io.StringIO(fetch(db+'_data/db/cars.csv').decode())))
logos=json.loads(fetch(logo+'logos/data.json'))
def norm(x):return re.sub('[^a-z0-9]','',x.lower())
lookup={norm(x['name']):x for x in logos}
aliases={'DMC':'DeLorean','AMG':'Mercedes-Benz','Renault Sport':'Renault','DS AUTOMOBILES':'DS','Super Formula (Dallara)':'Dallara'}
dest=ROOT/'frontend/public/brands';dest.mkdir(parents=True,exist_ok=True)
def download(item):
    mid,name=item;entry=lookup.get(norm(aliases.get(name,name)))
    if not entry:return mid,None
    url=logo+'logos/thumb/'+entry['slug']+'.png'
    try:
        data=fetch(url)
        if not data.startswith(b'\x89PNG') or len(data)>2_000_000:return mid,None
        (dest/(mid+'.png')).write_bytes(data);return mid,{'path':'/brands/'+mid+'.png','source':url,'original_source':entry['image']['source']}
    except Exception:return mid,None
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:images=dict(pool.map(download,makers.items()))
catalog={r['ID']:{'name':r['ShortName'],'manufacturer':makers.get(r['Maker'],'Unknown'),'logo':(images.get(r['Maker']) or {}).get('path')} for r in cars}
target=ROOT/'backend/app/data';target.mkdir(exist_ok=True)
(target/'cars.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'docs/car-assets-provenance.json').write_text(json.dumps({'database_commit':dbsha,'logos_commit':logosha,'images':images},indent=2))
(ROOT/'docs/licenses/car-database-MIT-0.txt').write_bytes(fetch(db+'LICENSE'))
(ROOT/'docs/licenses/car-logos-README.md').write_bytes(fetch(logo+'README.md'))
print(f'{len(catalog)} cars; {sum(bool(x) for x in images.values())} manufacturer images; unknown images remain unavailable.')
