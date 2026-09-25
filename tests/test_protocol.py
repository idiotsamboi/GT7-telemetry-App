import json,struct,math
from pathlib import Path
import pytest
from backend.app.telemetry import parse,Sequence,demo_sample
from tests.fixture_generator import stream

@pytest.mark.parametrize('variant,length',[('A',296),('B',316),('~',344),('C',368)])
def test_independent_encrypted_fixtures(variant,length):
    fixtures=json.loads(Path('tests/fixtures/packets.json').read_text());data=bytes.fromhex(fixtures[variant]);assert len(data)==length
    s=parse(data);v=s.values
    assert s.variant==variant and v['speed_kmh']==180 and v['rpm']==6543
    assert v['packet_id']==0xfffffffe and v['best_ms'] is None and v['last_ms']==93456
    assert v['gear']==4 and v['suggested_gear'] is None and v['position']==[12.5,-2,42]
    assert v['current_ms']==(12345 if variant=='C' else None)
    assert v['steering_rotation']==(pytest.approx(.2) if variant!='A' else None)
    assert v['surface']==('TCDG' if variant=='C' else None)

def test_independent_salsa_known_zero_vector():
    assert stream(bytes(32),bytes(8),64).hex()=='9a97f65b9b4c721b960a672145fca8d4e32e67f9111ea979ce9c4826806aeee63de9c0da2bd7f91ebcb2639bf989c6251b29bf38d39a9bdce7c55f4b2ac12a39'

@pytest.mark.parametrize('size',[0,1,64,295,297,315,343,367,369,4096])
def test_bad_lengths(size):
    with pytest.raises(ValueError):parse(bytes(size))

def test_magic_and_finite():
    with pytest.raises(ValueError):parse(bytes(296))
    b=bytearray(296);struct.pack_into('<I',b,0,0x47375330);struct.pack_into('<f',b,76,float('nan'))
    s=parse(bytes(b),encrypted=False);assert s.values['speed'] is None and 'speed:nonfinite' in s.quality

def test_sequence():
    s=Sequence()
    assert s.accept(0xfffffffe) and s.accept(0xffffffff) and s.accept(0)
    assert not s.accept(0)
    assert s.accept(3) and s.counts['gaps']==2
    assert not s.accept(2)
    assert s.accept(4)
    assert not s.accept(0) and not s.accept(1) and s.accept(2)
    assert s.counts['resets']==1

def test_short_packet_extension_reset():
    f=json.loads(Path('tests/fixtures/packets.json').read_text());assert parse(bytes.fromhex(f['C'])).values['surface']
    assert parse(bytes.fromhex(f['A'])).values['surface'] is None

