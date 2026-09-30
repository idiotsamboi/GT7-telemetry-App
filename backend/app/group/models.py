from typing import Literal,Annotated
from pydantic import BaseModel,Field,ConfigDict,field_validator
import math
from .graphics import legacy_graphics,template_ids

class Model(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
Text=Annotated[str,Field(max_length=160)]
class Branding(Model):
    name:Text='League'
    short_name:Annotated[str,Field(max_length=24)]='GT7'
    tagline:Text=''
    logos:dict[str,str]=Field(default_factory=dict,max_length=5)
    colors:dict[str,str]=Field(default_factory=lambda:{'primary':'#ed1b35','secondary':'#252530','accent':'#f5ce42','background':'#101014','text':'#ffffff'},max_length=5)
    font:Literal['system','sans','mono']='system'
    sponsors:list[dict]=Field(default_factory=list,max_length=20)
    teams:list[dict]=Field(default_factory=list,max_length=32)
    fit:Literal['contain','cover']='contain'
    align:Literal['left','center','right']='center'
    padding:int=Field(12,ge=0,le=100)
    opacity:float=Field(1,ge=0,le=1)
    safe_area:int=Field(40,ge=0,le=160)
    @field_validator('colors')
    @classmethod
    def colors_valid(cls,v):
        import re
        if set(v)-{'primary','secondary','accent','background','text'} or any(not re.fullmatch(r'#[0-9a-fA-F]{6}',x) for x in v.values()):raise ValueError('Colors must be six-digit hex colors')
        return v
    @field_validator('logos')
    @classmethod
    def logos_valid(cls,v):
        if set(v)-{'primary','light','dark','compact','watermark'}:raise ValueError('Unknown logo variant')
        return v

class GroupConfig(Model):
    name:Text
    league_id:Text
    event_name:Text
    layout_id:Annotated[str,Field(max_length=16)]=''
    format:Literal['practice','qualifying','laps','timed','manual']='practice'
    laps:int|None=Field(None,ge=1,le=10000)
    duration_s:int|None=Field(None,ge=10,le=86400)
    capacity:int=Field(16,ge=1,le=32)
    approval:bool=True
    join_locked:bool=False
    complete_field:bool=False
    required_sharing:list[Literal['basic','telemetry','fuel','strategy']]=['basic']
    publication:list[Literal['basic','telemetry','fuel','strategy']]=['basic']
    delay_s:int=Field(0,ge=0,le=120)
    provenance:Literal['live','demo']='live'
    branding:dict=Field(default_factory=dict,max_length=12)
    allow_workspace_branding:bool=True
    pit_loss_s:float|None=Field(None,ge=5,le=120)
    refuel_rate_lps:float|None=Field(None,ge=0.5,le=20)
    share_traffic_with_drivers:bool=False
    battles_include_lapping:bool=False
    battle_weights:dict[Literal['gap','close','pos','dur'],float]|None=None
    steward_popup_kinds:list[Literal['incident','investigation','warning','time','laps','disqualification','order','correction']]=['investigation','warning','time','laps','disqualification']
    steward_popup_s:int=Field(10,ge=3,le=60)
    auto_steward_paused:bool=False
    @field_validator('required_sharing','publication')
    @classmethod
    def basic_required(cls,v):return sorted(set(['basic',*v]))
    @field_validator('battle_weights')
    @classmethod
    def weights_valid(cls,v):
        if v is not None and (not v or any(isinstance(x,bool) or not isinstance(x,(int,float)) or x<0 for x in v.values())):raise ValueError('Battle weights must be non-negative numbers')
        return v

class Identity(Model):
    display_name:Text
    number:Annotated[str,Field(max_length=8)]=''
    team:Text=''
    class_name:Text=''
    driver_id:Annotated[str,Field(max_length=64)]=''
    roster:list[Text]=Field(default_factory=list,max_length=10)

class Join(Model):
    version:Literal[1]=1
    credential:Annotated[str,Field(min_length=20,max_length=200)]
    identity:Identity
    accepted_sharing:list[Literal['basic','telemetry','fuel','strategy']]=['basic']

class Packet(Model):
    version:Literal[1]=1
    group_id:Text
    session_id:Text
    participant_id:Text
    entry_id:Text
    boot_id:Annotated[str,Field(min_length=1,max_length=64)]
    sequence:int=Field(ge=0,le=9007199254740991)
    source_mono:float
    source_utc:float
    provenance:Literal['live','demo','replay']
    layout_id:Annotated[str,Field(max_length=16)]
    local_session_id:Text
    values:dict=Field(max_length=40)
    available:list[Text]=Field(default_factory=list,max_length=40)
    quality:list[Text]=Field(default_factory=list,max_length=32)
    @field_validator('values')
    @classmethod
    def values_valid(cls,v):
        allowed={'position','lap','last_ms','best_ms','current_ms','flags','car_id','speed_kmh','rpm','gear','throttle','brake','clutch','fuel','fuel_capacity','tyres','strategy'}
        if set(v)-allowed:raise ValueError('Unsupported shared field')
        for k,x in v.items():
            if x is None:continue
            if k=='strategy':
                if not isinstance(x,dict) or set(x)-{'laps_remaining','margin_l','litres_per_lap'}:raise ValueError('Invalid strategy')
                items=list(x.values())
            elif k in ('position','tyres'):
                if not isinstance(x,list) or len(x)!=(3 if k=='position' else 4):raise ValueError('Invalid vector')
                items=x
            else:items=[x]
            if any(a is not None and (isinstance(a,bool) or not isinstance(a,(int,float)) or not math.isfinite(a) or abs(a)>1e8) for a in items):raise ValueError('Invalid numeric telemetry')
        for k in ('lap','flags','car_id','gear'):
            if v.get(k) is not None and (isinstance(v[k],bool) or not isinstance(v[k],int)):raise ValueError('Integer field required')
        return v

class Instruction(Model):
    flag:Literal['green','yellow','double_yellow','red','blue','white','black','warning','mechanical','checkered','safety_car','fcy','vsc']
    scope:Literal['global','zone','entry']='global'
    target:Text=''
    reason:Annotated[str,Field(max_length=500)]
    expires_in:int|None=Field(None,ge=5,le=86400)

class Message(Model):
    text:Annotated[str,Field(min_length=1,max_length=500)]
    scope:Literal['all','class','team','entry']='all'
    target:Text=''
    priority:int=Field(1,ge=0,le=3)
    expires_in:int=Field(60,ge=5,le=3600)
    acknowledgement:bool=False
    public:bool=False

class Decision(Model):
    entry_id:Text
    kind:Literal['incident','investigation','warning','time','laps','disqualification','order','correction']
    reason:Annotated[str,Field(min_length=1,max_length=1000)]
    value:float=Field(0,ge=0,le=1000000)
    status:Literal['open','investigating','resolved','withdrawn']='open'
    public:bool=False
    supersedes:Text=''

class Zone(Model):
    name:Text
    start:float=Field(ge=0,lt=1)
    end:float=Field(ge=0,lt=1)

# Derived from the template registry (group/graphics.py): id -> (name, width, height).
GRAPHICS=legacy_graphics()
class Graphic(Model):
    id:Annotated[str,Field(max_length=64)]
    template:Literal.__getitem__(template_ids())
    visible:bool=True
    x:int=Field(0,ge=0,le=1920)
    y:int=Field(0,ge=0,le=1080)
    width:int=Field(600,ge=100,le=1920)
    height:int=Field(300,ge=50,le=1080)
    entry_id:Text=''
    slot:Literal['primary','a','b']='primary'
    duration_s:int=Field(0,ge=0,le=3600)
    settings:dict=Field(default_factory=dict,max_length=10)
    @field_validator('settings')
    @classmethod
    def settings_valid(cls,v):
        import math
        if set(v)-{'title','rows','opacity'}:raise ValueError('Unsupported graphic setting')
        if 'title' in v and (not isinstance(v['title'],str) or len(v['title'])>160):raise ValueError('Graphic title must be text up to 160 characters')
        if 'rows' in v and (isinstance(v['rows'],bool) or not isinstance(v['rows'],int) or not 1<=v['rows']<=32):raise ValueError('Graphic rows must be an integer from 1 to 32')
        if 'opacity' in v and (isinstance(v['opacity'],bool) or not isinstance(v['opacity'],(int,float)) or not math.isfinite(v['opacity']) or not 0<=v['opacity']<=1):raise ValueError('Graphic opacity must be from zero to one')
        return v
class WorkspaceConfig(Model):
    name:Text='Broadcast'
    preset:Literal['formula','endurance','minimal','neon','vintage','rally','oval','carbon','heritage','holo']='formula'
    delay_s:int=Field(0,ge=0,le=120)
    slots:dict[str,str]=Field(default_factory=lambda:{'primary':'','a':'','b':'','team':'','class':''},max_length=5)
    selection_mode:Literal['manual','leader','class_leader','position']='manual'
    selection_position:int=Field(1,ge=1,le=32)
    auto_replace:bool=False
    favorites:list[Text]=Field(default_factory=list,max_length=32)
    pinned:list[Text]=Field(default_factory=list,max_length=32)
    template_favorites:list[Text]=Field(default_factory=list,max_length=10)
    animation:bool=True
    cycle_s:int=Field(0,ge=0,le=300)
    branding:dict=Field(default_factory=dict,max_length=12)
    graphics:list[Graphic]=Field(default_factory=list,max_length=20)
    battle_auto_take:bool=False
    auto_steward:bool=True
    steward_popup_graphic_id:Annotated[str,Field(max_length=64)]=''
    @field_validator('slots')
    @classmethod
    def slots_valid(cls,v):
        if set(v)-{'primary','a','b','team','class'}:raise ValueError('Unknown slot')
        return v
