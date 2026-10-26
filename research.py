"""Read-only PE inspection helpers for the installed game."""
from pathlib import Path
import struct, re, bisect, sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

ROOT = Path(__file__).resolve().parent.parent
DATA = (ROOT / 'AzerothSurvivors.exe').read_bytes()
PE = pefile.PE(data=DATA, fast_load=True)
BASE = PE.OPTIONAL_HEADER.ImageBase
MD = Cs(CS_ARCH_X86, CS_MODE_64)
EX = PE.OPTIONAL_HEADER.DATA_DIRECTORY[3]
FUNCS = [(a,b) for a,b,u in struct.iter_unpack('<III', PE.get_data(EX.VirtualAddress,EX.Size))]
STARTS = [a for a,b in FUNCS]

def func(rva):
    i = bisect.bisect_right(STARTS, rva)-1
    return FUNCS[i] if i >= 0 and rva < FUNCS[i][1] else (rva, rva+128)

def dis(rva, end=None):
    a,b = func(rva) if end is None else (rva,end)
    print(f'FUNCTION {a:x}-{b:x}')
    for ins in MD.disasm(PE.get_data(a,b-a), BASE+a):
        print(f'{ins.address-BASE:08x} {ins.bytes.hex():24} {ins.mnemonic:8} {ins.op_str}')

def refs(target, span=1):
    for s in PE.sections:
        if not s.Characteristics & 0x20000000: continue
        chunk = s.get_data()
        for m in re.finditer(rb'[\x48\x4c][\x8d\x8b][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]',chunk):
            p = m.start()
            addr = s.VirtualAddress+p
            dest = addr+7+struct.unpack_from('<i',chunk,p+3)[0]
            if target <= dest < target+span:
                print(f'REF {addr:x} -> {dest:x}; function {func(addr)[0]:x}-{func(addr)[1]:x}')

if __name__ == '__main__':
    if sys.argv[1]=='dis': dis(int(sys.argv[2],16), int(sys.argv[3],16) if len(sys.argv)>3 else None)
    elif sys.argv[1]=='calls':
        target=int(sys.argv[2],16)
        for s in PE.sections:
            if not s.Characteristics & 0x20000000: continue
            chunk=s.get_data()
            for m in re.finditer(b'\xe8',chunk):
                p=m.start()
                if p+5<=len(chunk) and s.VirtualAddress+p+5+struct.unpack_from('<i',chunk,p+1)[0]==target:
                    a=s.VirtualAddress+p; print(f'CALL {a:x}; function {func(a)[0]:x}-{func(a)[1]:x}')
    elif sys.argv[1]=='refs': refs(int(sys.argv[2],16), int(sys.argv[3],0) if len(sys.argv)>3 else 1)
    else:
        term=sys.argv[1].encode(); pos=-1
        while (pos:=DATA.find(term,pos+1))>=0:
            rva=PE.get_rva_from_offset(pos)
            print(f'STR {term!r} file={pos:x} RVA={rva:x}')
            refs(rva,len(term))
