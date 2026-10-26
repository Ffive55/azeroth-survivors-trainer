"""Live run access. Addresses are bound to the verified local executable build."""
from dataclasses import dataclass
from pathlib import Path
import struct, math, time
from engine import ROOT, backup, save_json, log
from talents import jump, GAME_SHA256, CLASSES

CAPTURE_RVA=0x5c5c300
CAPTURE_ORIGINAL=bytes.fromhex('5541574156415541545657534881ecf8010000')
CAPTURE_MAGIC=b'AZS_RUN_CAPTURE_V2'
UI_RVA=0x114320
UI_ORIGINAL=bytes.fromhex('5541574156415541545657534881ec78050000')

def ui_capture_code(base,control):
    return bytes.fromhex('50415248b8')+struct.pack('<Q',control)+bytes.fromhex('4d8b104c8950104d8b114c895018415a58')+UI_ORIGINAL+jump(base+UI_RVA+len(UI_ORIGINAL))

@dataclass(frozen=True)
class Feature:
    key:str
    label:str
    offset:int
    kind:str='f'
    minimum:float=0
    maximum:float=10000
    scale:float=1
    default:str='100'
    unit:str=''
    hint:str='应用一次；开启左侧开关可持续保持此值。'
    bias:float=0
    mod_tag:int|None=None
    def decode(self,data): return struct.unpack_from('<'+self.kind,data,self.offset)[0]*self.scale+self.bias
    def encode(self,value):
        if isinstance(value,bool):raise ValueError(f'{self.label}请输入数字')
        try:v=float(value)
        except (ValueError,TypeError):raise ValueError(f'{self.label}请输入数字')
        if not math.isfinite(v) or not self.minimum<=v<=self.maximum:raise ValueError(f'{self.label}范围为 {self.minimum:g} 至 {self.maximum:g}')
        if self.kind=='I' and not v.is_integer():raise ValueError(f'{self.label}必须是整数')
        raw=(v-self.bias)/self.scale
        return struct.pack('<'+self.kind,int(raw) if self.kind=='I' else raw)

