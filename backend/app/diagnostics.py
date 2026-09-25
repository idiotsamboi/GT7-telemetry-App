"""Read-only network diagnostics. Never stops another application's receiver."""
import csv,io,platform,shutil,socket,subprocess

def udp_owners(port:int):
    if not 1<=port<=65535:raise ValueError('Invalid UDP port')
    options={'capture_output':True,'text':True,'timeout':3}
    if platform.system()=='Windows':
        options['creationflags']=subprocess.CREATE_NO_WINDOW
        try:
            result=subprocess.run(['netstat','-ano','-p','udp'],**options)
            pids=set()
            for line in result.stdout.splitlines():
                parts=line.split()
                if len(parts)>=4 and parts[0]=='UDP' and parts[1].rsplit(':',1)[-1]==str(port):pids.add(int(parts[-1]))
            owners=[]
            for pid in sorted(pids)[:8]:
                name=None
                result=subprocess.run(['tasklist','/FI',f'PID eq {pid}','/FO','CSV','/NH'],**options)
                for row in csv.reader(io.StringIO(result.stdout)):
                    if len(row)>1 and row[1]==str(pid):name=row[0]
                owners.append({'pid':pid,'name':name or 'unknown process'})
            return owners
        except (OSError,subprocess.TimeoutExpired,ValueError):return []
    if shutil.which('ss'):
        try:
            result=subprocess.run(['ss','-H','-lunp',f'sport = :{port}'],**options)
            return [{'description':line[:400]} for line in result.stdout.splitlines()[:8]]
        except (OSError,subprocess.TimeoutExpired):pass
    return []

def routing_address(remote:str):
    """UDP connect asks the local routing table; no application payload is sent."""
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect((remote,33739));return sock.getsockname()[0]
    except OSError:return None
