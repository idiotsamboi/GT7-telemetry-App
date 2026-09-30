#!/usr/bin/env python3
"""GT7 launcher. No Node.js or network service is needed at runtime."""
import argparse,json,os,sys,platform,shutil,socket
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description='GT7 Race Engineer')
    parser.add_argument('command',nargs='?',choices=['run','diagnostics','connection-test'],default='run')
    parser.add_argument('--data',default=str(Path(__file__).resolve().parent/'data'))
    parser.add_argument('--duration',type=float,default=10,help='Connection test duration in seconds')
    parser.add_argument('--demo',action='store_true');parser.add_argument('--scenario',help='With --demo: run a deterministic synthetic scenario (normal_laps, lap_transition, fuel_burn_and_refuel, braking_zones, packet_loss_burst, out_of_order, stream_stale_10s, session_end, variant_switch_A_to_C)');parser.add_argument('--safe-mode',action='store_true',help='Start with experimental features, microphone, local AI and the console heartbeat off');parser.add_argument('--host');parser.add_argument('--port',type=int);parser.add_argument('--ps5')
    args=parser.parse_args()
    from backend.app.config import Config
    cfg=Config(args.data)
    if args.command=='diagnostics':
        from backend.app.voice import audio_devices
        facts={'platform':platform.platform(),'architecture':platform.machine(),'python':sys.version,'disk':shutil.disk_usage(args.data)._asdict(),'audio':audio_devices(),'espeak':shutil.which('espeak-ng'),'piper':shutil.which('piper'),'frontend_built':Path('frontend/dist/index.html').exists()}
        for key,path in [('board','/proc/device-tree/model'),('memory','/proc/meminfo'),('os','/etc/os-release')]:
            try:facts[key]=Path(path).read_text().replace('\0','')[:1500]
            except OSError:facts[key]=None
        print(json.dumps(facts,indent=2));return
    if args.command=='connection-test':
        ip=args.ps5 or cfg.settings.ps5_ip
        if not ip:parser.error('Set a PS5 address or pass --ps5. 192.168.88.21 is only a previous suggestion.')
        from backend.app.telemetry import parse,PacketError
        from backend.app.diagnostics import udp_owners,routing_address
        import time
        print(f'Console {ip}:{cfg.settings.remote_port}; local bind {cfg.settings.udp_bind}:{cfg.settings.udp_port}; route {routing_address(str(ip))}; requested {cfg.settings.variant}')
        valid=0;invalid=0;foreign=0;last_error=None
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                if os.name=='nt':sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                sock.bind((str(cfg.settings.udp_bind),cfg.settings.udp_port));sock.settimeout(.25)
                deadline=time.monotonic()+max(1,min(args.duration,120));heartbeat=0
                while time.monotonic()<deadline:
                    if time.monotonic()>=heartbeat:
                        sock.sendto(cfg.settings.variant.encode(),(str(ip),cfg.settings.remote_port));heartbeat=time.monotonic()+cfg.settings.heartbeat
                    try:data,addr=sock.recvfrom(65535)
                    except socket.timeout:continue
                    if addr[0]!=str(ip):foreign+=1;continue
                    try:sample=parse(data)
                    except PacketError as e:invalid+=1;last_error=f'{e.code}: {e}';continue
                    valid+=1
                    if valid==1:print(f'Validated {sample.variant}, {sample.wire_length} bytes, packet {sample.values["packet_id"]}, speed {sample.values["speed_kmh"]} km/h, car {sample.values["car_id"]}.')
            print(json.dumps({'valid_packets':valid,'rejected_packets':invalid,'unexpected_senders':foreign,'last_error':last_error},indent=2))
            if not valid:print('No validated PS5 packets. Start driving and check console address/network/firewall. Menu silence does not prove a variant is unsupported.');sys.exit(1)
        except OSError as e:
            print(f'Local UDP receiver could not start: {e}')
            print(json.dumps({'port_owners':udp_owners(cfg.settings.udp_port)},indent=2))
            print('Stop this application and other telemetry receivers before running the standalone connection test.');sys.exit(1)
        return
    overrides={}
    if args.ps5:overrides['ps5_ip']=args.ps5
    if args.host:overrides['http_host']=args.host
    if args.port:overrides.update(http_port=args.port,allowed_origins=[f'http://127.0.0.1:{args.port}',f'http://localhost:{args.port}'])
    if args.scenario:
        from backend.app.telemetry.sources import SCENARIOS
        if args.scenario not in SCENARIOS:parser.error('Unknown scenario; choose one of: '+', '.join(SCENARIOS.ids()))
        if not args.demo:parser.error('--scenario needs --demo')
        os.environ['GT7_SCENARIO']=args.scenario      # per run only; Settings.demo_scenario is the persisted developer setting
    if overrides:cfg.save({**cfg.settings.model_dump(),**overrides})      # never rewrite settings.json just because the app started
    os.environ['GT7_DATA']=str(Path(args.data).resolve())
    if args.demo:os.environ['GT7_DEMO']='1'
    if args.safe_mode:os.environ['GT7_SAFE_MODE']='1'
    import uvicorn
    from backend.app.api import create_app
    print(f'Open http://127.0.0.1:{cfg.settings.http_port}. LAN pairing token is stored in {cfg.root / "control-token"}.')
    uvicorn.run(create_app(args.data,config=cfg),host=str(cfg.settings.http_host),port=cfg.settings.http_port,workers=1,access_log=False)
if __name__=='__main__':main()
