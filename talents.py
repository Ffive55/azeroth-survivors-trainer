"""Version-bound talent feature. Keeps native per-talent requirements intact."""
import struct

GAME_VERSION='0.119.0 (77b20bb3)'
GAME_SHA256='6cb443c6ee7bd8c6e08ea9fd22f715f21ef4bd9aab4f58caff83371fdb9e198f'
CLASSES={1:'战士',2:'圣骑士',3:'猎人',4:'潜行者',5:'牧师',7:'萨满',8:'法师',9:'术士',11:'德鲁伊'}
PATCHES=[
    (0x5ac3ed0,bytes.fromhex('488b4168488b497048c1e1034c8d0489')),
    (0x5a87410,bytes.fromhex('5541574156415541545657534881ec38010000')),
]
OFF=0xffffffff
MAX_TOTAL=999

def jump(address): return b'\xff\x25\x00\x00\x00\x00'+struct.pack('<Q',address)

class Asm:
    def __init__(self): self.code=bytearray(); self.labels={}; self.fix=[]
    def emit(self,b): self.code.extend(bytes.fromhex(b) if isinstance(b,str) else b)
    def label(self,n): self.labels[n]=len(self.code)
    def branch(self,op,n): self.emit(op); self.fix.append((len(self.code),n)); self.emit(b'\x00')
    def finish(self):
        for p,n in self.fix:
            d=self.labels[n]-p-1
            if not -128<=d<=127: raise ValueError('branch out of range')
            self.code[p]=d&255
        return bytes(self.code)

def hooks(base,control):
    a=Asm()
    a.emit(b'\x49\xbb'+struct.pack('<Q',control)) # r11 = shared data
    a.emit('49890b') # capture roster pointer
    a.emit('0fb6c2') # eax = class (dl)
    a.emit('41894308') # last observed class
    a.emit('83f80b'); a.branch('77','original')
    a.emit('418b448340') # per-class override
    a.emit('83f8ff'); a.branch('74','original')
    a.emit('c3')
    a.label('original'); a.emit(PATCHES[0][1]); a.emit(jump(base+PATCHES[0][0]+len(PATCHES[0][1])))
    b=Asm(); b.emit('509c') # save rax and flags
    b.emit(b'\x49\xbb'+struct.pack('<Q',control))
    b.emit('410fb6c0'); b.emit('83f80b'); b.branch('77','original')
    b.emit('418b448340'); b.emit('83f8ff'); b.branch('74','original')
    b.emit('4189c1') # normalizer budget r9d
    b.label('original'); b.emit('9d58'); b.emit(PATCHES[1][1]); b.emit(jump(base+PATCHES[1][0]+len(PATCHES[1][1])))
    return [a.finish(),b.finish()]

def earned(xp):
    count=0
    for i in range(51):
        cost=80+15*i
        if xp<cost: break
        xp-=cost; count+=1
    return count

def rank_total(p,cap,arr,n):
    if not 0<=n<=cap<=256: raise RuntimeError('天赋数组校验失败，拒绝写入')
    ranks=p.read(arr,n*16) if n else b''
    points=[]
    for j in range(n):
        desc=struct.unpack_from('<Q',ranks,j*16)[0]; rank=ranks[j*16+8]
        if not p.base<=desc<p.base+0x9000000 or not 1<=rank<=5: raise RuntimeError('天赋等级或描述指针异常')
        points.append(rank)
    return sum(points)

def read_roster(p,control):
    roster=struct.unpack('<Q',p.read(control,8))[0]
    if not roster: raise RuntimeError('请在游戏中切换到其他标签，再打开天赋页以读取角色')
    raw=p.read(roster+0x60,24); capacity,ptr,count=struct.unpack('<QQQ',raw)
    if not 0<count<=capacity<=32 or ptr<0x10000: raise RuntimeError('职业数据校验失败，请重新打开天赋页')
    data=p.read(ptr,count*40); result={}
    for i in range(count):
        item=data[i*40:(i+1)*40]; xp=struct.unpack_from('<I',item)[0]; cls=item[4]
        cap,arr,n=struct.unpack_from('<QQQ',item,8)
        if cls not in CLASSES or cls in result or not 0<=n<=cap<=256: raise RuntimeError('天赋结构校验失败，拒绝写入')
        spent=rank_total(p,cap,arr,n)
        override=struct.unpack('<I',p.read(control+0x40+cls*4,4))[0]
        total=earned(xp) if override==OFF else override
        result[cls]={'class':CLASSES[cls],'xp':xp,'earned':earned(xp),'spent':spent,'max_loadout_spent':spent,'total':total,'available':max(0,total-spent),'override':None if override==OFF else override,'rank_count':n}
    cap,ptr,n=struct.unpack('<QQQ',p.read(roster+0x78,24))
    if not 0<=n<=cap<=32: raise RuntimeError('天赋方案数组校验失败')
    slots=p.read(ptr,n*104) if n else b''
    for i in range(n):
        row=slots[i*104:(i+1)*104]; cls=row[0]
        if cls not in CLASSES or row[1]>2: raise RuntimeError('天赋方案职业或编号异常')
        counts=[rank_total(p,*struct.unpack_from('<QQQ',row,8+j*32)) for j in range(3)]
        if cls in result:
            result[cls]['loadout_spent']=counts
            result[cls]['active_loadout']=row[1]+1
            result[cls]['max_loadout_spent']=max(result[cls]['spent'],*counts)
        elif any(counts): raise RuntimeError('天赋方案缺少职业记录，停止写入')
    return result
