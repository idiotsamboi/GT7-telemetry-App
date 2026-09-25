"""Explicit GT7 wire layout, ported from MacManley/gt7-udp (MIT)."""
from dataclasses import dataclass, field, asdict
import math, struct, time
from datetime import datetime, timezone
from Crypto.Cipher import Salsa20

UPSTREAM = 'a768574ba809429ce0455b988794e028660f6b9b'
PARSER_VERSION = '1.1'
LENGTHS = {296:'A',316:'B',344:'~',368:'C'}
XOR = {'A':0xDEADBEAF,'B':0xDEADBEEF,'~':0x55FABB4F,'C':0xDEADBEEF}
KEY = b'Simulator Interface Packet GT7 ver 0.0'[:32]
# name, offset, struct format, units, first variant. Unknown values remain raw.
FIELDS = [
('position',4,'3f','m','A'),('velocity',16,'3f','m/s','A'),('rotation',28,'3f','raw','A'),
('north',40,'f','raw','A'),('angular_velocity',44,'3f','rad/s','A'),('body_height',56,'f','m','A'),
('rpm',60,'f','rpm','A'),('fuel',68,'f','L','A'),('fuel_capacity',72,'f','L','A'),('speed',76,'f','m/s','A'),
('boost',80,'f','raw +1','A'),('oil_pressure',84,'f','bar','A'),('water_temp',88,'f','C constant','A'),
('oil_temp',92,'f','C constant','A'),('tyres',96,'4f','C surface','A'),('packet_id',112,'I','counter','A'),
('lap',116,'h','lap','A'),('total_laps',118,'h','laps','A'),('best_ms',120,'i','ms','A'),('last_ms',124,'i','ms','A'),
('day_ms',128,'i','time of day ms','A'),('start_position',132,'h','pre-race only','A'),('start_cars',134,'h','pre-race only','A'),
('rpm_min',136,'h','rpm','A'),('rpm_max',138,'h','rpm','A'),('transmission_max',140,'h','km/h','A'),
('flags',142,'H','bits','A'),('gears',144,'B','nibbles','A'),('throttle_raw',145,'B','0-255','A'),('brake_raw',146,'B','0-255','A'),
('road_plane',148,'3f','raw','A'),('road_distance',160,'f','m','A'),('wheel_angular',164,'4f','rad/s','A'),
('tyre_radius',180,'4f','m','A'),('suspension',196,'4f','m','A'),('unknown_a',212,'8f','unknown','A'),
('clutch',244,'f','ratio','A'),('clutch_engagement',248,'f','ratio','A'),('gearbox_rpm',252,'f','rpm','A'),
('transmission_ratio',256,'f','ratio','A'),('gear_ratios',260,'8f','ratio','A'),('car_id',292,'i','ID','A'),
('steering_rotation',296,'f','rad upstream; unverified behavior','B'),('steering_velocity',300,'f','rad/s','B'),
('acceleration_raw',304,'3f','frame unverified','B'),('throttle_filtered',316,'B','0-255','~'),('brake_filtered',317,'B','0-255','~'),
('unknown_t_bytes',318,'2B','unknown','~'),('torque_vectors',320,'4f','upstream interpretation unverified','~'),
('energy_recovery',336,'f','unknown','~'),('unknown_t',340,'f','unknown','~'),('surface',344,'4s','upstream surface codes','C'),
('current_ms',348,'i','ms upstream; opt-in','C'),('wheel_steering',352,'2f','rad upstream; opt-in','C'),
('wheelbase',360,'f','m','C'),('category',364,'4s','text','C')]

CAPABILITIES = {n:{'offset':o,'format':f,'units':u,'variant':v,'source':'telemetry',
    'confidence':'upstream layout; hardware unverified','validity':'finite; negative timing sentinels null'} for n,o,f,u,v in FIELDS}
UNSUPPORTED = {k:'Not established in the player-car UDP stream' for k in ['leaderboard','opponents','penalties','tyre_wear','tyre_pressure','weather','official_lap_validity','race_finish','track_name','damage','understeer_diagnosis']}

class PacketError(ValueError):
    """Stable machine-readable rejection reason plus a human-readable explanation."""
    def __init__(self,code,message,*,length=None,variant=None):
        super().__init__(message)
        self.code=code;self.length=length;self.variant=variant

MAGIC=0x47375330
_LAYOUT=[(name,offset,struct.Struct('<'+fmt)) for name,offset,fmt,units,variant in FIELDS]

def decrypt_datagram(data):
    if not isinstance(data,(bytes,bytearray,memoryview)):
        raise PacketError('invalid_input','Datagram must be a bytes-like object')
    data=bytes(data)
    variant=LENGTHS.get(len(data))
    if variant is None:
        raise PacketError('bad_length',f'Unsupported datagram length {len(data)}; expected 296, 316, 344 or 368',length=len(data))
    seed=struct.unpack_from('<I',data,0x40)[0]
    nonce=struct.pack('<II',seed ^ XOR[variant],seed)
    plaintext=Salsa20.new(key=KEY,nonce=nonce).decrypt(data)
    magic=struct.unpack_from('<I',plaintext)[0]
    if magic!=MAGIC:
        raise PacketError('bad_magic',f'{variant} decryption failed magic check (0x{magic:08X})',length=len(data),variant=variant)
    return plaintext,variant

@dataclass(slots=True)
class Sample:
    values: dict
    mono: float = field(default_factory=time.monotonic)
    utc: str = field(default_factory=lambda:datetime.now(timezone.utc).isoformat())
    variant: str = 'A'
    provenance: str = 'live'
    quality: list = field(default_factory=list)
    raw_hex: str | None = None
    parser_version: str = PARSER_VERSION
    wire_length: int | None = None
    def json(self): return asdict(self)

