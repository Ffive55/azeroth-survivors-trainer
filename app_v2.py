"""Compact, dark two-column trainer UI with independent feature rows."""
import ctypes as C
from ctypes import wintypes as W
import os, time, tkinter as tk
from tkinter import ttk, messagebox
from engine import Trainer, ROOT, backup, log
from runtime_features import RunAccess, FEATURES
from talents import CLASSES

BG='#1d1f20'; PANEL='#242627'; TEXT='#dadada'; MUTED='#8e9295'; ORANGE='#ff9000'; LINE='#4a4d4e'; GREEN='#88d5a0'
FONT=('Microsoft YaHei UI',10)

def label(parent,text='',**kw):return tk.Label(parent,text=text,bg=kw.pop('bg',BG),fg=kw.pop('fg',TEXT),font=kw.pop('font',FONT),padx=kw.pop('padx',0),pady=kw.pop('pady',0),**kw)
def button(parent,text,command,accent=False,**kw):
    return tk.Button(parent,text=text,command=command,bg=ORANGE if accent else '#353839',fg='#171819' if accent else TEXT,activebackground='#ffac36' if accent else '#484c4e',activeforeground=TEXT,bd=0,relief='flat',font=FONT,cursor='hand2',padx=kw.pop('padx',10),pady=kw.pop('pady',5),**kw)

class Toggle(tk.Canvas):
    def __init__(self,parent,command,disabled=False):
        super().__init__(parent,width=35,height=22,bg=BG,highlightthickness=0,cursor='arrow' if disabled else 'hand2')
        self.on=False;self.command=command;self.disabled=disabled;self.draw()
        if not disabled:self.bind('<Button-1>',lambda _:self.command())
    def draw(self):
        self.delete('all');color=ORANGE if self.on else '#101213'
        self.create_oval(2,4,16,18,fill=color,outline='');self.create_oval(18,4,32,18,fill=color,outline='');self.create_rectangle(9,4,25,18,fill=color,outline='')
        x=25 if self.on else 9
        self.create_oval(x-7,4,x+7,18,fill='#f6f6f6' if self.on else ('#55595b' if self.disabled else '#babdbf'),outline='')
    def set(self,value):
        if self.on!=bool(value):self.on=bool(value);self.draw()