FEATURE_LIST=[
    Feature('health','当前血量',0x508,minimum=1,maximum=1000000,default='500',hint='设置当前生命，不能高于最大生命。保持开关按设定值补回生命，不提供致死伤害免疫。'),
    Feature('gold','本局金币',0x510,'I',0,10000000,default='9999'),
    Feature('rerolls','抽卡重抽次数',0x568,'I',0,9999,default='99',unit='次',hint='修改剩余免费重抽次数。锁定后重抽不减次数，且不会额外重发当前手牌。付费重抽价格按游戏原规则计算。'),
    Feature('banishes','抽卡放逐次数',0xc58,'I',0,9999,default='99',unit='次'),
    Feature('max_health','最大生命',0x4a0,minimum=1,maximum=1000000,default='1000',hint='修改本局实际最大生命；降低时会同时把当前生命限制在新上限以内。'),
    Feature('damage','伤害倍率',0x4a4,minimum=.1,maximum=100,default='3',unit='×'),
    Feature('cooldown','冷却时间倍率',0x4a8,minimum=.05,maximum=10,default='.5',unit='×',hint='越小越快。0.5 表示冷却时间为原来的约一半。'),
    Feature('crit','暴击率',0x4ac,maximum=100,scale=100,default='80',unit='%'),
    Feature('crit_damage','暴击伤害倍率',0x4b0,minimum=1,maximum=20,default='3',unit='×'),
    Feature('damage_reduction','伤害减免',0x4c0,maximum=95,scale=100,default='75',unit='%'),
    Feature('regeneration','每秒回血',0x4c4,maximum=10000,default='50'),
    Feature('area','效果范围倍率',0x4c8,minimum=.1,maximum=10,default='2',unit='×'),
    Feature('extra_projectiles','额外投射物',0x4d4,'I',0,3,default='3',unit='个'),
    Feature('echo','重复施法概率',0x4d8,maximum=100,scale=100,default='75',unit='%'),
    Feature('speed','移动速度倍率',0x4b4,minimum=.1,maximum=5,default='1.8',unit='×'),
    Feature('pickup','拾取半径',0x4b8,minimum=.5,maximum=100,default='30',unit='码'),
    Feature('experience','经验获取倍率',0x4bc,minimum=.1,maximum=20,default='3',unit='×'),
    Feature('luck','幸运加成',0x4cc,maximum=1000,scale=100,default='100',unit='%',hint='应用后会在属性重算和发牌前保持设定值，升级首轮即生效。关闭开关或还原后停止覆盖；提高稀有度概率，不保证所有卡均为传说。'),
    Feature('gold_gain','金币获取倍率',0x4d0,minimum=.1,maximum=100,default='3',unit='×'),
    Feature('heal_on_kill','击杀回血',0x4dc,maximum=10000,default='10'),
    Feature('shield','护盾值',0x50c,maximum=1000000,default='1000'),
    Feature('extra_lives','生命数',0x564,'I',0,99,default='9',unit='次'),
    Feature('buff_power','增益强度',0x4e0,maximum=1000,scale=100,default='100',unit='%'),
    Feature('dot_layers','持续伤害层数',0x4e4,'I',1,4,default='4',unit='层',bias=1),
    Feature('dot_haste','持续伤害急速',0x4e8,maximum=1000,scale=100,default='100',unit='%'),
    Feature('pet_damage','宠物伤害倍率',0x4ec,minimum=.1,maximum=100,default='3',unit='×'),
    Feature('current_experience','当前经验',0x504,'I',0,10000000,default='1000',hint='设置本级经验；战斗时由游戏线程结算升级，抽卡或暂停时在恢复战斗后结算。'),
    Feature('card_choices','升级可选卡数量',None,'I',1,6,default='6',unit='张',hint='指定升级发牌和升级重抽的候选数量。与宝藏独立设置；候选池不足时按实际可选项，不会自动重抽当前手牌。'),
    Feature('treasure_choices','宝藏可选卡数量',None,'I',1,6,default='6',unit='张',hint='指定守护者宝藏、宝箱珠宝发牌及对应重抽的候选数量，与升级抽卡独立。下一次对应发牌时生效，候选池不足时按游戏原规则处理。'),
    Feature('leech','生命偷取',None,maximum=100,scale=100,default='20',unit='%',hint='在实际生命偷取计算处应用。未覆盖时显示 —；应用后生效直到还原。'),
    Feature('thorns','荆棘反伤',None,maximum=1000,scale=100,default='100',unit='%',mod_tag=0x16),
    Feature('controlled_damage','对受控敌人伤害',None,maximum=1000,scale=100,default='100',unit='%',mod_tag=0x12),
    Feature('invulnerable','无敌：受击不掉血',None,'I',0,1,default='1',hint='在玩家受伤入口阻止扣血和扣盾，关闭即恢复原生受伤流程。'),
    Feature('one_hit','一击必杀',None,'I',0,1,default='1',hint='仅在实际命中敌人时放大伤害，不会自动杀死尚未受攻击的敌人。'),
    Feature('game_speed','游戏速度',None,minimum=.1,maximum=10,default='2',unit='×',hint='修改游戏模拟时间步长。1 为原速；计时、移动与技能同步，音频和窗口动画保持原速。'),
]
FEATURES={f.key:f for f in FEATURE_LIST}
PHASES={0:'准备中',1:'战斗中',2:'抽卡中',3:'暂停中',4:'已阵亡',5:'胜利'}

def capture_code(base,control):
    return b'\x50\x48\xb8'+struct.pack('<Q',control)+b'\x48\x89\x10\x48\xff\x40\x08\x58'+CAPTURE_ORIGINAL+jump(base+CAPTURE_RVA+len(CAPTURE_ORIGINAL))

