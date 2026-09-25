import argparse,time,tempfile,json,sys,statistics,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.telemetry import demo_sample,parse
from backend.app.config import Config
from backend.app.storage import Store
from backend.app.runtime import Runtime
p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=30);p.add_argument('--hours',type=float);p.add_argument('--rate',type=float,default=60);p.add_argument('--output',default='docs/benchmark.json');a=p.parse_args();duration=a.hours*3600 if a.hours else a.seconds
with tempfile.TemporaryDirectory() as d:
    cfg=Config(d);store=Store(Path(d)/'soak.db');r=Runtime(cfg,store);latencies=[];start=time.perf_counter();cpu=time.process_time();i=0;max_queue=0
    while time.perf_counter()-start<duration:
        before=time.perf_counter();sample=demo_sample(i/60,i);r.consume(sample);latencies.append((time.perf_counter()-before)*1000)
        if len(latencies)>100000:latencies=latencies[-50000:]
        i+=1;max_queue=max(max_queue,store.q.qsize());target=start+i/a.rate;time.sleep(max(0,target-time.perf_counter()))
    report_start=time.perf_counter();r.sessions.end();report_ms=(time.perf_counter()-report_start)*1000;store.flush();elapsed=time.perf_counter()-start
    result={'platform':sys.platform,'source':'synthetic accelerated / no audio / no browser','samples':i,'duration_s':elapsed,'samples_per_s':i/elapsed,'ingest_p95_ms':sorted(latencies)[int(.95*len(latencies))],'initial_report_ms':report_ms,'cpu_seconds':time.process_time()-cpu,'queue_peak':max_queue,'storage':store.health(),'hardware_validation':False}
    Path(a.output).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));store.close()
