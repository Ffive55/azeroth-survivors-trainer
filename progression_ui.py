"""Permanent progression panel, kept separate from ordinary run-value controls."""
import tkinter as tk
from tkinter import ttk,messagebox
from talents import CLASSES
from progression_catalog import GEAR,JEWELS,LEGENDARY,ACHIEVEMENTS
from progression_live import Progression

class ProgressionWindow(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app);self.app=app
        from app_v2 import BG,TEXT,MUTED,ORANGE,label,button
        self.title('永久解锁 · 全职业收藏、宝箱图鉴与成就');self.configure(bg=BG)
        self.geometry('930x710');self.minsize(880,680)
        self.target=tk.StringVar(value='全部职业');self.note=tk.StringVar(value='保持游戏运行。直接读取游戏真正保存的永久进度；点击刷新查看。')
        label(self,'永久解锁',font=('Microsoft YaHei UI',18,'bold'),fg=ORANGE).pack(anchor='w',padx=24,pady=(20,5))
        label(self,'即时更新游戏驱动持有的永久进度并原生保存；每次写入前自动备份。正常退出后保留。',fg=MUTED,wraplength=870,justify='left').pack(anchor='w',padx=24)
        top=tk.Frame(self,bg=BG);top.pack(fill='x',padx=24,pady=18)
        label(top,'目标职业').pack(side='left',padx=(0,10))
        ttk.Combobox(top,textvariable=self.target,values=['全部职业',*CLASSES.values()],state='readonly',width=17).pack(side='left')
        self.buttons=[]
        actions=[('刷新当前永久进度',self.refresh),('收藏装备 + 同步掉落表',lambda:self.apply('gear')),
                 ('宝箱装备图鉴（传说品质）',lambda:self.apply('codex')),
                 ('全部成就 + 同步成就点数',lambda:self.apply('achievements')),
                 ('全部职业一键解锁以上项目',lambda:self.apply('all'))]
        bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=24,pady=(0,12))
        for i,(title,fn) in enumerate(actions):
            b=button(bar,title,fn,accent=i==4,padx=12,pady=8);b.grid(row=i//2,column=i%2,sticky='ew',padx=(0,8),pady=(0,8));self.buttons.append(b)
        for col in range(2):bar.columnconfigure(col,weight=1)
        label(self,'收藏装备会同步开放所选职业的 12 个区域，以解锁掉落表。成就及奖励点数由账号共享；已消费点数继续扣除，重复解锁不会重复加点。',fg=MUTED,wraplength=870,justify='left').pack(anchor='w',padx=24,pady=(0,10))
        cols=('class','gear','codex','drops')
        self.tree=ttk.Treeview(self,columns=cols,show='headings',height=9)
        for key,title,width in [('class','职业',150),('gear','已收藏装备',190),('codex','传说品质图鉴',220),('drops','掉落区域',210)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,anchor='center')
        self.tree.pack(fill='both',expand=True,padx=24)
        self.points=tk.StringVar(value=f'全目录：{sum(map(len,GEAR.values()))} 件职业收藏装备 · {len(ACHIEVEMENTS)} 项成就 · 总计 {sum(ACHIEVEMENTS.values())} 成就点数')
        label(self,textvariable=self.points,fg=ORANGE,wraplength=870,justify='left').pack(anchor='w',padx=24,pady=12)
        label(self,textvariable=self.note,fg=TEXT,wraplength=870,justify='left',font=('Microsoft YaHei UI',9)).pack(fill='x',padx=24,pady=(0,18))
        self.after(100,self.refresh)
    def provider(self):
        self.app.ensure_connected()
        if getattr(self.app,'progression',None) is None:self.app.progression=Progression(self.app.engine)
        return self.app.progression
    def run_action(self,fn):
        for b in self.buttons:b.configure(state='disabled')
        self.note.set('正在读取、校验并等待游戏线程完成…');self.update_idletasks()
        try:return fn()
        except Exception as e:
            self.note.set(str(e));self.app.notice.set(str(e))
        finally:
            for b in self.buttons:b.configure(state='normal')
    def render(self,state):
        self.tree.delete(*self.tree.get_children())
        for cls,name in CLASSES.items():
            key=str(cls);opened=state['open'][key]
            zone='12 / 12，全部可查看' if opened=='naxx' else '原有进度：'+opened
            self.tree.insert('','end',values=(name,f"{state['gear'][key]} / {len(GEAR[cls])}",f"{state['codex'][key]} / {len(JEWELS)+len(LEGENDARY[cls])}",zone))
        self.points.set(f"已解锁成就 {state['achievements']} / {len(ACHIEVEMENTS)}　成就点数总计 {state['points_total']} / {sum(ACHIEVEMENTS.values())}（游戏按已消费点数计算可用余额）")
    def refresh(self):
        def work():
            state=self.provider().snapshot()['state'];self.render(state);self.note.set('已读取游戏真正保存的永久进度。解锁目标可选单职业或全部职业。')
        self.run_action(work)
    def apply(self,scope):
        def work():
            classes=None
            if scope not in ('achievements','all') and self.target.get()!='全部职业':classes=[next(k for k,v in CLASSES.items() if v==self.target.get())]
            result=self.provider().apply(scope,classes);self.render(result['after'])
            if result['changed']:
                text=f"已即时解锁并保存；本次新增 {result['points_added']} 成就点数。切换游戏标签刷新显示。备份：{result['backup']}"
            else:text='所选项目已经全部解锁，本次未重复写入或增加点数。'
            self.note.set(text);self.app.notice.set(text)
        self.run_action(work)
