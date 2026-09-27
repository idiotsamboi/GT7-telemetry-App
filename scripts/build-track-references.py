"""Build offline visual outlines from an explicitly downloaded, pinned source cache."""
import json,hashlib,math,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cache=ROOT/'data/reference-research'
sha=cache.joinpath('source-revision.txt').read_text().strip()
source='https://github.com/jbhoorasingh/gt7-datalogger-track-data/tree/'+sha
raw=cache.joinpath('signatures.json').read_bytes()
rows=json.loads(raw)['signatures']
cat=json.loads((ROOT/'backend/app/data/tracks.json').read_text(encoding='utf-8'))
def norm(x):return ''.join(c.lower() for c in unicodedata.normalize('NFKD',x.replace('Grand Prix Layout','GP Layout')) if c.isalnum())
lookup={}
for row in rows:
 lookup[norm(row['official_name'])]=(row,False)
 if row.get('reverse'):lookup[norm(row['reverse']['official_name'])]=(row,True)
layouts={}
for track in cat:
 for layout in track['layouts']:
  key=layout['id'];item={'layout_id':key,'name':layout['name'],'status':'unavailable','reason':'No exact layout-specific path in the pinned source','catalogue_source':'https://www.gran-turismo.com/us/gt7/tracklist/','revision':sha,'source_url':source}
  match=lookup.get(norm(layout['name']))
  if match:
   row,reverse=match;points=row.get('path') or []
   if row.get('flags'):item['reason']='Source quality flags: '+', '.join(row['flags'])
   elif len(points)<20:item['reason']='Source has no continuous outline'
   elif math.dist(points[0],points[-1])>100:item['reason']='Open/incomplete source outline'
   else:
    lo=[min(p[k] for p in points) for k in (0,1)];span=max(max(p[k] for p in points)-lo[k] for k in (0,1))
    normalized=[[round((p[k]-lo[k])/span*1000,3) for k in (0,1)] for p in points]
    if reverse:normalized.reverse()
    item.update(status='verified',reason='Exact layout identity; unflagged closed source path; visual outline review',points=normalized,approximate=True,coordinate_space='normalized reference; not world metres',source_layout_id=(row['reverse'] if reverse else row)['official_id'],attribution='jbhoorasingh GT7 track data (CC0); upstream zetetos/gt-telemetry captures (MIT)',derived_reverse=reverse,source_provenance=row['provenance'])
  layouts[key]=item
out={'schema':1,'source_revision':sha,'source_sha256':hashlib.sha256(raw).hexdigest(),'layouts':layouts}
(ROOT/'backend/app/data/track-references.json').write_text(json.dumps(out,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
verified=sum(x['status']=='verified' for x in layouts.values())
lines=['# Offline track-reference coverage','',f'{verified} verified visual outlines; {len(layouts)-verified} unavailable layouts. All {len(layouts)} existing layout IDs are unchanged.','',f'Source: [{source}]({source}). Source SHA256: `{out["source_sha256"]}`.','', 'These are approximate driving-line outlines, not track edges. Exact name matching (Grand Prix/GP alias only), source quality flags and closure checks precede visual review. Reverse twins preserve shape with reversed point order. Missing/flagged references fall back to live learning. No downloads occur while driving.','', 'Identity reference: [official GT7 track list](https://www.gran-turismo.com/us/gt7/tracklist/). Source data CC0 and upstream MIT notices are in `docs/licenses`.','', '| ID | Layout | Coverage | Reason |','|---|---|---|---|']
for key,item in layouts.items():lines.append(f'| {key} | {item["name"]} | {item["status"]} | {item["reason"]} |')
(ROOT/'docs/TRACK_REFERENCE_COVERAGE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(f'{verified}/{len(layouts)} reference outlines')
