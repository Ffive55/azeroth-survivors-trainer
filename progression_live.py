"""Permanent unlocks committed by the game thread and saved by the native writer."""
from pathlib import Path
from datetime import datetime
import struct,hashlib,json,time
from engine import ROOT,save_json,log
from talents import GAME_SHA256
from progression_rpc import GameThread
from progression_model import Document,change,selected_state
from save_codec import decode,encode

FIELDS={'open':(0x18,16,32),'items':(0x30,4,8192),'seen':(0x90,32,4096),
        'ach':(0xa8,24,4096),'achat':(0xc0,32,4096)}

def digest(data):return hashlib.sha256(data).hexdigest()

class Progression:
    def __init__(self,trainer):self.trainer=trainer;self.rpc=None
    @property
    def p(self):return self.trainer.p
    def connect(self):
        if not self.p or not self.p.alive():raise RuntimeError('请先连接游戏')
        if self.rpc and self.rpc.p is self.p:
            self.rpc.verify();return
        self.rpc=GameThread(self.p);self.rpc.connect()
    def header(self,address,field):
        offset,stride,limit=FIELDS[field];raw=self.p.read(address+offset,24)
        cap,ptr,n=struct.unpack('<QQQ',raw)
        if not 0<=n<=cap<=limit or ptr<0x10000 and n:raise RuntimeError('永久存档结构校验失败：'+field)
        data=self.p.read(ptr,n*stride) if n else b''
        return raw,data
    def roster(self):
        self.connect();deadline=time.monotonic()+2
        while True:
            address,sequence,driver=struct.unpack('<QQQ',self.p.read(self.rpc.control+0x60,24))
            if address:break
            if time.monotonic()>deadline:raise RuntimeError('等待游戏持久进度初始化，请稍后刷新')
            time.sleep(.02)
        if driver<0x10000 or address!=driver+0x1020:raise RuntimeError('未绑定到游戏真正保存的进度，已停止')
        for field in FIELDS:self.header(address,field)
        return address
    def serialized(self,address):
        out=self.rpc.control+0x1000;self.rpc.call(0x5acbb80,out,address)
        cap,ptr,n=struct.unpack('<QQQ',self.p.read(out,24))
        if not 0<n<=cap<=2_000_000 or ptr<0x10000:raise RuntimeError('游戏未返回有效存档快照')
        data=self.p.read(ptr,n)
        self.rpc.call(0x21d0,ptr,cap,1)
        text=data.decode('utf-8');Document(text)
        return text
    def save_path(self):
        out=self.rpc.control+0x1000;self.rpc.call(0x5ad1b20,out)
        cap,ptr,n=struct.unpack('<QQQ',self.p.read(out,24))
        if not 0<n<=cap<=32768 or ptr<0x10000:raise RuntimeError('无法读取游戏当前存档路径')
        value=self.p.read(ptr,n).decode('utf-8');self.rpc.call(0x21d0,ptr,cap,1)
        path=Path(value).resolve()
        if path.name!='characters.txt' or not path.is_file():raise RuntimeError('游戏存档路径校验失败')
        return path
    def snapshot(self):
        address=self.roster();text=self.serialized(address)
        return {'address':address,'text':text,'state':Document(text).state(),'source':'authoritative_driver'}
    def backup(self,before,path,scope,classes):
        folder=ROOT/'backups'/('unlocks-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        folder.mkdir(parents=True)
        disk=path.read_bytes();decode(disk)
        memory=encode(before)
        if len(memory)>0xfb000:raise RuntimeError('备份快照过大')
        incoming=self.rpc.control+0x4000;out=self.rpc.control+0x1000
        self.p.write(incoming,memory);self.rpc.call(0x5b5d880,out,incoming,len(memory))
        cap,ptr,n=struct.unpack('<QQQ',self.p.read(out,24))
        if cap==0xffffffffffffffff or not 0<n<=cap<=2_000_000:raise RuntimeError('游戏原生解码器未接受解锁前备份')
        native_plain=self.p.read(ptr,n).decode('utf-8');self.rpc.call(0x21d0,ptr,cap,1)
        if native_plain!=before:raise RuntimeError('解锁前备份的原生回读不一致')
        (folder/'characters.txt').write_bytes(memory)
        (folder/'disk-before.txt').write_bytes(disk)
        save_json(folder/'manifest.json',{'game_sha256':GAME_SHA256,'save_path':str(path),
             'scope':scope,'classes':list(classes),'source':'authoritative_driver','memory_save_sha256':digest(memory),
             'disk_before_sha256':digest(disk),'plaintext_sha256':digest(before.encode()),
             'meaning':'characters.txt preserves the current in-memory progress before this unlock; disk-before.txt preserves the original file bytes.'})
        if decode((folder/'characters.txt').read_bytes())!=before:raise RuntimeError('解锁前备份校验失败')
        return folder
    def apply(self,scope,classes=None):
        before=self.snapshot();plan=change(before['text'],scope,classes)
        if not plan['changed']:return {k:v for k,v in plan.items() if k!='text'}|{'backup':None,'saved':True}
        address=before['address'];headers={field:self.header(address,field) for field in plan['fields']}
        data=plan['text'].encode('utf-8')
        if len(data)>0xb0000:raise RuntimeError('存档快照过大，已停止')
        incoming=self.rpc.control+0x4000;parsed=self.rpc.control+0x2000
        self.p.write(incoming,data);self.rpc.call(0x5ac5360,parsed,incoming,len(data))
        normalized=self.serialized(parsed)
        if selected_state(normalized,plan['fields'])!=selected_state(plan['text'],plan['fields']):raise RuntimeError('游戏未接受完整解锁记录，本次未提交')
        changes=[]
        for field in plan['fields']:
            offset,_,_=FIELDS[field];old,old_data=headers[field];new,new_data=self.header(parsed,field)
            changes.append((address+offset,old,new,old_data))
        path=self.save_path();folder=self.backup(before['text'],path,scope,plan['classes'])
        if self.serialized(address)!=before['text']:raise RuntimeError('永久进度在准备期间变化，尚未提交；请刷新后重试')
        self.rpc.commit(address,changes)
        expected=selected_state(plan['text'],plan['fields'])
        try:
            actual=self.serialized(address)
            if selected_state(actual,plan['fields'])!=expected:raise RuntimeError('内存解锁回读不一致')
            saved=decode(path.read_bytes())
            if selected_state(saved,plan['fields'])!=expected:raise RuntimeError('游戏存档保存校验失败')
            # The mutation is limited to the selected progression categories.
            untouched=lambda text:sorted(x for x in text.splitlines() if x.split('|',1)[0] not in plan['fields'])
            if untouched(actual)!=untouched(before['text']):raise RuntimeError('检测到解锁范围外的进度变化')
        except BaseException as error:
            reverse=[]
            for destination,old,new,old_data in changes:
                field=next(k for k,v in FIELDS.items() if address+v[0]==destination)
                current,current_data=self.header(address,field)
                if current!=new:raise RuntimeError(f'解锁验证失败且数据已变化，请使用备份：{folder}') from error
                reverse.append((destination,new,old,current_data))
            self.rpc.commit(address,reverse)
            raise RuntimeError(f'解锁验证失败，已恢复内存并重新保存；备份：{folder}') from error
        result={k:v for k,v in plan.items() if k!='text'}|{'backup':str(folder),'saved':True,'after':Document(actual).state(),
               'save_sha256':digest(path.read_bytes()),'save_path':str(path),'source':'authoritative_driver'}
        save_json(folder/'result.json',result);log('permanent_unlock',scope=scope,classes=plan['classes'],points_added=plan['points_added'],backup=str(folder))
        return result
    def close(self):
        if self.rpc:self.rpc.close();self.rpc=None