class FeatureRow(tk.Frame):
    def __init__(self,parent,app,key,hotkey=''):
        super().__init__(parent,bg=BG);self.app=app;self.key=key
        self.columnconfigure(2,weight=1)
        self.toggle=Toggle(self,self.flip,disabled=key=='talents');self.toggle.grid(row=0,column=0,padx=(0,3))
        self.apply_button=button(self,'应用',self.apply,padx=3,pady=0)
        self.apply_button.configure(font=('Microsoft YaHei UI',8))
        self.apply_button.grid(row=0,column=1,padx=(0,6))
        title='可用天赋点数' if key=='talents' else FEATURES[key].label
        label(self,title,anchor='w',font=('Microsoft YaHei UI',9)).grid(row=0,column=2,sticky='w')
        self.current=tk.StringVar(value='当前 —')
        label(self,textvariable=self.current,fg=MUTED,font=('Microsoft YaHei UI',8),anchor='e',width=14).grid(row=0,column=3,sticky='e',padx=(4,5))
        self.value=tk.StringVar(value='50' if key=='talents' else FEATURES[key].default)
        box=tk.Frame(self,bg=ORANGE);box.grid(row=0,column=4,padx=(3,0))
        self.entry=tk.Entry(box,textvariable=self.value,width=7,bg=BG,fg=ORANGE,insertbackground=ORANGE,bd=0,font=('Consolas',10),justify='center',highlightthickness=0)
        self.entry.pack(pady=(0,1))
        unit='' if key=='talents' else FEATURES[key].unit
        label(self,unit,fg=MUTED,width=2,font=('Microsoft YaHei UI',8)).grid(row=0,column=5)
        info=label(self,'ⓘ',fg=MUTED,cursor='hand2',font=('Microsoft YaHei UI',9));info.grid(row=0,column=6,padx=(2,0))
        info.bind('<Button-1>',lambda _:self.help())
        self.configure(height=28);self.grid_propagate(False)
        if key in ('invulnerable','one_hit'):
            box.grid_remove();self.apply_button.configure(text='启用')
        if key=='game_speed':
            self.slider=tk.Scale(self,from_=.1,to=5,resolution=.1,orient='horizontal',showvalue=False,bg=BG,fg=ORANGE,troughcolor='#363a3c',highlightthickness=0,bd=0,sliderlength=16,command=lambda v:self.value.set(f'{float(v):g}'))
            self.slider.set(2);self.slider.grid(row=1,column=2,columnspan=3,sticky='ew');self.configure(height=52)
    def help(self):
        if self.key=='talents':text='设为剩余可用点数，最高总预算 999。单项天赋前置和等级仍生效。修改后切换游戏标签刷新。'
        else:
            f=FEATURES[self.key];text=f'{f.hint}\n范围：{f.minimum:g} 至 {f.maximum:g} {f.unit}\n属性是本局实际值；游戏重算属性后可再次应用，或开启保持。'
        self.app.notice.set(text.replace('\n','  '));messagebox.showinfo('使用说明',text,parent=self.app)
    def apply(self):
        def work():
            if self.key=='talents':
                self.app.ensure_talents();raw=self.value.get().strip()
                if not raw.isascii() or not raw.isdecimal():raise ValueError('可用天赋点数请输入非负整数')
                self.app.engine.set_available(self.app.class_id(),int(raw))
            elif self.key in ('invulnerable','one_hit'):
                self.app.ensure_run();self.app.run.set_value(self.key,int(not self.toggle.on))
            else:
                self.app.ensure_run();self.app.run.set_value(self.key,self.value.get(),hold=self.toggle.on)
        self.app.action(work,'已应用：'+('可用天赋点数' if self.key=='talents' else FEATURES[self.key].label))
    def flip(self):
        if self.key in ('invulnerable','one_hit'):self.apply();return
        if self.toggle.on:
            self.app.run.stop_hold(self.key);self.toggle.set(False);self.app.notice.set('游戏速度已恢复为 1 倍。' if self.key=='game_speed' else '已关闭保持；当前数值保留。')
        else:
            def work():self.app.ensure_run();self.app.run.set_value(self.key,self.value.get(),hold=True);self.toggle.set(True)
            self.app.action(work,'已开启保持：'+FEATURES[self.key].label)
    def render(self,value,holding=False):
        if value is None:self.current.set('当前 —')
        else:
            shown=('已开启' if value else '已关闭') if self.key in ('invulnerable','one_hit') else (f'{value:.3f}'.rstrip('0').rstrip('.') if isinstance(value,float) else str(value))
            self.current.set('当前 '+shown+(' '+FEATURES[self.key].unit if self.key!='talents' else ' 点'))
        self.toggle.set(holding)
        if self.key in ('invulnerable','one_hit'):self.apply_button.configure(text='关闭' if value else '启用')

