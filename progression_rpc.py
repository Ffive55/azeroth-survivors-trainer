"""Version-bound commands execute on the authoritative game driver thread."""
import struct,time,json,threading
from pathlib import Path
from engine import ROOT,save_json,sha
from talents import GAME_SHA256,jump
import progression_template as T

HOOK_RVA=0x5afd390
ORIGINAL=bytes.fromhex('5541574156415541545657534881ec580d0000')
MAGIC=b'AZS_PROGRESS_V331'
FUNCTIONS={0x5ad1b20,0x5acbb80,0x5ac5360,0x5aca5f0,0x5b5d880,0x21d0}

def code_bytes(control,original):
    b=bytearray(T.BLOB)
    for offset,kind in T.FIXUPS:struct.pack_into('<Q',b,offset,control if kind=='control' else original)
    return bytes(b)

class GameThread:
    def __init__(self,p):self.p=p;self.session=None;self.path=ROOT/'sessions'/f'progression-{p.pid}-{p.started}.json';self.lock=threading.RLock()
    def connect(self):
        if sha(self.p.path)!=GAME_SHA256:raise RuntimeError('永久解锁不支持当前游戏版本')
        if self.path.exists():
            s=json.loads(self.path.read_text(encoding='utf-8'))
            if s.get('kind')=='driver-v331' and self.p.read(self.p.base+HOOK_RVA,len(ORIGINAL))==jump(s['code'])+b'\x90'*(len(ORIGINAL)-14):self.session=s;self.verify();return
        if self.p.read(self.p.base+HOOK_RVA,len(ORIGINAL))!=ORIGINAL:raise RuntimeError('游戏持久进度驱动入口不匹配')
        original=self.p.base+HOOK_RVA+len(ORIGINAL)
        control=self.p.alloc(0x100000);code=self.p.alloc(4096)
        self.p.write(control,bytes(0x3000));self.p.write(control+0x80,MAGIC)
        payload=code_bytes(control,original);self.p.write(code,payload);self.p.protect(code,4096,0x20)
        s={'pid':self.p.pid,'started':self.p.started,'base':self.p.base,'original':original,'control':control,'code':code,'kind':'driver-v331'}
        save_json(self.path,s)
        with self.p.paused([(self.p.base+HOOK_RVA,self.p.base+HOOK_RVA+len(ORIGINAL))]):
            if self.p.read(self.p.base+HOOK_RVA,len(ORIGINAL))!=ORIGINAL:raise RuntimeError('游戏驱动入口已变化')
            try:self.p.write_code(self.p.base+HOOK_RVA,jump(code)+b'\x90'*(len(ORIGINAL)-14))
            except BaseException:self.p.write_code(self.p.base+HOOK_RVA,ORIGINAL);raise
        self.session=s;self.verify()
    @property
    def control(self):return self.session['control']
    def verify(self):
        s=self.session
        if not self.p.alive() or (self.p.pid,self.p.started,self.p.base)!=(s['pid'],s['started'],s['base']):raise RuntimeError('解锁进程身份已变化')
        if self.p.read(self.p.base+HOOK_RVA,len(ORIGINAL))!=jump(s['code'])+b'\x90'*(len(ORIGINAL)-14) or self.p.read(s['control']+0x80,len(MAGIC))!=MAGIC or self.p.read(s['code'],len(T.BLOB))!=code_bytes(s['control'],s['original']):raise RuntimeError('解锁支持校验失败')
    def dispatch(self,mode=0):
        self.verify();c=self.control
        status=struct.unpack('<I',self.p.read(c,4))[0]
        if status in (1,2):raise RuntimeError('游戏仍在执行上一条解锁指令，请稍后重试')
        self.p.write(c+0x48,struct.pack('<I',mode));self.p.write(c,struct.pack('<I',1))
        deadline=time.monotonic()+8
        while True:
            state=struct.unpack('<I',self.p.read(c,4))[0]
            if state==3:break
            if time.monotonic()>deadline:
                # Cancel only a command that has not started. Never overwrite in-flight data.
                with self.p.paused():
                    state=struct.unpack('<I',self.p.read(c,4))[0]
                    if state==1:self.p.write(c,bytes(4))
                raise RuntimeError('等待游戏线程超时；请等待游戏驱动恢复后重试' if state!=2 else '游戏仍在执行，请等待后刷新，勿重复提交')
            time.sleep(.01)
        if struct.unpack('<I',self.p.read(c+0x40,4))[0]:raise RuntimeError('游戏数据已变化，本次未提交，请刷新后重试')
        return struct.unpack('<Q',self.p.read(c+0x38,8))[0]
    def call(self,rva,rcx=0,rdx=0,r8=0,r9=0):
        if rva not in FUNCTIONS:raise ValueError('Unknown progression function')
        with self.lock:
            self.idle();self.p.write(self.control+0x10,struct.pack('<5Q',self.p.base+rva,rcx,rdx,r8,r9));return self.dispatch()
    def idle(self):
        self.verify()
        if struct.unpack('<I',self.p.read(self.control,4))[0] in (1,2):raise RuntimeError('游戏仍在执行上一条解锁指令，请稍后刷新')
    def commit(self,roster,changes):
        with self.lock:return self._commit(roster,changes)
    def _commit(self,roster,changes):
        self.idle()
        if not 1<=len(changes)<=8:raise ValueError('Invalid progression transaction')
        raw=bytearray();snapshot=self.control+0x10000
        for address,old,new,old_data in changes:
            if len(old)!=24 or len(new)!=24:raise ValueError('Invalid Vec header')
            if len(old_data)>0x10000:raise ValueError('Progression snapshot too large')
            self.p.write(snapshot,old_data)
            raw.extend(struct.pack('<Q',address)+old+new+struct.pack('<QQQ',snapshot,len(old_data),0));snapshot+=len(old_data)
        self.p.write(self.control+0x200,bytes(raw));self.p.write(self.control+0x4c,struct.pack('<I',len(changes)));self.p.write(self.control+0x50,struct.pack('<QQ',roster,self.p.base+0x5aca5f0));self.dispatch(1)
    def close(self):
        if not self.session or not self.p.alive():return
        self.verify();s=self.session
        if struct.unpack('<I',self.p.read(s['control'],4))[0] in (1,2):raise RuntimeError('解锁指令尚未结束')
        with self.p.paused([(s['code'],s['code']+4096),(self.p.base+HOOK_RVA,self.p.base+HOOK_RVA+len(ORIGINAL))]):
            try:self.p.write_code(self.p.base+HOOK_RVA,ORIGINAL)
            except BaseException:self.p.write_code(self.p.base+HOOK_RVA,jump(s['code'])+b'\x90'*(len(ORIGINAL)-14));raise
        self.session=None
