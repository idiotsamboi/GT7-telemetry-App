import json, os, secrets
from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, IPvAnyAddress, model_validator

class Settings(BaseModel):
    schema_version:int=1
    ps5_ip:IPv4Address|None=None
    udp_bind:IPv4Address='0.0.0.0'
    udp_port:int=Field(33740,ge=1024,le=65535)
    remote_port:int=Field(33739,ge=1024,le=65535)
    http_host:IPvAnyAddress='127.0.0.1'
    http_port:int=Field(8000,ge=1024,le=65535)
    allowed_origins:list[str]=['http://127.0.0.1:8000','http://localhost:8000']
    variant:Literal['A','B','~','C']='A'
    heartbeat:float=Field(5,ge=1,le=15)
    ui_hz:int=Field(12,ge=2,le=20)
    stale_seconds:float=Field(2,ge=.5,le=20)
    interrupt_seconds:float=Field(30,ge=5,le=600)
    reserve_l:float=Field(2,ge=0,le=100)
    race_laps:int|None=Field(None,ge=1,le=10000)
    race_minutes:float|None=Field(None,gt=0,le=1440)
    extra_lap:bool=True
    target_ms:int|None=Field(None,gt=1000,le=3600000)
    mode:Literal['Quiet','Normal','Detailed','Coaching','Critical-only']='Normal'
    hard_mute:bool=False
    speech_enabled:bool=False
    speech_gap:float=Field(8,ge=1,le=60)
    speech_per_min:int=Field(4,ge=1,le=20)
    speech_seconds:float=Field(20,ge=2,le=60)
    tts:Literal['espeak','piper']='espeak'
    voice:str=Field('en-us',max_length=80,pattern=r'^[\w+\-]+$')
    voice_rate:int=Field(165,ge=80,le=300)
    voice_volume:int=Field(80,ge=0,le=100)
    piper_model:str=''
    vosk_model:str=''
    input_device:int|None=None
    output_device:int|None=None
    mic_rate:int=Field(16000,ge=8000,le=48000)
    recognition_confidence:float=Field(.7,ge=0,le=1)
    retain_transcripts:bool=False
    trust_c_fields:bool=False
    low_fuel_l:float=Field(3,ge=.1,le=30)
    tyre_limit_c:float|None=Field(None,ge=0,le=200)
    tyre_imbalance_c:float=Field(18,ge=2,le=100)
    alert_cooldown:float=Field(60,ge=5,le=600)
    raw_capture:bool=False
    track:str=Field('',max_length=120)
    layout:str=Field('',max_length=120)
    direction:Literal['unknown','forward','reverse']='unknown'
    setup_notes:str=Field('',max_length=4000)
    pit_limit_kmh:float|None=Field(None,gt=0,le=200)
    pit_region:list[float]|None=None
    theme:Literal['dark','light']='dark'
    minimal:bool=False
    reduced_motion:bool=True
    retention_days:int=Field(90,ge=1,le=3650)
    @model_validator(mode='after')
    def addresses(self):
        if self.ps5_ip and str(self.ps5_ip)==str(self.udp_bind): raise ValueError('Local bind address cannot be the console address')
        if self.pit_region is not None and len(self.pit_region)!=4: raise ValueError('Pit region is [minX,minZ,maxX,maxZ]')
        return self

class Config:
    def __init__(self,root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'settings.json'
        self.settings=Settings.model_validate_json(self.path.read_text()) if self.path.exists() else Settings()
        tokenpath=self.root/'control-token'
        if not tokenpath.exists(): tokenpath.write_text(secrets.token_urlsafe(32)); tokenpath.chmod(0o600)
        self.token=tokenpath.read_text().strip()
    def save(self,values):
        candidate=Settings.model_validate(values)
        temp=self.path.with_suffix('.tmp')
        with temp.open('w') as f: f.write(candidate.model_dump_json(indent=2)); f.flush(); os.fsync(f.fileno())
        temp.replace(self.path); self.settings=candidate
        return candidate