def parse(data: bytes, *, encrypted=True, mono=None, provenance='live', raw=False) -> Sample:
    received_mono=time.monotonic() if mono is None else mono
    received_utc=datetime.now(timezone.utc).isoformat()
    if not isinstance(received_mono,(int,float)) or not math.isfinite(received_mono):
        raise PacketError('invalid_timestamp','Receive timestamp must be finite')
    if not isinstance(data,(bytes,bytearray,memoryview)):
        raise PacketError('invalid_input','Datagram must be a bytes-like object')
    original=bytes(data)
    if encrypted:
        data,variant=decrypt_datagram(original)
    else:
        data=original;variant=LENGTHS.get(len(data))
        if variant is None:raise PacketError('bad_length','Unsupported packet length',length=len(data))
        if struct.unpack_from('<I',data)[0]!=MAGIC:raise PacketError('bad_magic','Bad plaintext magic',length=len(data),variant=variant)
    values, quality = {}, []
    for name, offset, decoder in _LAYOUT:
        if offset+decoder.size>len(data): values[name]=None; continue
        result=decoder.unpack_from(data,offset)
        converted=[]
        for value in result:
            if isinstance(value,bytes): value=value.decode('ascii',errors='replace').rstrip('\0')
            if isinstance(value,float) and not math.isfinite(value): quality.append(name+':nonfinite'); value=None
            converted.append(value)
        values[name]=converted[0] if len(converted)==1 else converted
    values['timing_raw_ms']={name:values[name] for name in ('best_ms','last_ms','current_ms')}
    values['packet_id_signed']=struct.unpack_from('<i',data,112)[0]
    for name in ('best_ms','last_ms','current_ms','start_position','start_cars'):
        if values[name] is not None and values[name]<0: values[name]=None
    for name, lo, hi in [('speed',0,200),('rpm',0,30000),('fuel',0,1000),('fuel_capacity',0,1000)]:
        value=values[name]
        if value is not None and not lo<=value<=hi: quality.append(name+':implausible'); values[name]=None
    values['gear']=values['gears'] & 15
    values['suggested_gear']=values['gears']>>4 if values['gears']>>4 !=15 else None
    values['throttle']=values['throttle_raw']/255
    values['brake']=values['brake_raw']/255
    values['speed_kmh']=values['speed']*3.6 if values['speed'] is not None else None
    values['wheel_speed_kmh']=[abs(w*r)*3.6 if w is not None and r is not None and 0.05<r<1 else None for w,r in zip(values['wheel_angular'],values['tyre_radius'])]
    grounded=values['road_distance'] is not None and abs(values['road_distance'])<.25
    straight=values['angular_velocity'][1] is not None and abs(values['angular_velocity'][1])<.15
    values['wheel_speed_ratio']=[w/values['speed_kmh'] if w is not None and values['speed'] is not None and values['speed']>10 and grounded and straight else None for w in values['wheel_speed_kmh']]
    values['raw_nonfinite_fields']=[q for q in quality if ':nonfinite' in q]
    # Preserve original wire bits even when normalized values are invalid.
    values['invalid_wire_hex']=original.hex() if quality else None
    return Sample(values,received_mono,received_utc,variant,provenance,quality,original.hex() if raw else None,wire_length=len(original))

class Sequence:
    """uint32 modular ordering. Backward IDs require 3 increasing candidates to reset."""
    def __init__(self): self.last=None; self.candidate=None; self.run=0; self.counts=dict(duplicates=0,reordered=0,gaps=0,resets=0)
    def accept(self, pid):
        if self.last is None: self.last=pid; return True
        delta=(pid-self.last)&0xffffffff
        if delta==0: self.counts['duplicates']+=1; return False
        if delta>=0x80000000:
            self.counts['reordered']+=1
            self.run=self.run+1 if self.candidate is not None and pid==((self.candidate+1)&0xffffffff) else 1
            self.candidate=pid
            if self.run<3: return False
            self.counts['resets']+=1; self.run=0; self.last=pid; return True
        self.counts['gaps']+=delta-1; self.last=pid; self.run=0; return True

def demo_sample(t:float, index:int) -> Sample:
    lap=int(t/30)+1; phase=(t%30)/30; a=phase*math.tau
    speed=38+18*math.sin(a*3); braking=max(0,-math.cos(a*3))*.8
    b=bytearray(368)
    struct.pack_into('<I',b,0,0x47375330)
    struct.pack_into('<3f',b,4,200*math.cos(a),0,130*math.sin(a))
    struct.pack_into('<3f',b,16,-speed*math.sin(a),0,speed*math.cos(a))
    struct.pack_into('<f',b,60,4000+speed*65)
    struct.pack_into('<3f',b,68,max(0,42-t/30*2.3),100,speed)
    struct.pack_into('<4f',b,96,*[78+5*math.sin(a+j) for j in range(4)])
    struct.pack_into('<Ihhiii',b,112,index,lap,8,30000 if lap>1 else -1,30000 if lap>1 else -1,43200000)
    struct.pack_into('<hhhHBBB',b,136,7000,8000,300,9,0xf0+max(1,int(speed/12)),int((1-braking)*230),int(braking*255))
    struct.pack_into('<4f',b,164,*([-speed/.33]*4)); struct.pack_into('<4f',b,180,*([.33]*4))
    struct.pack_into('<4f',b,196,.1,.11,.1,.11); struct.pack_into('<i',b,292,123)
    struct.pack_into('<f',b,296,.1*math.sin(a)); b[344:348]=b'TTTT' if phase<.88 else b'DDTT'
    struct.pack_into('<i',b,348,int(t%30*1000)); struct.pack_into('<f',b,360,2.7); b[364:368]=b'GR3\0'
    return parse(bytes(b),encrypted=False,mono=t,provenance='demo')