class RunAccess:
    def __init__(self,trainer):
        self.trainer=trainer; self.session=None; self.path=None
        self.holds={};self.originals={};self.last_identity=None;self.last_elapsed=None
        self.native=None
    @property
    def p(self): return self.trainer.p
    def connect(self):
        self.session=None
        self.holds.clear();self.originals.clear();self.last_identity=None;self.last_elapsed=None
        if not self.p or not self.p.alive(): raise RuntimeError('请先连接游戏')
        self.path=ROOT/'sessions'/f'run-{self.p.pid}-{self.p.started}.json'
        if self.path.exists():
            import json
            s=json.loads(self.path.read_text(encoding='utf-8'))
            if self.p.read(self.p.base+CAPTURE_RVA,len(CAPTURE_ORIGINAL))!=CAPTURE_ORIGINAL:
                self.session=s; self.verify()
        from native_v3 import NativeManager
        self.native=NativeManager(self);self.native.connect()
    def verify(self):
        if not self.p or not self.p.alive() or not self.session: raise RuntimeError('请先启用对局修改')
        s=self.session
        if (s['pid'],s['started'],s['base'])!=(self.p.pid,self.p.started,self.p.base): raise RuntimeError('对局进程身份已改变，请重新连接')
        expected=jump(s['code'])+b'\x90'*(len(CAPTURE_ORIGINAL)-14)
        if self.p.read(self.p.base+CAPTURE_RVA,len(expected))!=expected: raise RuntimeError('对局读取补丁校验失败')
        if self.p.read(s['control']+32,len(CAPTURE_MAGIC))!=CAPTURE_MAGIC or self.p.read(s['code'],len(capture_code(self.p.base,s['control'])))!=capture_code(self.p.base,s['control']): raise RuntimeError('对局读取会话校验失败')
        if s.get('ui_code'):
            expected=jump(s['ui_code'])+b'\x90'*(len(UI_ORIGINAL)-14)
            if self.p.read(self.p.base+UI_RVA,len(expected))!=expected or self.p.read(s['ui_code'],len(ui_capture_code(self.p.base,s['control'])))!=ui_capture_code(self.p.base,s['control']):raise RuntimeError('抽卡界面读取补丁校验失败')
        if self.native and self.native.session:self.native.verify()
    def enable_ui_refresh(self):
        self.verify()
        if self.session.get('ui_code'):return
        if self.p.read(self.p.base+UI_RVA,len(UI_ORIGINAL))!=UI_ORIGINAL:raise RuntimeError('抽卡界面原指令不匹配')
        addr=self.p.alloc(4096);self.p.write(addr,ui_capture_code(self.p.base,self.session['control']));self.p.protect(addr,4096,0x20)
        self.session['ui_code']=addr;save_json(self.path,self.session)
        with self.p.paused([(self.p.base+UI_RVA,self.p.base+UI_RVA+len(UI_ORIGINAL))]):
            try:self.p.write_code(self.p.base+UI_RVA,jump(addr)+b'\x90'*(len(UI_ORIGINAL)-14))
            except BaseException:self.p.write_code(self.p.base+UI_RVA,UI_ORIGINAL);self.session.pop('ui_code',None);save_json(self.path,self.session);raise
    def enable(self):
        if self.session:self.verify();self.enable_ui_refresh();return
        if not self.p or not self.p.alive(): raise RuntimeError('请先连接游戏')
        if self.p.read(self.p.base+CAPTURE_RVA,len(CAPTURE_ORIGINAL))!=CAPTURE_ORIGINAL: raise RuntimeError('发现未知对局补丁，停止启用')
        dest=backup(Path(self.p.path)); control=self.p.alloc(4096); code=self.p.alloc(4096)
        payload=bytearray(64);payload[32:32+len(CAPTURE_MAGIC)]=CAPTURE_MAGIC
        self.p.write(control,bytes(payload)); self.p.write(code,capture_code(self.p.base,control)); self.p.protect(code,4096,0x20)
        s={'pid':self.p.pid,'started':self.p.started,'base':self.p.base,'code':code,'control':control,'backup':str(dest),'sha256':GAME_SHA256}
        save_json(self.path,s)
        with self.p.paused([(self.p.base+CAPTURE_RVA,self.p.base+CAPTURE_RVA+len(CAPTURE_ORIGINAL))]):
            try:self.p.write_code(self.p.base+CAPTURE_RVA,jump(code)+b'\x90'*(len(CAPTURE_ORIGINAL)-14))
            except BaseException:self.p.write_code(self.p.base+CAPTURE_RVA,CAPTURE_ORIGINAL);raise
        self.session=s;self.verify();self.enable_ui_refresh();log('enable_run_access',backup=str(dest))
    def enable_native(self):
        if self.native is None:
            from native_v3 import NativeManager
            self.native=NativeManager(self);self.native.connect()
        self.native.enable()
        state=self.snapshot();self.native.bind(state)
    def raw(self):
        self.verify(); address,sequence=struct.unpack('<QQ',self.p.read(self.session['control'],16))
        if not address:raise RuntimeError('等待游戏更新对局信息')
        data=self.p.read(address,0xc90)
        return address,sequence,data
    def snapshot(self):
        address,sequence,data=self.raw()
        elapsed=struct.unpack_from('<f',data,0xbdc)[0];level=struct.unpack_from('<I',data,0x500)[0]
        cls=data[0x33c];phase=data[0xc8a];maximum=struct.unpack_from('<f',data,0x4a0)[0]
        if cls not in CLASSES or phase not in PHASES or not math.isfinite(elapsed) or not 0<=elapsed<100000 or not 1<=level<=10000 or not math.isfinite(maximum) or not 1<=maximum<=10000000:
            self.holds.clear();raise RuntimeError('未读取到有效对局，进入战斗后再试')
        identity=(address,cls,struct.unpack_from('<Q',data,0x488)[0],data[0x2b8:0x2c8].hex())
        changed=(self.last_identity is not None and identity!=self.last_identity) or (self.last_elapsed is not None and elapsed<self.last_elapsed-.1) or phase==0
        if self.last_identity is None and self.native and self.native.session:
            old_address,old_elapsed=struct.unpack('<Qf',self.p.read(self.native.session['control'],12))
            changed=changed or old_address not in (0,address) or elapsed<old_elapsed-.1
        if changed:
            self.holds.clear();self.originals.clear()
            if self.native and self.native.session:self.native.clear()
        self.last_identity=identity;self.last_elapsed=elapsed
        values={key:f.decode(data) for key,f in FEATURES.items() if f.offset is not None}
        native=self.native.info() if self.native else {'invulnerable':False,'one_hit':False,'game_speed':1.,'leech':None,'card_choices':None}
        for key in ['invulnerable','one_hit','game_speed','leech']:values[key]=native[key]
        hand_kind=data[0xc88]
        values['card_choices']=struct.unpack_from('<Q',data,0x680)[0] if phase==2 and hand_kind==0 else native.get('card_choices')
        values['treasure_choices']=struct.unpack_from('<Q',data,0x680)[0] if phase==2 and hand_kind!=0 else native.get('treasure_choices')
        for key,f in FEATURES.items():
            if f.mod_tag is not None:values[key]=self.mod_sum(address,f.mod_tag)*f.scale
        if any(v is not None and not math.isfinite(v) for v in values.values()):self.holds.clear();raise RuntimeError('对局属性包含无效值，已停止保持')
        remote_holds=set(native.get('active_cached',[]))|{k for k in ['thorns','controlled_damage'] if native.get(k) is not None}
        state={'address':address,'sequence':sequence,'phase':phase,'phase_label':PHASES[phase],'class_id':cls,'class':CLASSES[cls],'level':level,'elapsed':elapsed,'values':values,'holds':sorted(set(self.holds)|remote_holds),'native_settings':native}
        if self.native and self.native.session:self.native.bind(state)
        return state
    def mod_table(self,address):
        cap,ptr,n=struct.unpack('<QQQ',self.p.read(address+0x810,24))
        if not 0<=n<=cap<=4096:raise RuntimeError('属性表结构校验失败')
        return cap,ptr,n,self.p.read(ptr,n*8) if n else b''
    def mod_sum(self,address,tag):
        cap,ptr,n,data=self.mod_table(address)
        return sum(struct.unpack_from('<f',data,i*8+4)[0] for i in range(n) if data[i*8]==tag)
    def write_mod(self,address,tag,value):
        cap,ptr,n,data=self.mod_table(address);indices=[i for i in range(n) if data[i*8]==tag]
        if indices:
            for j,i in enumerate(indices):self.p.write(ptr+i*8+4,struct.pack('<f',value if j==0 else 0.))
        else:
            if cap<=n:raise RuntimeError('属性表需要游戏线程扩容，请重试')
            self.p.write(ptr+n*8,struct.pack('<B3xf',tag,value));self.p.write(address+0x820,struct.pack('<Q',n+1))
    def sync_cards(self,state=None,rebuild=True):
        """Synchronize an existing numeric UI cache with the already-written real game values."""
        if not self.session.get('ui_code'):return
        state=state or self.snapshot()
        if state['phase']!=2:return
        data,view=struct.unpack('<QQ',self.p.read(self.session['control']+16,16))
        if not data or not view:return
        value=self.p.read(data+0x80,32)
        if value[0]!=5:return
        node,height=struct.unpack_from('<QQ',value,8)
        # This build's card metadata is a single BTree leaf containing ten fields.
        # Reject another structure instead of following guessed nodes.
        if not node or height!=0:return
        count=struct.unpack('<H',self.p.read(node+0x272,2))[0]
        if not 1<=count<=11:return
        found={}
        for i in range(count):
            cap,ptr,n=struct.unpack('<QQQ',self.p.read(node+0x168+i*24,24))
            if not 0<n<=cap<=64:return
            key=self.p.read(ptr,n)
            if key in (b'gold',b'rerolls',b'banishes'):
                raw=self.p.read(node+i*32,24)
                if raw[0]!=2 or struct.unpack_from('<Q',raw,8)[0]!=0:return
                found[key.decode()]=(node+i*32+16,struct.unpack_from('<Q',raw,16)[0])
        if set(found)!={'gold','rerolls','banishes'}:return
        changed=False
        for key,(addr,old) in found.items():
            new=int(state['values'][key])
            if old!=new:self.p.write(addr,struct.pack('<Q',new));changed=True
        if changed and rebuild:
            version=struct.unpack('<I',self.p.read(data+0xe0,4))[0]
            self.p.write(view+0x40,struct.pack('<I',version^0xffffffff))
    def set_value(self,key,value,hold=None):
        f=FEATURES[key];encoded=f.encode(value)
        self.verify()
        if self.native is not None and (hold or key in ('luck','current_experience')):self.enable_native()
        if key in ('card_choices','treasure_choices','leech','invulnerable','one_hit','game_speed') or f.mod_tag is not None:
            self.enable_native();state=self.snapshot()
            if state['phase'] not in (1,2,3):raise RuntimeError('当前阶段不能修改对局值')
            if f.mod_tag is not None:
                cap,ptr,n,data=self.mod_table(state['address'])
                if cap==n:self.native.reserve_mods()
                with self.p.paused():
                    state=self.snapshot();before=self.mod_sum(state['address'],f.mod_tag);self.write_mod(state['address'],f.mod_tag,struct.unpack('<f',encoded)[0])
                    self.originals.setdefault(key,{'mod':before})
                    self.native.modifier(key,struct.unpack('<f',encoded)[0])
            else:
                self.originals.setdefault(key,{'native':state['native_settings'].get(key)})
                if key in ('invulnerable','one_hit'):self.native.toggle(key,bool(int(value)))
                else:self.native.setting(key,float(value))
            if hold:self.holds[key]=float(value)
            else:self.holds.pop(key,None)
            log('set_native_value',feature=key,value=float(value));return self.snapshot()
        with self.p.paused():
            state=self.snapshot()
            if state['phase'] not in (1,2,3):raise RuntimeError('只能在战斗、抽卡或暂停时修改对局数值')
            if key=='health' and float(value)>state['values']['max_health']+.01:raise ValueError('当前血量不能超过最大生命，请先修改最大生命')
            if key=='max_health' and 'health' in self.holds and float(self.holds['health'])>float(value):raise ValueError('保持的当前血量高于新上限，请先关闭血量保持')
            before=self.p.read(state['address']+f.offset,4)
            changes=[(state['address']+f.offset,before,encoded)]
            if key=='max_health' and state['values']['health']>float(value):
                hp=FEATURES['health'];changes.append((state['address']+hp.offset,self.p.read(state['address']+hp.offset,4),hp.encode(value)))
            try:
                for address,old,new in changes:self.p.write(address,new)
            except BaseException:
                for address,old,new in reversed(changes):self.p.write(address,old)
                raise
            self.originals.setdefault(key,before)
            if len(changes)>1:self.originals.setdefault('health',changes[1][1])
            if hold is True:self.holds[key]=float(value)
            elif hold is False:self.holds.pop(key,None)
            if self.native and self.native.session:
                self.native.cached(key,encoded,bool(hold) or key=='luck')
                if key=='current_experience':self.native.settle_xp()
            if key in ('rerolls','banishes','gold'):self.sync_cards()
        log('set_run_value',feature=key,before=struct.unpack('<'+f.kind,before)[0]*f.scale,value=float(value),hold=key in self.holds)
        return self.snapshot()
    def stop_hold(self,key):
        self.holds.pop(key,None)
        if self.native:self.native.stop(key)
    def stop_all(self):
        self.holds.clear()
        if self.native and self.native.session and self.p and self.p.alive():self.native.clear()
    def tick(self):
        if not self.holds:return
        # A single short pause applies all holds against the same validated run snapshot.
        with self.p.paused():
            state=self.snapshot()
            if state['phase'] not in (1,2,3):self.holds.clear();return
            for key,value in list(self.holds.items()):
                f=FEATURES[key]
                if self.native and self.native.session and (key in self.native.cached_keys or key in ('leech','card_choices','treasure_choices','game_speed','invulnerable','one_hit')):continue
                if f.mod_tag is not None:self.write_mod(state['address'],f.mod_tag,value/f.scale);continue
                if key=='health':value=min(value,state['values']['max_health'])
                self.p.write(state['address']+FEATURES[key].offset,FEATURES[key].encode(value))
            if 'max_health' in self.holds:
                current=struct.unpack('<f',self.p.read(state['address']+0x508,4))[0]
                if current>self.holds['max_health']:self.p.write(state['address']+0x508,FEATURES['health'].encode(self.holds['max_health']))
            if not (self.native and self.native.session) and any(k in self.holds for k in ('gold','rerolls','banishes')):self.sync_cards()
    def restore_values(self):
        with self.p.paused():
            state=self.snapshot()
            if state['phase'] not in (1,2,3):raise RuntimeError('当前阶段不能恢复对局数值')
            self.holds.clear()
            if self.native:self.native.clear()
            for key,original in self.originals.items():
                if isinstance(original,dict):
                    if 'mod' in original:self.write_mod(state['address'],FEATURES[key].mod_tag,original['mod'])
                else:self.p.write(state['address']+FEATURES[key].offset,original)
            hp,maxhp=FEATURES['health'],FEATURES['max_health']
            maximum=struct.unpack('<f',self.p.read(state['address']+maxhp.offset,4))[0]
            current=struct.unpack('<f',self.p.read(state['address']+hp.offset,4))[0]
            if current>maximum:self.p.write(state['address']+hp.offset,hp.encode(maximum))
            self.originals.clear()
            self.sync_cards()
        log('restore_run_values')
    def disable(self):
        self.verify();s=self.session
        self.holds.clear()
        if self.native and self.native.session:self.native.disable()
        ranges=[(self.p.base+CAPTURE_RVA,self.p.base+CAPTURE_RVA+len(CAPTURE_ORIGINAL)),(s['code'],s['code']+128)]
        if s.get('ui_code'):ranges.extend([(self.p.base+UI_RVA,self.p.base+UI_RVA+len(UI_ORIGINAL)),(s['ui_code'],s['ui_code']+128)])
        with self.p.paused(ranges):
            restored=[]
            try:
                if s.get('ui_code'):
                    restored.append((UI_RVA,UI_ORIGINAL,s['ui_code']));self.p.write_code(self.p.base+UI_RVA,UI_ORIGINAL)
                restored.append((CAPTURE_RVA,CAPTURE_ORIGINAL,s['code']));self.p.write_code(self.p.base+CAPTURE_RVA,CAPTURE_ORIGINAL)
            except BaseException:
                for rva,original,code in reversed(restored):self.p.write_code(self.p.base+rva,jump(code)+b'\x90'*(len(original)-14))
                raise
        self.session=None;log('disable_run_access')
