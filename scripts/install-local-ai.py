"""Install pinned, checksum-verified local AI assets. No telemetry is uploaded."""
import argparse,hashlib,json,urllib.request,zipfile,tarfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODEL={'url':'https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf','sha256':'74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db','name':'qwen2.5-0.5b-instruct-q4_k_m.gguf'}
RUNTIMES={'windows':('llama-b11201-bin-win-cpu-x64.zip','916708591114436aaedaa0a8079ac992ec3f82217694551333772136df9f75f0'),'arm64':('llama-b11201-bin-ubuntu-arm64.tar.gz','05c5f635c88a2c1df1dd15982f782c1b555be3150fb9469c610cdd9d8f97d1e3')}
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def download(url,path,expected):
 if path.exists() and digest(path)==expected:return
 partial=path.with_suffix(path.suffix+'.partial')
 with urllib.request.urlopen(url,timeout=60) as src,partial.open('wb') as dst:
  while chunk:=src.read(1024*1024):dst.write(chunk)
 if digest(partial)!=expected:raise RuntimeError('Checksum mismatch: '+path.name)
 partial.replace(path)
def main():
 p=argparse.ArgumentParser();p.add_argument('--platform',choices=RUNTIMES,default='windows' if sys.platform=='win32' else 'arm64');p.add_argument('--directory',type=Path,default=ROOT/'data/local-ai');a=p.parse_args()
 dest=a.directory.resolve();dest.mkdir(parents=True,exist_ok=True)
 download(MODEL['url'],dest/MODEL['name'],MODEL['sha256']);print('Model verified',flush=True)
 name,sha=RUNTIMES[a.platform];url='https://github.com/ggml-org/llama.cpp/releases/download/b11201/'+name
 download(url,dest/name,sha)
 target=dest/a.platform;target.mkdir(exist_ok=True)
 if name.endswith('.zip'):
  with zipfile.ZipFile(dest/name) as z:
   for entry in z.infolist():
    if not (target/entry.filename).resolve().is_relative_to(target):raise ValueError('Unsafe archive path')
   z.extractall(target)
 else:
  with tarfile.open(dest/name) as t:t.extractall(target,filter='data')
 (dest/'provenance.json').write_text(json.dumps({'model':MODEL,'runtime':{'release':'b11201','url':url,'sha256':sha}},indent=2))
 for repo,rev,file in [('Qwen/Qwen2.5-0.5B-Instruct-GGUF','9217f5db79a29953eb74d5343926648285ec7e67','LICENSE')]:
  (dest/'MODEL-LICENSE.txt').write_bytes(urllib.request.urlopen(f'https://huggingface.co/{repo}/resolve/{rev}/{file}',timeout=30).read())
 print('Installed to',dest)
if __name__=='__main__':main()
