"""Independent Salsa20/20 scalar fixture generator (test-only, not production)."""
import struct,json
from pathlib import Path

def stream(key,nonce,length):
    def rot(v,n):return ((v<<n)|(v>>(32-n)))&0xffffffff
    def quarter(x,a,b,c,d):
        x[b]^=rot((x[a]+x[d])&0xffffffff,7);x[c]^=rot((x[b]+x[a])&0xffffffff,9);x[d]^=rot((x[c]+x[b])&0xffffffff,13);x[a]^=rot((x[d]+x[c])&0xffffffff,18)
    constants=struct.unpack('<4I',b'expand 32-byte k');k=struct.unpack('<8I',key);n=struct.unpack('<2I',nonce);out=bytearray()
    for block in range((length+63)//64):
        state=[constants[0],*k[:4],constants[1],*n,block,0,constants[2],*k[4:],constants[3]];x=state.copy()
        for _ in range(10):
            for q in [(0,4,8,12),(5,9,13,1),(10,14,2,6),(15,3,7,11),(0,1,2,3),(5,6,7,4),(10,11,8,9),(15,12,13,14)]:quarter(x,*q)
        out.extend(struct.pack('<16I',*[(a+b)&0xffffffff for a,b in zip(x,state)]))
    return bytes(out[:length])

def fixtures(packet_id=0xfffffffe):
    out={};key=b'Simulator Interface Packet GT7 ver 0.0'[:32];seed=0x12345678
    for variant,length,xor in [('A',296,0xDEADBEAF),('B',316,0xDEADBEEF),('~',344,0x55FABB4F),('C',368,0xDEADBEEF)]:
        p=bytearray(length);struct.pack_into('<I',p,0,0x47375330);struct.pack_into('<3f',p,4,12.5,-2,42)
        struct.pack_into('<f',p,60,6543);struct.pack_into('<3f',p,68,37.5,100,50);struct.pack_into('<4f',p,96,70,71,72,73)
        struct.pack_into('<Ihhii',p,112,packet_id,4,12,-1,93456);struct.pack_into('<HBBB',p,142,9,0xf4,255,128);struct.pack_into('<i',p,292,999)
        if length>=316:struct.pack_into('<5f',p,296,.2,.3,1,2,3)
        if length>=344:struct.pack_into('<BB',p,316,201,99)
        if length==368:p[344:348]=b'TCDG';struct.pack_into('<iff',p,348,12345,.01,.02)
        nonce=struct.pack('<II',seed^xor,seed);cipher=bytes(a^b for a,b in zip(p,stream(key,nonce,length)));cipher=bytearray(cipher);struct.pack_into('<I',cipher,64,seed)
        out[variant]=bytes(cipher).hex()
    return out
if __name__=='__main__':
    Path('tests/fixtures').mkdir(exist_ok=True);Path('tests/fixtures/packets.json').write_text(json.dumps(fixtures(),indent=2))
