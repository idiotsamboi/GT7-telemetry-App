"""Smoke-test the packaged Windows microphone worker without touching live data."""
import subprocess,time,json,urllib.request,http.cookiejar,socket
from pathlib import Path
root=Path(__file__).resolve().parents[1]
data=root/'data/frozen-audit-13'
with socket.socket() as probe:
    if probe.connect_ex(('127.0.0.1',28300))==0:raise SystemExit('Test port is already in use')
exe=root/'release/windows-1.3.0/GT7 Race Engineer/GT7 Race Engineer.exe'
process=subprocess.Popen([str(exe),'--desktop','--data',str(data),'--port','28300'])
op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(path,data=None,method=None):
    return json.load(op.open(urllib.request.Request('http://127.0.0.1:28300/api/'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method),timeout=3))
try:
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Packaged app exited before startup; inspect data/frozen-audit-13/runtime.log')
        try:call('pair',{});break
        except Exception:time.sleep(.3)
    settings=call('settings');settings.update(hands_free=True,speech_enabled=False);call('settings',settings,'PUT')
    while time.monotonic()<deadline:
        state=call('state')
        if state['audio']['microphone']=='listening':break
        time.sleep(.3)
    result={'frozen_executable':True,'catalog_count':call('engineer/requests')['count'],'audio':state['audio'],'heartbeat':call('settings')['heartbeat']}
    (root/'docs/frozen-handsfree-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    assert state['audio']['microphone']=='listening',state['audio']
    assert not state['audio']['mic_error']
finally:
    try:call('control',{'action':'listen_off'});time.sleep(2)
    except Exception:pass
    if process.poll() is None:process.terminate();process.wait(timeout=10)
