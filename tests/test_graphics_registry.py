import pytest
from pydantic import ValidationError
from backend.app.group.models import Graphic,GRAPHICS
from backend.app.group.public import registry

NEW={'classification_strip','team_roster','lap_board','speed_comparison','connection_status','event_info','battle_tag','net_order'}
def test_registry_and_validated_models_agree():
 rows={r['id']:r for r in registry()}
 assert NEW<=set(rows) and len(rows)==28
 for key,row in rows.items():
  assert Graphic(id=key,template=key).template==key
  assert row['permissions'] and row['unavailable'] and row['settings']
 assert rows['speed_comparison']['permissions']==['telemetry']
 assert rows['fuel_status']['permissions']==['fuel']
 assert rows['team_roster']['slots']==['primary']
 assert rows['battle_tag']['slots']==['a','b']
 assert rows['net_order']['permissions']==['fuel','strategy']  # _public_projection is gated on BOTH categories

@pytest.mark.parametrize('settings',[{'title':{}},{'title':'x'*161},{'rows':0},{'rows':True},{'rows':2.5},{'opacity':float('nan')},{'opacity':2},{'opacity':False},{'html':'<script>'}])
def test_invalid_graphic_settings_cannot_reach_renderer(settings):
 with pytest.raises(ValidationError):Graphic(id='bad',template='event_info',settings=settings)

def test_graphic_settings_supported():
 assert Graphic(id='ok',template='lap_board',settings={'title':'Connected laps','rows':8,'opacity':.8}).settings['rows']==8
