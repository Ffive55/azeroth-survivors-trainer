"""Safety/regression tests against an in-memory fixture; never touch the game."""
import unittest, struct
from contextlib import nullcontext
from unittest.mock import patch
from engine import Trainer
import talents

class Memory:
    base=0x140000000
    def __init__(self): self.data={}; self.writes=[]
    def seed(self,a,b): self.data.update({a+i:x for i,x in enumerate(b)})
    def read(self,a,n): return bytes(self.data.get(a+i,0) for i in range(n))
    def write(self,a,b): self.writes.append((a,b)); self.seed(a,b)
    def paused(self,*a): return nullcontext()

def fixture():
    p=Memory(); control=0x10000; roster=0x20000; array=0x30000; ranks=0x40000
    p.seed(control,struct.pack('<Q',roster)); p.seed(control+0x40,b'\xff'*48)
    p.seed(roster+0x60,struct.pack('<QQQ',1,array,1))
    p.seed(array,struct.pack('<IB3xQQQ8x',51407,8,4,ranks,4))
    p.seed(ranks,b''.join(struct.pack('<QB7x',p.base+0x10000+i*0xa0,n) for i,n in enumerate([5,5,5,4])))
    t=Trainer(); t.p=p; t.session={'control':control}; t.verify=lambda:None
    return t,p,control,array

class Tests(unittest.TestCase):
    @patch('engine.game_pids',return_value=[])
    def test_reconnect_drops_old_session(self,_):
        t=Trainer(); t.session={'pid':123,'control':0x10000}; t.session_path='old-session'
        with self.assertRaises(RuntimeError): t.connect()
        self.assertIsNone(t.session); self.assertIsNone(t.session_path)
    def test_earned_thresholds(self):
        for n in range(1,52):
            threshold=80*n+15*n*(n-1)//2
            self.assertEqual(talents.earned(threshold),n)
            self.assertEqual(talents.earned(threshold-1),n-1)
        self.assertEqual(talents.earned(0xffffffff),51)
    @patch('engine.log')
    def test_remaining_is_not_total(self,_):
        t,p,c,a=fixture(); old=p.read(a,32)
        result=t.set_available(8,50)
        self.assertEqual((result['spent'],result['total'],result['available']),(19,69,50))
        self.assertEqual(p.read(a,32),old) # no XP, rank-vector, or save modification
        self.assertEqual([x[0] for x in p.writes],[c+0x40+32])
    @patch('engine.log')
    def test_zero_preserves_invested_points(self,_):
        t,p,c,a=fixture(); result=t.set_available(8,0)
        self.assertEqual((result['spent'],result['total'],result['available']),(19,19,0))
    def test_reject_invalid_values_without_writes(self):
        for value in [-1,True,1.5,None,'5',1000,981]:
            t,p,c,a=fixture()
            with self.assertRaises((ValueError,TypeError)): t.set_available(8,value)
            self.assertFalse(p.writes)
    @patch('engine.log')
    def test_class_isolation(self,_):
        t,p,c,a=fixture(); t.set_available(8,50)
        for cls in talents.CLASSES:
            if cls!=8:self.assertEqual(p.read(c+0x40+cls*4,4),b'\xff'*4)
    def test_bad_vector_is_rejected(self):
        t,p,c,a=fixture(); p.seed(a+24,struct.pack('<Q',1000000))
        with self.assertRaises(RuntimeError): t.set_available(8,50)
        self.assertFalse(p.writes)
    def test_missing_roster(self):
        t,p,c,a=fixture(); p.seed(c,b'\0'*8)
        with self.assertRaises(RuntimeError): t.set_available(8,50)
        self.assertFalse(p.writes)
    def test_new_roster_stride_and_loadout_flags_are_not_rank_vectors(self):
        t,p,c,a=fixture();roster=0x20000
        first=p.read(a,40)
        second=bytearray(40);struct.pack_into('<IB3xQQQ',second,0,80,11,0,8,0)
        p.seed(roster+0x60,struct.pack('<QQQ',2,a,2));p.seed(a,first+second)
        slots=bytearray(208)
        for i,cls in enumerate((8,11)):
            slots[i*104]=cls
            for j in range(3):
                struct.pack_into('<QQQ',slots,i*104+8+j*32,0,8,0)
                slots[i*104+32+j*32]=1
        p.seed(roster+0x78,struct.pack('<QQQ',2,0x50000,2));p.seed(0x50000,slots)
        result=talents.read_roster(p,c)
        self.assertEqual(set(result),{8,11})
        self.assertEqual(result[8]['spent'],19)
        self.assertEqual(result[11]['earned'],1)
        self.assertEqual(result[11]['loadout_spent'],[0,0,0])
        self.assertFalse(p.writes)
    @patch('engine.log')
    def test_restore_budget_guard(self,_):
        t,p,c,a=fixture(); p.seed(a,struct.pack('<I',80)) # native budget only 1
        with self.assertRaises(RuntimeError): t.restore_class(8)
        self.assertFalse(p.writes)
    @patch('engine.log')
    def test_restore_budget(self,_):
        t,p,c,a=fixture(); t.set_available(8,50); t.restore_class(8)
        result=talents.read_roster(p,c)[8]
        self.assertEqual((result['total'],result['spent'],result['available']),(51,19,32))
    def test_inactive_loadout_is_protected(self):
        t,p,c,a=fixture(); roster=0x20000
        p.seed(roster+0x78,struct.pack('<QQQ',1,0x50000,1))
        row=bytearray(104); row[0]=8
        struct.pack_into('<QQQ',row,40,11,0x60000,11)
        p.seed(0x50000,row)
        p.seed(0x60000,b''.join(struct.pack('<QB7x',p.base+0x10000+i*0xa0,5) for i in range(11)))
        with self.assertRaises(ValueError): t.set_available(8,0)
        with self.assertRaises(RuntimeError): t.restore_class(8)
        self.assertFalse(p.writes)

if __name__=='__main__': unittest.main(verbosity=2)
