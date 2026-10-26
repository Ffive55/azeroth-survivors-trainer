"""Reversible, version-bound game-thread hooks. No keyboard hooks or remote threads."""
import struct,json,time
from pathlib import Path
from engine import ROOT,backup,save_json,log
from talents import jump
import native_templates_v3 as T

CACHED_KEYS=['health','gold','rerolls','banishes','max_health','damage','cooldown','crit','crit_damage','damage_reduction','regeneration','area','extra_projectiles','echo','speed','pickup','experience','luck','gold_gain','heal_on_kill','shield','extra_lives','buff_power','dot_layers','dot_haste','pet_damage']

def code_bytes(base,control):
    result=bytearray(T.BLOB)
    for offset,kind,addend in T.FIXUPS:struct.pack_into('<Q',result,offset,(base if kind=='base' else control)+addend)
    return bytes(result)

class NativeManager:
    cached_keys=CACHED_KEYS
    def __init__(self,run):self.run=run;self.session=None;self.path=None
    @property
    def p(self):return self.run.p
    def connect(self):
        self.session=None
        self.path=ROOT/'sessions'/f'native-v3-{self.p.pid}-{self.p.started}.json'
        if self.path.exists():
            s=json.loads(self.path.read_text(encoding='utf-8'))
            if any(self.p.read(self.p.base+d['rva'],len(bytes.fromhex(d['original'])))!=bytes.fromhex(d['original']) for d in T.PATCHES.values()):self.session=s;self.verify()
    def verify(self):
        if not self.session or not self.p or not self.p.alive():raise RuntimeError('高级修改未启用或游戏已退出')
        s=self.session
        if (s['pid'],s['started'],s['base'])!=(self.p.pid,self.p.started,self.p.base):raise RuntimeError('高级修改进程身份变化')
        blob=code_bytes(self.p.base,s['control'])
        if self.p.read(s['code'],len(blob))!=blob:raise RuntimeError('高级修改代码校验失败')
        for key,d in T.PATCHES.items():
            original=bytes.fromhex(d['original']);expected=jump(s['code']+T.ENTRIES[key])+b'\x90'*(len(original)-14)
            if self.p.read(self.p.base+d['rva'],len(original))!=expected:raise RuntimeError('高级修改入口校验失败：'+key)
    def enable(self):
        if self.session:self.verify();return
        for d in T.PATCHES.values():
            original=bytes.fromhex(d['original'])
            if self.p.read(self.p.base+d['rva'],len(original))!=original:raise RuntimeError('检测到未知高级修改补丁')
        dest=backup(Path(self.p.path));control=self.p.alloc(4096);code=self.p.alloc(16384)
        self.p.write(control,bytes(4096));self.p.write(code,code_bytes(self.p.base,control));self.p.protect(code,16384,0x20)
        s={'pid':self.p.pid,'started':self.p.started,'base':self.p.base,'control':control,'code':code,'backup':str(dest)};save_json(self.path,s)
        ranges=[(self.p.base+d['rva'],self.p.base+d['rva']+len(bytes.fromhex(d['original']))) for d in T.PATCHES.values()]
        written=[]
        with self.p.paused(ranges):
            try:
                for key,d in T.PATCHES.items():
                    original=bytes.fromhex(d['original']);written.append(d)
                    self.p.write_code(self.p.base+d['rva'],jump(code+T.ENTRIES[key])+b'\x90'*(len(original)-14))
            except BaseException:
                for d in reversed(written):self.p.write_code(self.p.base+d['rva'],bytes.fromhex(d['original']))
                raise
        self.session=s;self.verify();log('enable_native_v3',backup=str(dest))
    def read32(self,offset,kind='I'):return struct.unpack('<'+kind,self.p.read(self.session['control']+offset,4))[0]
    def put32(self,offset,value,kind='I'):self.p.write(self.session['control']+offset,struct.pack('<'+kind,value))
    def bind(self,state,clear=False):
        if not self.session:return
        if clear:self.clear()
        self.p.write(self.session['control'],struct.pack('<QfI',state['address'],state['elapsed'],1))
    def clear(self):
        if not self.session:return
        self.put32(12,0);self.p.write(self.session['control']+16,bytes(44));self.put32(88,0);self.p.write(self.session['control']+0x100,bytes(128));self.p.write(self.session['control']+0x400,bytes(8))
        log('stop_native_overrides')
    def cached(self,key,encoded,enabled):
        if not self.session or key not in CACHED_KEYS:return
        i=CACHED_KEYS.index(key);self.p.write(self.session['control']+0x200+i*4,encoded);self.put32(0x100+i*4,int(enabled))
    def toggle(self,key,enabled):
        self.verify();self.put32({'invulnerable':16,'one_hit':20}[key],int(enabled))
    def setting(self,key,value):
        self.verify()
        if key=='game_speed':self.put32(28,float(value),'f');self.put32(24,int(float(value)!=1))
        elif key=='card_choices':self.put32(36,int(value));self.put32(32,1)
        elif key=='treasure_choices':self.put32(92,int(value));self.put32(88,1)
        elif key=='leech':self.put32(56,float(value)/100,'f');self.put32(52,1)
    def info(self):
        if not self.session:return {'invulnerable':False,'one_hit':False,'game_speed':1.,'leech':None,'card_choices':None,'treasure_choices':None}
        active=[k for i,k in enumerate(CACHED_KEYS) if self.read32(0x100+i*4)]
        return {'invulnerable':bool(self.read32(16)),'one_hit':bool(self.read32(20)),'game_speed':self.read32(28,'f') if self.read32(24) else 1.,'leech':self.read32(56,'f')*100 if self.read32(52) else None,'card_choices':self.read32(36) if self.read32(32) else None,'treasure_choices':self.read32(92) if self.read32(88) else None,'active_cached':active,'thorns':self.read32(0x440,'f')*100 if self.read32(0x400) else None,'controlled_damage':self.read32(0x444,'f')*100 if self.read32(0x404) else None}
    def modifier(self,key,value):
        i=['thorns','controlled_damage'].index(key);self.put32(0x440+i*4,value,'f');self.put32(0x400+i*4,1)
    def stop(self,key):
        if not self.session:return
        if key in CACHED_KEYS:self.put32(0x100+CACHED_KEYS.index(key)*4,0)
        elif key=='leech':self.put32(52,0)
        elif key=='card_choices':self.put32(32,0)
        elif key=='treasure_choices':self.put32(88,0)
        elif key=='game_speed':self.put32(24,0)
        elif key in ('invulnerable','one_hit'):self.toggle(key,False)
        elif key in ('thorns','controlled_damage'):self.put32(0x400+['thorns','controlled_damage'].index(key)*4,0)
    def reserve_mods(self):
        self.verify();self.put32(44,2);self.put32(40,1)
        deadline=time.monotonic()+2
        while self.read32(40) and time.monotonic()<deadline:time.sleep(.01)
        if self.read32(40) or self.read32(44):raise RuntimeError('游戏线程尚未完成属性表准备，请稍后再试')
    def settle_xp(self):self.put32(48,1)
    def counters(self):return dict(zip(['tick','deals','rerolls','banishes','blocked_hits','boosted_hits'],struct.unpack('<6I',self.p.read(self.session['control']+60,24))))
    def disable(self):
        self.verify();self.clear();s=self.session
        ranges=[(self.p.base+d['rva'],self.p.base+d['rva']+len(bytes.fromhex(d['original']))) for d in T.PATCHES.values()]+[(s['code'],s['code']+len(T.BLOB))]
        restored=[]
        with self.p.paused(ranges):
            try:
                for key,d in T.PATCHES.items():
                    restored.append((key,d));self.p.write_code(self.p.base+d['rva'],bytes.fromhex(d['original']))
            except BaseException:
                for key,d in reversed(restored):self.p.write_code(self.p.base+d['rva'],jump(s['code']+T.ENTRIES[key])+b'\x90'*(len(bytes.fromhex(d['original']))-14))
                raise
        self.session=None;log('disable_native_v3')
