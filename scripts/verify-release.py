"""Verify archive integrity, platform payloads and absence of runtime user data."""
import io,json,tarfile,zipfile,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1];release=root/'release'
windows=release/'GT7-Race-Engineer-1.3.0-beta-windows-x64.zip'
def private(names):return [n for n in names if Path(n).name in ('control-token','settings.json','telemetry.sqlite3')]
with zipfile.ZipFile(windows) as archive:
    assert archive.testzip() is None
    names=archive.namelist()
    assert not private(names),private(names)
    for suffix in ['GT7 Race Engineer.exe','models/vosk-model-small-en-us-0.15/am/final.mdl','frontend/dist/brands/43.png','docs/car-assets-provenance.json','_tkinter.pyd','_tcl_data/init.tcl','_tk_data/tk.tcl']:
        assert any(n.endswith(suffix) for n in names),suffix
linux=release/'gt7-race-engineer_1.3.0_arm64.deb';raw=linux.read_bytes();assert raw[:8]==b'!<arch>\n';pos=8;parts={}
while pos<len(raw):
    header=raw[pos:pos+60];assert header[58:]==b'`\n';size=int(header[48:58]);parts[header[:16].decode().strip().rstrip('/')]=raw[pos+60:pos+60+size];pos+=60+size+size%2
with tarfile.open(fileobj=io.BytesIO(parts['control.tar.gz'])) as archive:
    control=archive.extractfile('./control').read().decode();assert 'Architecture: arm64' in control and 'python3 (>= 3.12)' in control
with tarfile.open(fileobj=io.BytesIO(parts['data.tar.gz'])) as archive:
    names=archive.getnames();assert not private(names)
    for name in ['desktop.py','frontend/dist/brands/43.png','models/vosk-model-small-en-us-0.15/am/final.mdl','docs/car-assets-provenance.json']:
        assert './opt/gt7-race-engineer/'+name in names,name
    assert archive.getmember('./usr/bin/gt7-race-engineer').mode==0o755
for artifact in (windows,linux):assert artifact.with_suffix(artifact.suffix+'.sha256').read_text().split()[0]==hashlib.sha256(artifact.read_bytes()).hexdigest()
result={'windows_zip_bytes':windows.stat().st_size,'linux_deb_bytes':linux.stat().st_size,'archive_integrity':'passed','checksums':'passed','no_user_settings_or_recordings':True}
(root/'docs/release-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