def test_pinned_header_layout_independent_sequential_offsets():
    # Derive packed offsets from upstream declarations, not production offsets.
    import re
    text=Path('vendor/gt7-udp/GT7UDPParser.h').read_text()
    sizes={'int32_t':4,'int16_t':2,'uint8_t':1,'float':4,'char':1,'SimulatorFlags':2}
    expected={'PacketA':296,'PacketB':316,'PacketTilda':344,'PacketC':368};ends={};offsets={}
    for name,parent,body in re.findall(r'struct (PacketA|PacketB|PacketTilda|PacketC)(?:\s*:\s*public\s+(\w+))?\s*\{(.*?)\};',text,re.S):
        cursor=ends.get(parent,0)
        for dtype,field,count in re.findall(r'^\s*(int32_t|int16_t|uint8_t|float|char|SimulatorFlags)\s+(\w+)(?:\[(\d+)\])?\s*;',body,re.M):
            offsets[field]=cursor;cursor+=sizes[dtype]*int(count or 1)
        ends[name]=cursor
    assert ends==expected
    from backend.app.telemetry import FIELDS
    names={
        'position':'position','velocity':'worldVelocity','rotation':'rotation','north':'orientationRelativeToNorth','angular_velocity':'angularVelocity','body_height':'bodyHeight','rpm':'EngineRPM','fuel':'fuelLevel','fuel_capacity':'fuelCapacity','speed':'speed','boost':'boost','oil_pressure':'oilPressure','water_temp':'waterTemp','oil_temp':'oilTemp','tyres':'tyreTemp','packet_id':'packetId','lap':'lapCount','total_laps':'totalLaps','best_ms':'bestLaptime','last_ms':'lastLaptime','day_ms':'dayProgression','start_position':'RaceStartPosition','start_cars':'preRaceNumCars','rpm_min':'minAlertRPM','rpm_max':'maxAlertRPM','transmission_max':'calcMaxSpeed','flags':'flags','gears':'gears','throttle_raw':'throttle','brake_raw':'brake','road_plane':'roadPlane','road_distance':'roadPlaneDistance','wheel_angular':'wheelRPS','tyre_radius':'tyreRadius','suspension':'suspHeight','unknown_a':'UNKNOWNFLOATS','clutch':'clutch','clutch_engagement':'clutchEngagement','gearbox_rpm':'RPMFromClutchToGearbox','transmission_ratio':'transmissionTopSpeed','gear_ratios':'gearRatios','car_id':'carCode','steering_rotation':'wheelRotation','steering_velocity':'steeringAngularVelocity','acceleration_raw':'sway','throttle_filtered':'throttleFiltered','brake_filtered':'brakeFiltered','unknown_t_bytes':'UNKNOWNUINT81','torque_vectors':'torqueVectors','energy_recovery':'energyRecovery','unknown_t':'UNKNOWNFLOAT11','surface':'surfaceType','current_ms':'currentLap','wheel_steering':'wheelSteeringAngle','wheelbase':'wheelBase','category':'carCategory'}
    for name,offset,*_ in FIELDS:assert offset==offsets[names[name]],name

@pytest.mark.parametrize('data',[None,'packet',123,[0]*296])
def test_invalid_input_has_classified_error(data):
    from backend.app.telemetry import PacketError
    with pytest.raises(PacketError) as err:parse(data)
    assert err.value.code=='invalid_input'

def test_crypto_failure_classified_and_byteslike_supported():
    from backend.app.telemetry import PacketError,decrypt_datagram
    f=json.loads(Path('tests/fixtures/packets.json').read_text())
    assert parse(memoryview(bytes.fromhex(f['A']))).values['rpm']==6543
    with pytest.raises(PacketError) as e:decrypt_datagram(bytes(368))
    assert e.value.code=='bad_magic' and e.value.variant=='C'

def test_nonfinite_all_float_offsets_is_json_safe():
    from backend.app.telemetry import FIELDS,MAGIC
    b=bytearray(368);struct.pack_into('<I',b,0,MAGIC)
    for name,offset,fmt,*_ in FIELDS:
        if fmt.endswith('f'):struct.pack_into('<'+fmt,b,offset,*([float('nan')]*int(fmt[:-1] or 1)))
    s=parse(b,encrypted=False);json.dumps(s.json(),allow_nan=False)
    assert s.values['speed_kmh'] is None and s.values['wheel_speed_ratio']==[None]*4
    assert s.values['invalid_wire_hex']==bytes(b).hex()

def test_signed_raw_timing_and_packet_id_preserved():
    f=json.loads(Path('tests/fixtures/packets.json').read_text());s=parse(bytes.fromhex(f['A']))
    assert s.values['packet_id_signed']==-2 and s.values['timing_raw_ms']['best_ms']==-1 and s.values['best_ms'] is None
    assert s.parser_version=='1.1' and s.wire_length==296

def test_random_datagrams_never_yield_nonfinite_json():
    import random
    rng=random.Random(42)
    for i in range(300):
        data=rng.randbytes(rng.choice([296,316,344,368,1,20,1000]))
        with pytest.raises(ValueError):parse(data)
