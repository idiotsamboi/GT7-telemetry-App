"""Build an ARM64 Debian package on any build host, without root or dpkg."""
import io,tarfile,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'release';OUT.mkdir(exist_ok=True)
def tar(entries):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz') as archive:
        directories=set()
        for name,_,_ in entries:
            bits=name.split('/')
            directories.update('/'.join(bits[:i]) for i in range(1,len(bits)) if '/'.join(bits[:i])!='.')
        for name in sorted(directories):
            info=tarfile.TarInfo(name+'/');info.type=tarfile.DIRTYPE;info.mode=0o755;info.mtime=0;archive.addfile(info)
        for name,content,mode in entries:
            info=tarfile.TarInfo(name);info.size=len(content);info.mode=mode;info.mtime=0
            archive.addfile(info,io.BytesIO(content))
    return stream.getvalue()
entries=[]
def add(path,destination):
    for f in sorted(path.rglob('*')) if path.is_dir() else [path]:
        if f.is_file() and '__pycache__' not in f.parts:
            name=destination+'/'+str(f.relative_to(path)).replace('\\','/') if path.is_dir() else destination
            entries.append((name,f.read_bytes(),0o644))
for src in ['backend','frontend/dist','run.py','desktop.py','requirements-desktop.txt','THIRD_PARTY_NOTICES.md','docs/licenses','docs/car-assets-provenance.json','vendor/gt7-udp/LICENSE','release/INSTALL.md']:
    add(ROOT/src,'./opt/gt7-race-engineer/'+src)
model=ROOT/'data/models/vosk-model-small-en-us-0.15'
if not model.is_dir():raise SystemExit('Download the Vosk model first')
add(model,'./opt/gt7-race-engineer/models/vosk-model-small-en-us-0.15')
add(ROOT/'data/models/vosk-download.json','./opt/gt7-race-engineer/models/vosk-download.json')
wheels=ROOT/'data/linux-wheels'
if not wheels.is_dir() or not list(wheels.glob('*aarch64.whl')):raise SystemExit('Prepare ARM64 wheels first')
add(wheels,'./opt/gt7-race-engineer/wheels')
entries.extend([
('./opt/gt7-race-engineer/RELEASE',b'1.3.0\n',0o644),
('./usr/bin/gt7-race-engineer',(ROOT/'scripts/desktop-launch.sh').read_bytes(),0o755),
('./usr/share/applications/gt7-race-engineer.desktop',b'[Desktop Entry]\nType=Application\nName=GT7 Race Engineer\nComment=Offline race telemetry and analysis\nExec=gt7-race-engineer\nIcon=gt7-race-engineer\nTerminal=false\nCategories=Game;Utility;\n',0o644),
('./usr/share/icons/hicolor/scalable/apps/gt7-race-engineer.svg',b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#151a24"/><path d="M12 40L24 20l8 24 9-18 11 14" fill="none" stroke="#eb5360" stroke-width="6"/></svg>',0o644)])
control=b'Package: gt7-race-engineer\nVersion: 1.3.0\nArchitecture: arm64\nMaintainer: GT7 Race Engineer project\nDepends: python3 (>= 3.12), python3 (<< 3.13), python3-venv, python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, libportaudio2, espeak-ng, zenity, util-linux\nSection: games\nPriority: optional\nDescription: Local GT7 race engineer with offline speech and desktop telemetry\n Uses the system WebKit renderer and includes the Vosk small English model.\n'
parts=[('debian-binary',b'2.0\n'),('control.tar.gz',tar([('./control',control,0o644)])),('data.tar.gz',tar(entries))]
dest=OUT/'gt7-race-engineer_1.3.0_arm64.deb'
with dest.open('wb') as f:
    f.write(b'!<arch>\n')
    for name,data in parts:
        f.write(f'{name+"/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n'.encode());f.write(data)
        if len(data)%2:f.write(b'\n')
digest=hashlib.sha256(dest.read_bytes()).hexdigest();dest.with_suffix('.deb.sha256').write_text(f'{digest}  {dest.name}\n')
print(json.dumps({'package':str(dest),'bytes':dest.stat().st_size,'sha256':digest},indent=2))
