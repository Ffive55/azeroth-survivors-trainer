"""Shared trainer lifecycle: identity, backup, patch transaction, journal, features."""
from pathlib import Path
import hashlib, json, os, struct, sys, time, shutil
from datetime import datetime
from winmem import Process, game_pids
import talents

ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
GAME=ROOT.parent/'AzerothSurvivors.exe'
MAGIC=b'AZS_TRAINER_V1'

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def save_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)

def log(event,**values):
    folder=ROOT/'logs'; folder.mkdir(exist_ok=True)
    with (folder/'events.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'time':datetime.now().isoformat(timespec='seconds'),'event':event,**values},ensure_ascii=False)+'\n')

def backup(game):
    dest=ROOT/'backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    dest.mkdir(parents=True)
    shutil.copy2(game,dest/'AzerothSurvivors.exe')
    source=Path(os.environ['APPDATA'])/'wenilla-rogue'
    if not (source/'characters.txt').is_file(): raise RuntimeError('找不到存档，停止修改')
    shutil.copytree(source,dest/'wenilla-rogue')
    config=game.parent/'benilla-config'
    if config.exists(): shutil.copytree(config,dest/'benilla-config')
    # Require a stable snapshot of the live main save, plus an exact EXE copy.
    if sha(source/'characters.txt')!=sha(dest/'wenilla-rogue'/'characters.txt'): raise RuntimeError('存档正在写入，备份不稳定，请稍后重试')
    if sha(game)!=sha(dest/'AzerothSurvivors.exe'): raise RuntimeError('程序备份校验失败')
    files=[{'path':str(p.relative_to(dest)),'size':p.stat().st_size,'sha256':sha(p)} for p in dest.rglob('*') if p.is_file()]
    save_json(dest/'manifest.json',files)
    log('backup',path=str(dest)); return dest

class Trainer:
    """Feature providers share this transport/session; only talents is enabled in v1."""
    features={'talents':talents}
    def __init__(self): self.p=None; self.session=None; self.session_path=None

    def connect(self):
        if self.p: self.p.close(); self.p=None
        self.session=None; self.session_path=None
        pids=game_pids()
        if len(pids)!=1: raise RuntimeError('请只运行一个 Azeroth Survivors 游戏实例')
        p=Process(pids[0])
        try:
            if Path(p.path).resolve()!=GAME.resolve(): raise RuntimeError('游戏路径不匹配，请将修改器文件夹直接放在 AzerothSurvivors.exe 所在目录中')
            actual_sha=sha(p.path)
            if actual_sha!=talents.GAME_SHA256:
                raise RuntimeError(f'游戏版本不匹配，已停止。此修改器支持 {talents.GAME_VERSION}；当前程序校验 {actual_sha[:12]}。游戏再次更新后需要重新适配修改位置。')
            self.session_path=ROOT/'sessions'/f'{p.pid}-{p.started}.json'
            self.p=p
            if self.session_path.exists():
                state=json.loads(self.session_path.read_text(encoding='utf-8'))
                self.session=state
                if all(p.read(p.base+rva,len(orig))==orig for rva,orig in talents.PATCHES):
                    self.session=None
                else:
                    self.verify(); return self.status(allow_empty=True)
            for rva,original in talents.PATCHES:
                if p.read(p.base+rva,len(original))!=original: raise RuntimeError('检测到未知内存补丁，停止以避免与其他修改器冲突')
            return {'connected':True,'enabled':False,'pid':p.pid,'classes':{}}
        except BaseException:
            p.close(); self.p=None; self.session=None; raise

    def verify(self):
        if not self.p or not self.p.alive(): raise RuntimeError('游戏未连接或已经退出，请重新连接')
        if not self.session: raise RuntimeError('请先启用天赋修改')
        s=self.session
        if s['pid']!=self.p.pid or s['started']!=self.p.started or s['base']!=self.p.base: raise RuntimeError('进程身份变化，拒绝使用旧地址')
        if self.p.read(s['control']+0x100,len(MAGIC))!=MAGIC: raise RuntimeError('修改器数据标记不匹配')
        codes=talents.hooks(self.p.base,s['control'])
        for (rva,orig),address,code in zip(talents.PATCHES,s['code'],codes):
            expected=talents.jump(address)+b'\x90'*(len(orig)-14)
            if self.p.read(self.p.base+rva,len(orig))!=expected or self.p.read(address,len(code))!=code:
                raise RuntimeError('补丁被其他程序更改，停止读写')

    def enable(self):
        if not self.p or not self.p.alive(): raise RuntimeError('请先连接游戏')
        if self.session: self.verify(); return
        dest=backup(Path(self.p.path))
        p=self.p; control=p.alloc(4096); code=p.alloc(4096)
        data=bytearray(4096); data[0x40:0x70]=b'\xff'*48; data[0x100:0x100+len(MAGIC)]=MAGIC
        p.write(control,bytes(data)); codes=talents.hooks(p.base,control); addresses=[code,code+0x200]
        for addr,payload in zip(addresses,codes): p.write(addr,payload)
        p.protect(code,4096,0x20)
        s={'pid':p.pid,'started':p.started,'base':p.base,'control':control,'code':addresses,'backup':str(dest),'status':'preparing','sha256':talents.GAME_SHA256}
        save_json(self.session_path,s)
        written=[]
        try:
            ranges=[(p.base+r,p.base+r+len(o)) for r,o in talents.PATCHES]
            with p.paused(ranges):
                try:
                    for (rva,orig),address in zip(talents.PATCHES,addresses):
                        if p.read(p.base+rva,len(orig))!=orig: raise RuntimeError('原始指令校验失败')
                        written.append((rva,orig))
                        p.write_code(p.base+rva,talents.jump(address)+b'\x90'*(len(orig)-14))
                except BaseException:
                    for rva,orig in reversed(written): p.write_code(p.base+rva,orig)
                    raise
            self.session=s; s['status']='active'; save_json(self.session_path,s)
            self.verify(); log('enable',pid=p.pid,backup=str(dest))
        except BaseException:
            # The pre-write journal remains recoverable if an I/O failure occurs after patching.
            log('enable_error',pid=p.pid); raise

    def status(self,allow_empty=False):
        if not self.session: return {'connected':bool(self.p and self.p.alive()),'enabled':False,'classes':{}}
        self.verify()
        try:
            with self.p.paused(): classes=talents.read_roster(self.p,self.session['control'])
        except RuntimeError as e:
            if not allow_empty: raise
            return {'connected':True,'enabled':True,'pid':self.p.pid,'classes':{},'hint':str(e),'backup':self.session['backup']}
        return {'connected':True,'enabled':True,'pid':self.p.pid,'classes':classes,'backup':self.session['backup']}

    def set_available(self,cls,value):
        if cls not in talents.CLASSES or isinstance(value,bool) or not isinstance(value,int) or value<0: raise ValueError('请输入非负整数')
        self.verify()
        with self.p.paused():
            before=talents.read_roster(self.p,self.session['control'])
            if cls not in before: raise RuntimeError('该职业尚未读取，请先在游戏中打开该职业天赋页')
            total=before[cls]['spent']+value
            if total>talents.MAX_TOTAL: raise ValueError(f'已分配加可用点数不能超过 {talents.MAX_TOTAL}')
            if total<before[cls]['max_loadout_spent']: raise ValueError('其他天赋方案已投入更多点数，请先退点；降低预算可能清掉该方案')
            self.p.write(self.session['control']+0x40+cls*4,struct.pack('<I',total))
            after=talents.read_roster(self.p,self.session['control'])[cls]
        log('set_available',class_id=cls,before=before[cls],after=after)
        return after

    def restore_class(self,cls):
        self.verify()
        with self.p.paused():
            state=talents.read_roster(self.p,self.session['control'])[cls]
            if state['max_loadout_spent']>state['earned']: raise RuntimeError(f"该职业有方案已用 {state['max_loadout_spent']} 点，原生预算 {state['earned']} 点；请先在游戏中退回多余天赋，再恢复")
            self.p.write(self.session['control']+0x40+cls*4,struct.pack('<I',talents.OFF))
        log('restore_class',class_id=cls)

    def disable(self):
        self.verify(); p=self.p
        ranges=[(p.base+r,p.base+r+len(o)) for r,o in talents.PATCHES]+[(x,x+0x200) for x in self.session['code']]
        with p.paused(ranges):
            # With no overrides, disable is safe even before the first roster observation.
            values=struct.unpack('<12I',p.read(self.session['control']+0x40,48))
            if any(x!=talents.OFF for x in values):
                states=talents.read_roster(p,self.session['control'])
                if any(x['max_loadout_spent']>x['earned'] for x in states.values()): raise RuntimeError('有职业的天赋方案已投入超过原生预算的点数，请先退回多余天赋；暂不撤销补丁')
            self.verify()
            restored=[]
            try:
                for (rva,original),address in zip(talents.PATCHES,self.session['code']):
                    restored.append((rva,original,address)); p.write_code(p.base+rva,original)
            except BaseException:
                for rva,original,address in reversed(restored): p.write_code(p.base+rva,talents.jump(address)+b'\x90'*(len(original)-14))
                raise
        self.session['status']='disabled'; save_json(self.session_path,self.session)
        # Do not free trampolines while suspended call stacks might still reference them.
        # Only 8 KiB per enable cycle; Windows reclaims them on process exit.
        log('disable',pid=p.pid); self.session=None

    def close(self):
        if self.p: self.p.close(); self.p=None

def restore_save(folder):
    if game_pids(): raise RuntimeError('恢复存档前必须退出游戏，防止游戏覆盖恢复结果')
    folder=Path(folder).resolve(); root=(ROOT/'backups').resolve()
    if not folder.is_relative_to(root): raise RuntimeError('只能恢复本修改器 backups 文件夹内的备份')
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8-sig'))
    src=folder/'wenilla-rogue'/'characters.txt'
    record=next(x for x in manifest if x.get('path',x.get('Path','')).replace('\\','/')=='wenilla-rogue/characters.txt')
    if sha(src).lower()!=record.get('sha256',record.get('SHA256')).lower(): raise RuntimeError('备份存档校验失败')
    target=Path(os.environ['APPDATA'])/'wenilla-rogue'/'characters.txt'
    safety=ROOT/'backups'/('before-restore-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    safety.mkdir(parents=True); shutil.copy2(target,safety/'characters.txt')
    temp=target.with_suffix('.trainer.tmp'); shutil.copy2(src,temp); os.replace(temp,target)
    log('restore_save',source=str(src),preserved_current=str(safety))
