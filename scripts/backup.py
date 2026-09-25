import argparse,sqlite3
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--database',required=True);p.add_argument('--output',required=True);a=p.parse_args();source=Path(a.database).resolve();dest=Path(a.output).resolve()
if source==dest or dest.exists():raise SystemExit('Choose a new backup destination')
dest.parent.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True) as src,sqlite3.connect(dest) as dst:src.backup(dst,pages=256,sleep=.1)
print('Backup ready:',dest)
