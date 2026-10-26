"""Development-only assembler for the authoritative driver command dispatcher."""
from pathlib import Path
import struct
from keystone import Ks,KS_ARCH_X86,KS_MODE_64
CTL=0xbbb000000000;ORIGINAL=0xaaa000000000
save='pushfq;push rax;push rcx;push rdx;push r8;push r9;push r10;push r11;sub rsp,0x88;'
save+=';'.join(f'movdqu xmmword ptr [rsp+{0x20+i*16}],xmm{i}' for i in range(6))+';'
restore=';'.join(f'movdqu xmm{i},xmmword ptr [rsp+{0x20+i*16}]' for i in range(6))+';add rsp,0x88;pop r11;pop r10;pop r9;pop r8;pop rdx;pop rcx;pop rax;popfq;'
asm=save+f'movabs r11,{CTL};mov eax,dword ptr gs:[0x48];cmp dword ptr [r11+4],0;jne tid_known;mov dword ptr [r11+4],eax;tid_known:;cmp eax,dword ptr [r11+4];jne done;lea rax,[rcx+0x1020];mov qword ptr [r11+0x60],rax;mov qword ptr [r11+0x70],rcx;inc qword ptr [r11+0x68];inc qword ptr [r11+8];cmp dword ptr [r11],1;jne done;mov eax,dword ptr gs:[0x68];mov dword ptr [rsp+0x80],eax;mov dword ptr [r11],2;mov dword ptr [r11+0x40],0;cmp dword ptr [r11+0x48],1;je commit;mov rax,qword ptr [r11+0x10];mov rcx,qword ptr [r11+0x18];mov rdx,qword ptr [r11+0x20];mov r8,qword ptr [r11+0x28];mov r9,qword ptr [r11+0x30];call rax;movabs r11,{CTL};mov qword ptr [r11+0x38],rax;jmp finished;'
asm+='commit:;mov rax,qword ptr [r11+0x50];cmp rax,qword ptr [r11+0x60];jne invalid;mov r8d,dword ptr [r11+0x4c];cmp r8d,8;ja invalid;test r8d,r8d;je invalid;lea rdx,[r11+0x200];xor r10d,r10d;validate:;mov r9,qword ptr [rdx];mov rax,qword ptr [rdx+8];cmp qword ptr [r9],rax;jne invalid;mov rax,qword ptr [rdx+16];cmp qword ptr [r9+8],rax;jne invalid;mov rax,qword ptr [rdx+24];cmp qword ptr [r9+16],rax;jne invalid;cmp qword ptr [rdx+64],0;je data_valid;mov rcx,qword ptr [rdx+16];mov r9,qword ptr [rdx+56];xor eax,eax;check_data:;mov r8b,byte ptr [rcx+rax];cmp byte ptr [r9+rax],r8b;jne invalid;inc rax;cmp rax,qword ptr [rdx+64];jb check_data;data_valid:;add rdx,0x50;inc r10d;cmp r10d,dword ptr [r11+0x4c];jb validate;lea rdx,[r11+0x200];xor r10d,r10d;write_headers:;mov r9,qword ptr [rdx];mov rax,qword ptr [rdx+32];mov qword ptr [r9],rax;mov rax,qword ptr [rdx+40];mov qword ptr [r9+8],rax;mov rax,qword ptr [rdx+48];mov qword ptr [r9+16],rax;add rdx,0x50;inc r10d;cmp r10d,dword ptr [r11+0x4c];jb write_headers;mov rcx,qword ptr [r11+0x50];mov rax,qword ptr [r11+0x58];call rax;'
asm+=f'movabs r11,{CTL};jmp finished;invalid:;mov dword ptr [r11+0x40],1;finished:;mov eax,dword ptr [rsp+0x80];mov dword ptr gs:[0x68],eax;mov dword ptr [r11],3;done:;'+restore+'.byte 0x55,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x56,0x57,0x53,0x48,0x81,0xec,0x58,0x0d,0x00,0x00;jmp qword ptr [rip];.quad '+str(ORIGINAL)
blob=bytes(Ks(KS_ARCH_X86,KS_MODE_64).asm(asm)[0])
fix=[]
for marker,kind in [(CTL,'control'),(ORIGINAL,'original')]:
    start=0
    while (p:=blob.find(struct.pack('<Q',marker),start))>=0:fix.append((p,kind));start=p+8
Path(__file__).with_name('progression_template.py').write_text('"""Generated authoritative driver dispatcher; runtime uses only the standard library."""\nBLOB=bytes.fromhex('+repr(blob.hex())+')\nFIXUPS='+repr(fix)+'\n',encoding='utf-8')
print('Progression dispatcher',len(blob),'bytes')
