"""Small, bounded Windows process-memory transport. No remote threads."""
import ctypes as C
from ctypes import wintypes as W
from contextlib import contextmanager
import struct, time

K = C.WinDLL('kernel32', use_last_error=True)
N = C.WinDLL('ntdll')
SIZE = C.c_size_t
PTR = C.c_void_p

def api(name, restype, *args):
    f = getattr(K, name); f.restype = restype; f.argtypes = args; return f

OpenProcess = api('OpenProcess', W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
CloseHandle = api('CloseHandle', W.BOOL, W.HANDLE)
ReadProcessMemory = api('ReadProcessMemory', W.BOOL, W.HANDLE, PTR, PTR, SIZE, C.POINTER(SIZE))
WriteProcessMemory = api('WriteProcessMemory', W.BOOL, W.HANDLE, PTR, PTR, SIZE, C.POINTER(SIZE))
VirtualAllocEx = api('VirtualAllocEx', PTR, W.HANDLE, PTR, SIZE, W.DWORD, W.DWORD)
VirtualProtectEx = api('VirtualProtectEx', W.BOOL, W.HANDLE, PTR, SIZE, W.DWORD, C.POINTER(W.DWORD))
FlushInstructionCache = api('FlushInstructionCache', W.BOOL, W.HANDLE, PTR, SIZE)
QueryFullProcessImageNameW = api('QueryFullProcessImageNameW', W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD))
GetProcessTimes = api('GetProcessTimes', W.BOOL, W.HANDLE, PTR, PTR, PTR, PTR)
GetExitCodeProcess = api('GetExitCodeProcess', W.BOOL, W.HANDLE, C.POINTER(W.DWORD))
Snapshot = api('CreateToolhelp32Snapshot', W.HANDLE, W.DWORD, W.DWORD)
OpenThread = api('OpenThread', W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
GetThreadContext = api('GetThreadContext', W.BOOL, W.HANDLE, PTR)
N.NtSuspendProcess.argtypes=[W.HANDLE]; N.NtSuspendProcess.restype=C.c_long
N.NtResumeProcess.argtypes=[W.HANDLE]; N.NtResumeProcess.restype=C.c_long

class PROCESSENTRY32(C.Structure):
    _fields_=[('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',SIZE),('module',W.DWORD),('threads',W.DWORD),('parent',W.DWORD),('priority',W.LONG),('flags',W.DWORD),('exe',W.WCHAR*260)]
class MODULEENTRY32(C.Structure):
    _fields_=[('size',W.DWORD),('id',W.DWORD),('pid',W.DWORD),('globalUsage',W.DWORD),('procUsage',W.DWORD),('base',PTR),('length',W.DWORD),('module',W.HMODULE),('name',W.WCHAR*256),('path',W.WCHAR*260)]
class THREADENTRY32(C.Structure):
    _fields_=[('size',W.DWORD),('usage',W.DWORD),('tid',W.DWORD),('pid',W.DWORD),('basePri',W.LONG),('deltaPri',W.LONG),('flags',W.DWORD)]

def entries(flag, pid, typ, first, next_):
    handle=Snapshot(flag,pid)
    if handle == C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
    try:
        a=api(first,W.BOOL,W.HANDLE,C.POINTER(typ)); b=api(next_,W.BOOL,W.HANDLE,C.POINTER(typ))
        item=typ(); item.size=C.sizeof(item)
        ok=a(handle,C.byref(item))
        while ok:
            yield typ.from_buffer_copy(item)
            ok=b(handle,C.byref(item))
    finally: CloseHandle(handle)

def game_pids():
    return [e.pid for e in entries(2,0,PROCESSENTRY32,'Process32FirstW','Process32NextW') if e.exe.lower()=='azerothsurvivors.exe']

class Process:
    def __init__(self,pid):
        self.pid=pid
        self.handle=OpenProcess(0x0438|0x0800,False,pid) # query/read/write/VM operation/suspend
        if not self.handle: raise C.WinError(C.get_last_error())
        try:
            path=C.create_unicode_buffer(32768); n=W.DWORD(len(path))
            if not QueryFullProcessImageNameW(self.handle,0,path,C.byref(n)): raise C.WinError(C.get_last_error())
            self.path=path.value
            times=[C.c_ulonglong() for _ in range(4)]
            if not GetProcessTimes(self.handle,*[C.byref(x) for x in times]): raise C.WinError(C.get_last_error())
            self.started=times[0].value
            mods=list(entries(0x18,pid,MODULEENTRY32,'Module32FirstW','Module32NextW'))
            self.base=next(x.base for x in mods if x.path.lower()==self.path.lower())
        except BaseException:
            self.close(); raise

    def close(self):
        if self.handle: CloseHandle(self.handle); self.handle=None

    def alive(self):
        code=W.DWORD()
        return bool(self.handle and GetExitCodeProcess(self.handle,C.byref(code)) and code.value==259)

    def read(self,addr,n):
        buf=C.create_string_buffer(n); done=SIZE()
        if not ReadProcessMemory(self.handle,addr,buf,n,C.byref(done)) or done.value!=n: raise C.WinError(C.get_last_error())
        return buf.raw

    def write(self,addr,data):
        done=SIZE(); buf=C.create_string_buffer(data)
        if not WriteProcessMemory(self.handle,addr,buf,len(data),C.byref(done)) or done.value!=len(data): raise C.WinError(C.get_last_error())
        if self.read(addr,len(data))!=data: raise RuntimeError('内存写入回读不一致')

    def alloc(self,n):
        addr=VirtualAllocEx(self.handle,None,n,0x3000,4)
        if not addr: raise C.WinError(C.get_last_error())
        return addr

    def protect(self,addr,n,protection):
        old=W.DWORD()
        if not VirtualProtectEx(self.handle,addr,n,protection,C.byref(old)): raise C.WinError(C.get_last_error())
        return old.value

    def write_code(self,addr,data):
        old=self.protect(addr,len(data),0x40)
        try:
            self.write(addr,data)
            if not FlushInstructionCache(self.handle,addr,len(data)): raise C.WinError(C.get_last_error())
        finally: self.protect(addr,len(data),old)

    @contextmanager
    def paused(self,forbidden=()):
        """Suspend briefly; refuse to patch underneath an instruction pointer."""
        if N.NtSuspendProcess(self.handle)<0: raise RuntimeError('无法暂挂游戏，未写入')
        try:
            if forbidden:
                for t in entries(4,0,THREADENTRY32,'Thread32First','Thread32Next'):
                    if t.pid!=self.pid: continue
                    h=OpenThread(8,False,t.tid)
                    if not h: raise C.WinError(C.get_last_error())
                    try:
                        raw=C.create_string_buffer(1248); address=(C.addressof(raw)+15)&~15
                        C.c_uint32.from_address(address+48).value=0x100001
                        if not GetThreadContext(h,address): raise C.WinError(C.get_last_error())
                        rip=C.c_uint64.from_address(address+248).value
                        if any(a<=rip<b for a,b in forbidden): raise RuntimeError('游戏线程正在经过补丁位置，请重试')
                    finally: CloseHandle(h)
            yield
        finally:
            if N.NtResumeProcess(self.handle)<0: raise RuntimeError('恢复游戏线程失败')
