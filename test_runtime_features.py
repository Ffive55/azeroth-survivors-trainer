"""Bounded run-data safety tests; no live game process is opened."""
import unittest,struct,math
from unittest.mock import patch
from types import SimpleNamespace
from runtime_features import RunAccess,FEATURES
from test_trainer import Memory

def fixture():
    p=Memory();address=0x200000;control=0x100000;data=bytearray(0xc90)
    for f in FEATURES.values():
        if f.offset is not None:struct.pack_into('<'+f.kind,data,f.offset,int(f.minimum-f.bias) if f.kind=='I' else f.minimum/f.scale)
    struct.pack_into('<f',data,0x4a0,500);struct.pack_into('<f',data,0x508,400)
    struct.pack_into('<I',data,0x500,4);struct.pack_into('<f',data,0xbdc,30)
    data[0x33c]=8;data[0xc8a]=2
    p.seed(address,data);p.seed(control,struct.pack('<QQ',address,1))
    r=RunAccess(SimpleNamespace(p=p));r.session={'control':control};r.verify=lambda:None
    return r,p,address

class RuntimeTests(unittest.TestCase):
    def test_invalid_numeric_values_never_write(self):
        for value in [float('nan'),float('inf'),-1,10000001,1.5,True,'not a number']:
            r,p,a=fixture()
            with self.assertRaises(ValueError):r.set_value('gold',value)
            self.assertEqual(p.writes,[])
    @patch('runtime_features.log')
    def test_percent_conversion_and_field_isolation(self,_):
        r,p,a=fixture();r.set_value('crit',80)
        self.assertAlmostEqual(struct.unpack('<f',p.read(a+0x4ac,4))[0],.8)
        self.assertEqual([addr for addr,data in p.writes],[a+0x4ac])
    @patch('runtime_features.log')
    def test_health_cannot_exceed_maximum(self,_):
        r,p,a=fixture()
        with self.assertRaises(ValueError):r.set_value('health',501)
        self.assertFalse(p.writes)
    @patch('runtime_features.log')
    def test_lower_maximum_clamps_health_and_restore_reverts_both(self,_):
        r,p,a=fixture();r.set_value('max_health',200)
        self.assertEqual(r.snapshot()['values']['health'],200)
        r.restore_values();state=r.snapshot()
        self.assertEqual((state['values']['health'],state['values']['max_health']),(400,500))
    @patch('runtime_features.log')
    def test_group_write_failure_rolls_back(self,_):
        r,p,a=fixture();normal=p.write;failed=False
        def write(address,data):
            nonlocal failed
            if address==a+0x508 and not failed:failed=True;raise OSError('injected write failure')
            normal(address,data)
        p.write=write
        with self.assertRaises(OSError):r.set_value('max_health',200)
        state=r.snapshot()['values'];self.assertEqual((state['health'],state['max_health']),(400,500))
    @patch('runtime_features.log')
    def test_hold_recovers_external_value(self,_):
        r,p,a=fixture();r.set_value('gold',99,hold=True)
        p.seed(a+0x510,struct.pack('<I',4));r.tick()
        self.assertEqual(r.snapshot()['values']['gold'],99)
        r.stop_hold('gold');p.seed(a+0x510,struct.pack('<I',3));r.tick()
        self.assertEqual(r.snapshot()['values']['gold'],3)
    @patch('runtime_features.log')
    def test_new_run_stops_holds_and_discards_old_restore_values(self,_):
        r,p,a=fixture();r.set_value('gold',99,hold=True);p.writes.clear()
        p.seed(a+0xbdc,struct.pack('<f',0));r.tick()
        self.assertFalse(r.holds);self.assertFalse(r.originals);self.assertEqual(p.writes,[])
    @patch('runtime_features.log')
    def test_dead_run_refuses_numeric_writes(self,_):
        r,p,a=fixture();p.seed(a+0xc8a,b'\x04')
        with self.assertRaises(RuntimeError):r.set_value('gold',99)
        self.assertEqual(p.writes,[])
    @patch('runtime_features.log')
    def test_maximum_conflicting_with_held_health_is_rejected(self,_):
        r,p,a=fixture();r.set_value('health',400,hold=True);p.writes.clear()
        with self.assertRaises(ValueError):r.set_value('max_health',200)
        self.assertEqual(p.writes,[])
    @patch('runtime_features.log')
    def test_card_cache_sync_also_writes_actual_game_field(self,_):
        r,p,a=fixture();r.session['ui_code']=123;control=r.session['control'];data=0x300000;view=0x400000;node=0x500000
        p.seed(control+16,struct.pack('<QQ',data,view));value=bytearray(32);value[0]=5;struct.pack_into('<QQ',value,8,node,0);p.seed(data+0x80,value);p.seed(data+0xe0,struct.pack('<I',8));p.seed(node+0x272,struct.pack('<H',3))
        for i,key in enumerate(['banishes','gold','rerolls']):
            b=key.encode();p.seed(node+0x168+i*24,struct.pack('<QQQ',len(b),0x600000+i*64,len(b)));p.seed(0x600000+i*64,b)
            val=bytearray(32);val[0]=2;struct.pack_into('<QQ',val,8,0,0);p.seed(node+i*32,val)
        r.set_value('rerolls',12)
        self.assertEqual(struct.unpack('<I',p.read(a+0x568,4))[0],12)
        self.assertEqual(struct.unpack('<Q',p.read(node+2*32+16,8))[0],12)
        self.assertEqual(struct.unpack('<I',p.read(view+0x40,4))[0],8^0xffffffff)

if __name__=='__main__':unittest.main(verbosity=2)
