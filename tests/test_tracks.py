import math,json
import pytest
from backend.app.tracks import TrackMap,validate_points,CATALOG
from backend.app.telemetry import demo_sample

def lap(m,number,start,flags=1):
 for i in range(601):
  s=demo_sample(start+i*.05,int((start+i*.05)*60));s.provenance='live'
  a=i/600*math.tau;s.values.update(position=[200*math.cos(a),0,200*math.sin(a)],lap=number+(i==600),flags=flags)
  m.consume(s)

def test_complete_lap_saved_but_partial_not_saved(tmp_path):
 m=TrackMap(tmp_path);m.select('10');lap(m,1,0)
 assert m.saved is None
 lap(m,2,30.05);m.flush();assert m.saved is not None
 m.flush();other=TrackMap(tmp_path);other.select('10')
 assert other.snapshot()['complete'] and len(other.saved['points'])>=20
 other.select('11');assert not other.snapshot()['complete'] and not other.points

def test_pause_and_teleport_do_not_save(tmp_path):
 m=TrackMap(tmp_path);m.select('10');lap(m,1,0);lap(m,2,30.05,3)
 assert m.saved is None
 s=demo_sample(61,3600);s.values.update(flags=0);m.consume(s)
 assert not m.points and m.partial

def test_import_boundaries_and_persistence(tmp_path):
 m=TrackMap(tmp_path);m.select('10');points=[[i,i*2] for i in range(20)]
 m.import_map('10',points);assert m.snapshot()['complete']
 assert (tmp_path/'track-maps/10.json').exists()
 with pytest.raises(ValueError):m.import_map('../../bad',points)
 for points in [[[0,0]]*19,[[0,0]]*4097,[[float('nan'),0]]*20,[[True,0]]*20]:
  with pytest.raises(ValueError):validate_points(points)

def test_catalogue_assets_exist():
 from pathlib import Path
 root=Path(__file__).resolve().parents[1]/'frontend/public'
 assert len(CATALOG)==41
 assert len({l['id'] for t in CATALOG for l in t['layouts']})==sum(len(t['layouts']) for t in CATALOG)
 assert all((root/t['logo'].lstrip('/')).is_file() for t in CATALOG)
