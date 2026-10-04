import json, os, secrets, time, shutil
from ipaddress import IPv4Address
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal
from pydantic import BaseModel, Field, IPvAnyAddress, model_validator
from .core import defaults as D
from .core.config_migrations import migrate, backup_before_migration, load_raw
from .core.version import SETTINGS_SCHEMA_VERSION

class Units(BaseModel):
    """Display/spoken units. Internal data is always SI-ish (m/s, m, C, L, bar); see telemetry/units.py."""
    speed:Literal['kmh','mph']='kmh'
    temperature:Literal['C','F']='C'
    fuel:Literal['L','gal_us','gal_uk']='L'
    distance:Literal['m','km','mi']='m'
    pressure:Literal['bar','psi']='bar'

class Settings(BaseModel):
    schema_version:int=SETTINGS_SCHEMA_VERSION
    ps5_ip:IPv4Address|None=None
    udp_bind:IPv4Address='0.0.0.0'
    udp_port:int=Field(D.UDP_PORT,ge=1024,le=65535)
    remote_port:int=Field(D.REMOTE_PORT,ge=1024,le=65535)
    http_host:IPvAnyAddress='127.0.0.1'
    http_port:int=Field(D.HTTP_PORT,ge=1024,le=65535)
    allowed_origins:list[str]=['http://127.0.0.1:8000','http://localhost:8000']
    image_pack_dir:str=Field('',max_length=500)
    variant:Literal['A','B','~','C']='A'
    heartbeat:float=Field(D.HEARTBEAT_S,ge=.25,le=15)
    ui_hz:int=Field(D.UI_HZ,ge=2,le=20)
    stale_seconds:float=Field(D.STALE_S,ge=.5,le=20)
    interrupt_seconds:float=Field(D.INTERRUPT_S,ge=5,le=600)
    reserve_l:float=Field(2,ge=0,le=100)
    race_laps:int|None=Field(None,ge=1,le=10000)
    race_minutes:float|None=Field(None,gt=0,le=1440)
    extra_lap:bool=True
    target_ms:int|None=Field(None,gt=1000,le=3600000)
    mode:Literal['Quiet','Normal','Detailed','Coaching','Critical-only']='Normal'
    hard_mute:bool=False
    speech_enabled:bool=True
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
    hands_free:bool=True
    local_ai_enabled:bool=False
    local_ai_model:str=''
    local_ai_binary:str=''
    local_ai_port:int=Field(D.LOCAL_AI_PORT,ge=1024,le=65535)
    local_ai_interval:float=Field(45,ge=15,le=300)
    trust_c_fields:bool=False
    low_fuel_l:float=Field(3,ge=.1,le=30)
    tyre_limit_c:float|None=Field(None,ge=0,le=200)
    tyre_imbalance_c:float=Field(18,ge=2,le=100)
    alert_cooldown:float=Field(60,ge=5,le=600)
    raw_capture:bool=False
    track_id:str=Field('',max_length=16)
    track:str=Field('',max_length=120)
    layout:str=Field('',max_length=120)
    direction:Literal['unknown','forward','reverse']='unknown'
    setup_notes:str=Field('',max_length=4000)
    pit_limit_kmh:float|None=Field(None,gt=0,le=200)
    pit_region:list[float]|None=None
    theme:Literal['dark','light']='dark'
    minimal:bool=False
    reduced_motion:bool=True
    retention_days:int=Field(D.RETENTION_DAYS,ge=1,le=3650)
    max_storage_gb:float|None=Field(None,gt=0,le=100000)      # optional: retention may also archive the oldest sessions past this size
    battles_desk_chime:bool=False
    local_ai_rephrase:bool=False
    max_save_percent:float=Field(8,ge=1,le=20)
    fuel_time_slope_s_per_l:float|None=Field(None,ge=.5,le=20)
    pit_loss_s:float|None=Field(None,ge=5,le=120)
    refuel_rate_lps:float|None=Field(None,ge=.5,le=20)
    tyre_heat_rate_c_s:float=Field(.15,ge=.05,le=1)
    tyre_heat_anomaly_c:float=Field(4,ge=1,le=20)
    coaching_min_loss_s:float=Field(.05,ge=0,le=5)
    # schema v2 (core/config_migrations.py)
    units:Units=Field(default_factory=Units)
    performance_profile:Literal['AUTO','DESKTOP','LOW_POWER']='AUTO'
    log_level:Literal['DEBUG','INFO','WARNING','ERROR']='INFO'
    feature_flags:dict[str,bool]=Field(default_factory=dict)
    safe_mode_on_crash:bool=True
    developer_mode:bool=False
    demo_scenario:str=Field('',max_length=40)     # '' = free-running demo; else a telemetry.sources scenario (always SYNTHETIC)
    @model_validator(mode='after')
    def addresses(self):
        if self.demo_scenario:
            from .telemetry.sources import SCENARIOS
            if self.demo_scenario not in SCENARIOS:raise ValueError('Unknown demo scenario')
        if len(self.allowed_origins)>32:raise ValueError('At most 32 browser origins are allowed')
        for origin in self.allowed_origins:
            try:
                parsed=urlsplit(origin);port=parsed.port
                if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or '*' in parsed.netloc:raise ValueError('invalid origin')
            except ValueError:raise ValueError('Browser origins must be exact http(s) addresses without paths or credentials')
        if self.ps5_ip and str(self.ps5_ip)==str(self.udp_bind): raise ValueError('Local bind address cannot be the console address')
        if self.pit_region is not None and len(self.pit_region)!=4: raise ValueError('Pit region is [minX,minZ,maxX,maxZ]')
        return self

class Config:
    def __init__(self,root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'settings.json'
        self.recovery_notice=None
        self.migrated_from=None
        try:self.settings=self._load()
        except (ValueError,OSError):
            self.settings=Settings(hands_free=False,speech_enabled=False)
            backup=self.path.with_name('settings.invalid-'+str(time.time_ns())+'.json')
            try:
                shutil.copy2(self.path,backup);self.recovery_notice='Invalid settings preserved as '+backup.name+'. Safe defaults loaded; review Settings before driving.'
                for old in sorted(self.root.glob('settings.invalid-*.json'))[:-5]:old.unlink(missing_ok=True)      # keep the newest five
            except OSError:self.recovery_notice='Settings could not be read or backed up. Safe defaults loaded; original file was not changed.'
        tokenpath=self.root/'control-token'
        if not tokenpath.exists(): tokenpath.write_text(secrets.token_urlsafe(32)); tokenpath.chmod(0o600)
        self.token=tokenpath.read_text().strip()
    def _load(self):
        if not self.path.exists():return Settings()
        raw=load_raw(self.path)
        raw,applied=migrate(raw)
        settings=Settings.model_validate(raw)       # validated first, so a bad file is never half-migrated
        if applied:
            self.migrated_from=applied[0]
            try:backup_before_migration(self.path,applied[0]);self._write(settings)      # original kept as settings.v{n}.bak.json
            except OSError:pass       # locked/read-only file (e.g. a syncing folder): keep the migrated settings in memory, retry on next save
        return settings
    def _write(self,candidate):
        temp=self.path.with_suffix('.tmp')
        with temp.open('w',encoding='utf-8') as f: f.write(candidate.model_dump_json(indent=2)); f.flush(); os.fsync(f.fileno())
        temp.replace(self.path)
    def save(self,values):
        candidate=Settings.model_validate({**values,'schema_version':SETTINGS_SCHEMA_VERSION})     # never persist a schema this build cannot load
        self._write(candidate); self.settings=candidate
        return candidate
