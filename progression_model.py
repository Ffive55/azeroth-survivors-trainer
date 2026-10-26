"""Idempotent, narrowly scoped changes to the game's native save-text format."""
import time
from progression_catalog import GEAR,JEWELS,LEGENDARY,ACHIEVEMENTS

CLASSES=tuple(GEAR)
SCOPES={'gear','codex','achievements','all'}

class Document:
    def __init__(self,text):
        if not isinstance(text,str) or len(text)>2_000_000 or '\x00' in text:raise ValueError('存档文本无效')
        self.lines=text.splitlines()
        if not any(line.startswith('pick|') for line in self.lines):raise ValueError('未识别到游戏存档')
        for kind in ('items','seen','ach','achat'):
            if sum(line.startswith(kind+'|') for line in self.lines)>1:raise ValueError('存档存在重复记录：'+kind)
    def text(self):return '\n'.join(self.lines)+'\n'
    def get(self,kind,cls=None):
        prefix=kind+'|' if cls is None else f'{kind}|{cls}|'
        rows=[x[len(prefix):] for x in self.lines if x.startswith(prefix)]
        if len(rows)>1:raise ValueError('存档存在重复职业记录')
        return rows[0] if rows else ''
    def put(self,kind,value,cls=None):
        prefix=kind+'|' if cls is None else f'{kind}|{cls}|'
        for i,line in enumerate(self.lines):
            if line.startswith(prefix):self.lines[i]=prefix+value;return
        self.lines.append(prefix+value)
    def numbers(self,kind):
        return {int(x) for x in self.get(kind).split(',') if x}
    def keys(self,kind):return {x for x in self.get(kind).split(',') if x}
    def mapping(self,kind):
        pairs=[x.rsplit('=',1) for x in self.get(kind).split(',') if x]
        if any(len(x)!=2 for x in pairs):raise ValueError('存档映射记录损坏：'+kind)
        result={k:int(v) for k,v in pairs}
        if len(result)!=len(pairs):raise ValueError('存档映射存在重复键：'+kind)
        return result
    def state(self):
        items=self.numbers('items');seen=self.mapping('seen');ach=self.keys('ach')
        return {'gear':{str(c):len(items&set(GEAR[c])) for c in CLASSES},
                'gear_total':sum(len(items&set(GEAR[c])) for c in CLASSES),
                'codex':{str(c):sum(seen.get(k,-1)>=4 for k in (*JEWELS,*LEGENDARY[c])) for c in CLASSES},
                'codex_discovered':{str(c):sum(k in seen for k in (*JEWELS,*LEGENDARY[c])) for c in CLASSES},
                'open':{str(c):self.get('open',c) or 'elwynn' for c in CLASSES},
                'achievements':len(ach&set(ACHIEVEMENTS)),
                'points_total':sum(v for k,v in ACHIEVEMENTS.items() if k in ach)}

def change(text,scope,classes=None,now=None):
    if scope not in SCOPES:raise ValueError('未知解锁项目')
    classes=CLASSES if classes is None else tuple(classes)
    if not classes or len(set(classes))!=len(classes) or any(c not in CLASSES or isinstance(c,bool) for c in classes):raise ValueError('无效职业选择')
    d=Document(text);before=d.state();fields=[]
    if scope in ('gear','all'):
        items=d.numbers('items')
        for cls in classes:
            items.update(GEAR[cls]);d.put('open','naxx',cls)
        d.put('items',','.join(map(str,sorted(items))));fields.extend(['items','open'])
    if scope in ('codex','all'):
        seen=d.mapping('seen')
        if any(not 0<=v<=4 for v in seen.values()):raise ValueError('图鉴稀有度记录异常')
        for cls in classes:
            for key in (*JEWELS,*LEGENDARY[cls]):seen[key]=4
        d.put('seen',','.join(f'{k}={v}' for k,v in sorted(seen.items())));fields.append('seen')
    if scope in ('achievements','all'):
        earned=d.keys('ach');times=d.mapping('achat');stamp=int(time.time() if now is None else now)
        if not 1<=stamp<=0xffffffffffffffff:raise ValueError('成就时间无效')
        for key in ACHIEVEMENTS:
            if key not in earned:earned.add(key);times.setdefault(key,stamp)
        d.put('ach',','.join(sorted(earned)));d.put('achat',','.join(f'{k}={v}' for k,v in sorted(times.items())));fields.extend(['ach','achat'])
    after=d.state()
    # Existing timestamps, stats, perks, equipment and talents remain byte-for-byte lines.
    changed=any(Document(text).get(k,c)!=d.get(k,c) for k in fields for c in (classes if k=='open' else (None,)))
    return {'text':d.text() if changed else text,'changed':changed,'fields':fields,'classes':list(classes),
            'before':before,'after':after,'points_added':after['points_total']-before['points_total']}

def selected_state(text,fields):
    d=Document(text);result={}
    for key in fields:
        if key=='items':result[key]=d.numbers(key)
        elif key=='ach':result[key]=d.keys(key)
        elif key=='open':result[key]={c:d.get(key,c) or 'elwynn' for c in CLASSES}
        else:result[key]=d.mapping(key)
    return result
