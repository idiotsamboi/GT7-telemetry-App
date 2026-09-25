"""Explicit small English model download. Never invoked by app startup."""
import argparse,urllib.request,hashlib,zipfile,tempfile,json
from pathlib import Path
parser=argparse.ArgumentParser(description='Download Vosk small English 0.15 (~40 MB, Apache 2.0). Requires network; do not run during a race.')
parser.add_argument('--accept-license',action='store_true');parser.add_argument('--destination',default='data/models');parser.add_argument('--sha256')
a=parser.parse_args()
if not a.accept_license:parser.error('Review https://alphacephei.com/vosk/models then pass --accept-license')
root=Path(a.destination).resolve();root.mkdir(parents=True,exist_ok=True)
url='https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
with tempfile.TemporaryDirectory() as d:
    path=Path(d)/'model.zip';urllib.request.urlretrieve(url,path);digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if a.sha256 and digest!=a.sha256:raise SystemExit('Checksum mismatch')
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>200*1024*1024:raise SystemExit('Unexpected model expansion size')
        for i in z.infolist():
            target=(root/i.filename).resolve()
            if not target.is_relative_to(root):raise SystemExit('Unsafe model archive path')
        z.extractall(root)
    (root/'vosk-download.json').write_text(json.dumps({'url':url,'sha256_observed':digest,'publisher_checksum_verified':bool(a.sha256),'license':'Apache-2.0'},indent=2))
    print('Model directory:',root/'vosk-model-small-en-us-0.15');print('Observed SHA256:',digest)