class App(tk.Tk):
    def __init__(self):
        super().__init__();self.title('Azeroth Survivors · v3.3.1 修改器');self.geometry('1320x880');self.minsize(1240,800);self.configure(bg=BG)
        self.engine=Trainer();self.run=RunAccess(self.engine);self.rows={};self.latest=None;self.tick_error=None;self.progression=None;self.progression_window=None
        self.protocol('WM_DELETE_WINDOW',self.shutdown)
        self.notice=tk.StringVar(value='先连接游戏。应用前自动备份；输入数值后点击应用，左侧开关用于持续保持。')
        head=tk.Frame(self,bg=BG);head.pack(fill='x',padx=22,pady=(16,12))
        label(head,'《艾泽拉斯幸存者》',fg=ORANGE,font=('Microsoft YaHei UI',19,'bold')).pack(side='left')
        label(head,f'v3.3.1  {len(FEATURES)+1} 项修改 + 全职业永久解锁',fg=TEXT,font=('Microsoft YaHei UI',12,'bold')).pack(side='left',padx=18)
        label(head,'● 简体中文',fg=ORANGE).pack(side='right')
        tk.Frame(self,bg=LINE,height=1).pack(fill='x',padx=22)
        main=tk.Frame(self,bg=BG);main.pack(fill='both',expand=True,padx=22,pady=16)
        left=tk.Frame(main,bg=BG,width=210);left.pack(side='left',fill='y',padx=(0,22));left.pack_propagate(False)
        self.sidebar(left)
        body=tk.Frame(main,bg=BG);body.pack(side='left',fill='both',expand=True)
        top=tk.Frame(body,bg=BG);top.pack(fill='x',pady=(0,12))
        label(top,'功能列表',font=('Microsoft YaHei UI',13,'bold')).pack(side='left')
        label(top,'开关 = 启用/保持     应用 = 设置数值',fg=MUTED,font=('Microsoft YaHei UI',9)).pack(side='right')
        scroll=tk.Frame(body,bg=BG);scroll.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(scroll,bg=BG,highlightthickness=0);bar=ttk.Scrollbar(scroll,orient='vertical',command=self.canvas.yview);bar.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True);self.canvas.configure(yscrollcommand=bar.set)
        columns=tk.Frame(self.canvas,bg=BG);item=self.canvas.create_window(0,0,window=columns,anchor='nw')
        columns.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(item,width=e.width))
        columns.columnconfigure(0,weight=1,uniform='columns');columns.columnconfigure(1,weight=1,uniform='columns')
        col1=tk.Frame(columns,bg=BG);col1.grid(row=0,column=0,sticky='nsew',padx=(0,10))
        col2=tk.Frame(columns,bg=BG);col2.grid(row=0,column=1,sticky='nsew',padx=(10,0))
        self.section(col1,'战斗开关与变速')
        for key in ['invulnerable','one_hit','game_speed']:self.add_row(col1,key)
        self.section(col1,'资源与抽卡',pady=(18,8))
        for key in ['health','shield','gold','current_experience','rerolls','banishes','card_choices','treasure_choices','talents']:self.add_row(col1,key)
        self.section(col1,'生命与成长',pady=(18,8))
        for key in ['max_health','extra_lives','experience','gold_gain','luck']:self.add_row(col1,key)
        self.section(col2,'玩家战斗属性')
        for key in ['damage','cooldown','crit','crit_damage','damage_reduction','regeneration','area','extra_projectiles','echo','speed','pickup','heal_on_kill','leech','thorns','buff_power','dot_layers','dot_haste','controlled_damage','pet_damage']:self.add_row(col2,key)
        def wheel(e):self.canvas.yview_scroll(-int(e.delta/120),'units');return 'break'
        def bind_wheel(w):
            w.bind('<MouseWheel>',wheel)
            for child in w.winfo_children():bind_wheel(child)
        bind_wheel(scroll)
        foot=tk.Frame(self,bg=BG);foot.pack(fill='x',padx=22,pady=(0,14))
        tk.Frame(foot,bg=LINE,height=1).pack(fill='x',pady=(0,10))
        label(foot,textvariable=self.notice,fg=ORANGE,anchor='w',justify='left',wraplength=1300,font=('Microsoft YaHei UI',9)).pack(fill='x')
        label(foot,'本局生效  ·  关闭窗口会停止保持与高级功能  ·  1 倍为原速  ·  功能列表可用滚轮滚动',fg=MUTED,anchor='w',font=('Microsoft YaHei UI',9)).pack(fill='x',pady=(6,0))
        self.after(250,self.connect);self.after(150,self.poll)
    def sidebar(self,parent):
        art=tk.Canvas(parent,width=210,height=140,bg='#151718',highlightthickness=0);art.pack(fill='x',pady=(0,20))
        for i in range(12):art.create_line(0,i*12,210,128-i*5,fill=['#272627','#312c23','#3b3021'][i%3])
        art.create_text(105,54,text='AZEROTH',fill='#e0c282',font=('Georgia',21,'bold'));art.create_text(105,89,text='SURVIVORS',fill=ORANGE,font=('Georgia',17,'bold'))
        art.create_rectangle(1,1,208,138,outline='#5a4325')
        self.status=tk.StringVar(value='未连接');self.pid=tk.StringVar(value='—');self.hero=tk.StringVar(value='—');self.phase=tk.StringVar(value='—');self.health=tk.StringVar(value='—');self.holding=tk.StringVar(value='0 项')
        for title,var in [('连接状态',self.status),('进程 ID',self.pid),('当前角色',self.hero),('对局阶段',self.phase),('生命值',self.health),('持续保持',self.holding)]:
            row=tk.Frame(parent,bg=BG);row.pack(fill='x',pady=(0,13))
            label(row,title,fg=MUTED,font=('Microsoft YaHei UI',9),anchor='w').pack(side='left')
            label(row,textvariable=var,fg=TEXT,anchor='e',font=('Microsoft YaHei UI',9,'bold')).pack(side='right')
        self.cls=tk.StringVar(value='法师');style=ttk.Style(self);style.theme_use('clam');style.configure('TCombobox',fieldbackground=BG,background=PANEL,foreground=TEXT,arrowcolor=ORANGE)
        style.map('TCombobox',fieldbackground=[('readonly',BG)],foreground=[('readonly',TEXT)])
        label(parent,'天赋职业',fg=MUTED,anchor='w',font=('Microsoft YaHei UI',9)).pack(fill='x')
        combo=ttk.Combobox(parent,textvariable=self.cls,values=list(CLASSES.values()),state='readonly',width=16);combo.pack(fill='x',pady=(4,12))
        button(parent,'连接游戏',self.connect).pack(fill='x',pady=3)
        button(parent,'备份并启用全部',lambda:self.action(self.enable_all,'已启用，可以设置所需项目。'),accent=True).pack(fill='x',pady=3)
        button(parent,'还原本次窗口设置',lambda:self.action(self.restore_values,'已恢复本次窗口内设置前的对局值。')).pack(fill='x',pady=3)
        button(parent,'永久解锁 · 收藏 / 图鉴 / 成就',self.open_progression,accent=True,padx=4).pack(fill='x',pady=(12,3))
        links=tk.Frame(parent,bg=BG);links.pack(fill='x',pady=(12,0))
        for text,fn in [('打开备份',self.open_backups),('恢复与说明',self.more)]:
            l=label(links,text,fg=ORANGE,cursor='hand2',font=('Microsoft YaHei UI',9));l.pack(side='left',padx=(0,15));l.bind('<Button-1>',lambda _,f=fn:f())
    def section(self,parent,title,pady=(0,8)):
        label(parent,title,fg=ORANGE,font=('Microsoft YaHei UI',11,'bold'),anchor='w').pack(fill='x',pady=pady)
    def add_row(self,parent,key,hotkey=''):
        row=FeatureRow(parent,self,key,hotkey);row.pack(fill='x',pady=1);self.rows[key]=row
    def class_id(self):return next(k for k,v in CLASSES.items() if v==self.cls.get())
    def action(self,fn,message):
        try:fn();self.notice.set(message);self.refresh()
        except Exception as e:log('ui_v2_error',error=str(e));self.notice.set(str(e));messagebox.showerror('操作未完成',str(e),parent=self)
    def connect(self):
        def work():
            if self.progression:self.progression.close();self.progression=None
            self.run.holds.clear();self.engine.connect();self.run.connect()
        self.action(work,'已连接；点击“备份并启用全部”，或直接应用需要的项目。')
    def ensure_connected(self):
        if not self.engine.p or not self.engine.p.alive():self.engine.connect();self.run.connect()
    def ensure_talents(self):self.ensure_connected();self.engine.enable()
    def ensure_run(self):self.ensure_connected();self.run.enable();self.run.enable_native()
    def enable_all(self):self.ensure_talents();self.run.enable();self.run.enable_native()
    def restore_values(self):
        self.ensure_run();self.run.restore_values()
    def refresh(self):
        alive=bool(self.engine.p and self.engine.p.alive());self.status.set('已连接' if alive else '未连接');self.pid.set(str(self.engine.p.pid) if alive else '—')
        if not alive:
            self.run.holds.clear();self.phase.set('等待游戏');self.latest=None;self.hero.set('—');self.health.set('—');self.holding.set('0 项')
            for row in self.rows.values():row.render(None)
            return
        if self.run.session:
            try:
                state=self.run.snapshot();self.latest=state
                self.hero.set(f"{state['class']} · 等级 {state['level']}");self.phase.set(state['phase_label']);v=state['values'];self.health.set(f"{v['health']:.0f} / {v['max_health']:.0f}");self.holding.set(f"{len(state['holds'])} 项")
                native=state.get('native_settings',{})
                for key,value in v.items():
                    enabled=key in state['holds']
                    if key in ('invulnerable','one_hit'):enabled=bool(value)
                    elif key=='game_speed':enabled=abs(value-1)>.0001
                    elif key in ('leech','card_choices','treasure_choices'):enabled=native.get(key) is not None
                    self.rows[key].render(value,enabled)
            except Exception as e:self.phase.set('等待有效对局');self.run.holds.clear();self.notice.set(str(e))
        else:
            self.phase.set('对局读取未启用');self.hero.set('—');self.health.set('—');self.holding.set('0 项')
            for key in FEATURES:self.rows[key].render(None)
        if self.engine.session:
            try:
                s=self.engine.status(allow_empty=True);item=s.get('classes',{}).get(self.class_id());self.rows['talents'].render(item['available'] if item else None)
            except Exception as e:self.rows['talents'].render(None);self.notice.set(str(e))
    def poll(self):
        try:
            if self.run.holds:self.run.tick()
        except Exception as e:self.run.holds.clear();self.notice.set('已停止保持：'+str(e));log('hold_stopped',error=str(e))
        self.refresh();self.after(150,self.poll)
    def open_backups(self):(ROOT/'backups').mkdir(exist_ok=True);os.startfile(ROOT/'backups')
    def open_progression(self):
        from progression_ui import ProgressionWindow
        if self.progression_window and self.progression_window.winfo_exists():self.progression_window.lift();return
        self.progression_window=ProgressionWindow(self)
    def more(self):
        win=tk.Toplevel(self);win.title('恢复与使用说明');win.configure(bg=BG);win.geometry('590x330')
        label(win,'数值仅在本局生效；天赋规则作用于本次游戏进程。\n还原功能恢复本次窗口首次设置前的值。\n如果要恢复原生天赋，请先把所有方案退到原生预算以内。\n备份文件和 README.md 保存在修改器文件夹中。',justify='left',wraplength=540).pack(padx=22,pady=22,anchor='w')
        button(win,'恢复所选职业的原生天赋',lambda:self.action(lambda:self.engine.restore_class(self.class_id()),'已恢复原生天赋预算。')).pack(fill='x',padx=22,pady=4)
        button(win,'停止保持并撤销全部运行时补丁',lambda:self.action(self.disable_all,'已撤销运行时补丁，已应用的对局值保留。')).pack(fill='x',padx=22,pady=4)
        button(win,'打开使用说明',lambda:os.startfile(ROOT/'README.md')).pack(fill='x',padx=22,pady=4)
    def disable_all(self):
        self.run.holds.clear()
        if self.progression:self.progression.close();self.progression=None
        if self.engine.session:self.engine.disable()
        if self.run.session:self.run.disable()
    def shutdown(self):
        try:
            self.run.stop_all()
            if self.progression:self.progression.close()
        finally:self.engine.close();self.destroy()

def main():
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR];kernel.CreateMutexW.restype=W.HANDLE
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
    mutex=kernel.CreateMutexW(None,False,'Local\\AzerothSurvivorsTrainerV2')
    if not mutex:raise C.WinError(C.get_last_error())
    if C.get_last_error()==183:
        user=C.WinDLL('user32');user.MessageBoxW.argtypes=[W.HWND,W.LPCWSTR,W.LPCWSTR,W.UINT]
        user.MessageBoxW(None,'修改器已经运行，请切换到现有窗口。','Azeroth Survivors 修改器',0x40);kernel.CloseHandle(mutex);return
    try:App().mainloop()
    finally:kernel.CloseHandle(mutex)

if __name__=='__main__':main()
