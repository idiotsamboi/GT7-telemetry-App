"""Safe, bounded exports. Bundles contain JSONL + metadata + a checksum manifest."""
import csv,io,json,zipfile,hashlib,html,tempfile,math,struct
from .telemetry import FIELDS
from datetime import datetime
from pathlib import Path

def safe_cell(value):
    if isinstance(value,str) and value[:1] in '=+-@\t\r':return "'"+value
    return value

def report_html(detail):
    report=detail.get('report') or {};laps=detail.get('laps',[])
    rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(l.get(k,"N/A")))}</td>' for k in ('number','duration_ms','timing_source','complete','fuel_used_l','coast_s'))+'</tr>' for l in laps)
    speeds=[l.get('max_speed_kmh',0) for l in laps];points=' '.join(f'{20+i*30},{160-min(140,s/2)}' for i,s in enumerate(speeds[:100]))
    return f'''<!doctype html><html><meta charset="utf-8"><title>GT7 session report</title><style>body{{font:16px system-ui;max-width:1000px;margin:40px auto;color:#172334}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #ddd}}svg{{max-width:100%}}@media print{{button{{display:none}}}}</style><h1>GT7 Race Engineer · Session report</h1><p>{html.escape(detail['provenance'].upper())} · {html.escape(detail['status'])} · {html.escape(detail['started'])}</p><p>Official lap validity unknown. Comparisons reflect application quality checks.</p><button onclick="print()">Print / Save PDF</button><h2>Lap maximum speed (km/h)</h2><svg viewBox="0 0 {max(300,len(speeds[:100])*30+40)} 180" role="img" aria-label="Maximum speed per lap"><polyline fill="none" stroke="#2563eb" stroke-width="3" points="{points}"/></svg><table><tr><th>Lap</th><th>Time (ms)</th><th>Timing source</th><th>Complete</th><th>Fuel (L)</th><th>Coast (s)</th></tr>{rows}</table><h2>Evidence-backed practice</h2>{''.join('<p>'+html.escape(c['title']+': '+c['observation']+' '+c['advice'])+'</p>' for c in report.get('improvements',[]))}<h2>Quality and metadata</h2><pre style="white-space:pre-wrap">{html.escape(json.dumps({'quality':report.get('quality'), 'pace':report.get('pace'), 'meta':detail['meta']},indent=2))}</pre></html>'''

def export_bundle(store,sid,directory):
    detail=store.detail(sid)
    if not detail:raise ValueError('Unknown session')
    path=Path(directory)/(sid+'.zip')
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        root=Path(tmp);(root/'metadata.json').write_text(json.dumps({'schema':1,**detail}),encoding='utf-8');(root/'report.html').write_text(report_html(detail),encoding='utf-8')
        cursor=0
        with (root/'samples.jsonl').open('w',encoding='utf-8') as raw,(root/'telemetry.csv').open('w',newline='',encoding='utf-8') as csvfile:
            writer=csv.writer(csvfile);writer.writerow(['utc','packet_id','lap','speed_kmh','rpm','fuel_L','throttle_ratio','brake_ratio'])
            while True:
                rows=store.samples(sid,-1e30,10000,cursor)
                if not rows:break
                for r in rows:
                    raw.write(json.dumps(r)+'\n');v=r['values'];writer.writerow([safe_cell(r['utc'])]+[safe_cell(v.get(k)) for k in ('packet_id','lap','speed_kmh','rpm','fuel','throttle','brake')])
                cursor=rows[-1]['record_id']
        manifest={}
        for p in root.iterdir():
            digest=hashlib.sha256()
            with p.open('rb') as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
            manifest[p.name]=digest.hexdigest()
        (root/'manifest.json').write_text(json.dumps(manifest))
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
            for p in root.iterdir():z.write(p,p.name)
    return path

def inspect_bundle(data):
    if len(data)>32*1024*1024:raise ValueError('Import exceeds 32 MiB')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        expected={'metadata.json','samples.jsonl','telemetry.csv','report.html','manifest.json'}
        if set(z.namelist())!=expected or len(z.namelist())!=5:raise ValueError('Unexpected bundle paths')
        if sum(x.file_size for x in z.infolist())>128*1024*1024:raise ValueError('Expanded bundle exceeds 128 MiB')
        manifest=json.loads(z.read('manifest.json'))
        for name in expected-{'manifest.json'}:
            if hashlib.sha256(z.read(name)).hexdigest()!=manifest.get(name):raise ValueError('Checksum mismatch')
        metadata=json.loads(z.read('metadata.json'))
        if metadata.get('schema')!=1:raise ValueError('Unsupported schema')
        if not isinstance(metadata.get('meta'),dict) or not isinstance(metadata.get('laps'),list):raise ValueError('Invalid metadata')
        if len(metadata['laps'])>10000:raise ValueError('Too many laps')
        datetime.fromisoformat(metadata['started'])
        for lap in metadata['laps']:
            if not isinstance(lap,dict) or not isinstance(lap.get('id'),str) or not isinstance(lap.get('number'),int):raise ValueError('Invalid lap metadata')
        rows=[]
        for line in z.read('samples.jsonl').splitlines():
            r=json.loads(line)
            if not isinstance(r.get('values'),dict) or not isinstance(r.get('mono'),(int,float)) or not math.isfinite(r['mono']):raise ValueError('Invalid sample')
            if r.get('variant') not in ('A','B','~','C'):raise ValueError('Invalid packet variant')
            if not isinstance(r.get('quality'),list) or len(r['quality'])>100 or any(not isinstance(q,str) or len(q)>300 for q in r['quality']):raise ValueError('Invalid quality flags')
            datetime.fromisoformat(r['utc'])
            for name,offset,fmt,units,variant in FIELDS:
                if name not in r['values']:raise ValueError('Missing channel: '+name)
                value=r['values'][name]
                if value is None:continue
                if fmt.endswith('s'):
                    if not isinstance(value,str) or len(value)>16:raise ValueError('Invalid text channel')
                else:
                    count=int(fmt[:-1] or 1)
                    vals=value if count>1 else [value]
                    if not isinstance(vals,list) or len(vals)!=count:raise ValueError('Invalid channel shape')
                    for v in vals:
                        if v is not None and (not isinstance(v,(int,float)) or not math.isfinite(v)):raise ValueError('Invalid numeric channel')
                        if fmt[-1]!='f' and not isinstance(v,int):raise ValueError('Invalid integer channel')
            for name in ('speed_kmh','gear','suggested_gear'):
                v=r['values'].get(name)
                if v is not None and (not isinstance(v,(int,float)) or not math.isfinite(v)):raise ValueError('Invalid derived channel')
            for name,count in [('position',3),('angular_velocity',3),('tyres',4)]:
                if not isinstance(r['values'].get(name),list) or len(r['values'][name])!=count:raise ValueError('Missing required array')
            for name in ('flags','packet_id','lap','car_id','gears'):
                if not isinstance(r['values'].get(name),int):raise ValueError('Required integer missing')
            for name in ('throttle','brake'):
                v=r['values'].get(name)
                if not isinstance(v,(int,float)) or not 0<=v<=1:raise ValueError('Invalid normalized pedal')
            if rows and r['mono']<rows[-1]['mono']:raise ValueError('Sample times must be nondecreasing')
            r['provenance']='import'
            rows.append(r)
            if len(rows)>100000:raise ValueError('Import limited to 100,000 samples')
        return metadata,rows
