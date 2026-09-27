import sys,asyncio,json,time,tempfile,platform,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.config import Config
from backend.app.storage import Store
from backend.app.runtime import Runtime
from backend.app.telemetry import demo_sample
from backend.app.local_ai import evidence
async def main():
 root=Path(__file__).resolve().parents[1]
 binary=next((root/'data/local-ai').rglob('llama-server.exe' if os.name=='nt' else 'llama-server'))
 with tempfile.TemporaryDirectory(dir=root/'data') as folder:
  path=Path(folder);cfg=Config(path);cfg.save({'speech_enabled':False,'hands_free':False,'local_ai_enabled':True,'local_ai_binary':str(binary),'local_ai_model':str(root/'data/local-ai/qwen2.5-0.5b-instruct-q4_k_m.gguf')})
  store=Store(path/'test.db');r=Runtime(cfg,store);r.source='demo'
  r.consume(demo_sample(5,300));r.box=True
  r.live_analysis.result={'available':True,'window_s':30,'coast_percent':42,'overlap_percent':20,'tyre_spread_c':24}
  before=evidence(r);start=time.perf_counter()
  try:
   await r.local_ai.refresh(r,True)
   async def keep_fresh():
    while r.local_ai.task and not r.local_ai.task.done():r.received_at=time.monotonic();await asyncio.sleep(.2)
   await keep_fresh();await r.local_ai.task
   result={'elapsed_s':time.perf_counter()-start,'model_bytes':Path(cfg.settings.local_ai_model).stat().st_size,'evidence_bytes':len(json.dumps(before).encode()),'input':before,'output':r.local_ai.result,'hardware':platform.platform()+'; validate independently on target Orange Pi'}
   (root/'docs/local-ai-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
   if r.local_ai.result.get('model_error'):
    print((path/'local-ai.log').read_text(errors='replace')[-5000:]);raise AssertionError(r.local_ai.result['model_error'])
   assert r.local_ai.result['engine'].startswith('Qwen')
   assert r.local_ai.result['status']=='ready'
  finally:await r.local_ai.close();store.close()
if __name__=='__main__':asyncio.run(main())
