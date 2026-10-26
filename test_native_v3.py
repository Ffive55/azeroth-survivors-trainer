"""No-process regression tests for native controls, scope and patch rollback."""
import unittest,struct
from pathlib import Path
from unittest.mock import patch,Mock
from test_runtime_features import fixture
from native_v3 import NativeManager,CACHED_KEYS,code_bytes,T
from talents import jump
from runtime_features import FEATURES

def with_native():
    r,p,a=fixture();native=NativeManager(r);native.session={'control':0x700000};native.verify=lambda:None;r.native=native;r.enable_native=lambda:None
    return r,p,a,native

class NativeTests(unittest.TestCase):
    def test_dot_layers_are_one_based(self):
        self.assertEqual(FEATURES['dot_layers'].encode(3),struct.pack('<I',2))
        d=bytearray(0xc90);struct.pack_into('<I',d,0x4e4,2)
        self.assertEqual(FEATURES['dot_layers'].decode(d),3)
    @patch('runtime_features.log')
    def test_luck_native_override_is_ready_before_next_deal(self,_):
        r,p,a,n=with_native();r.set_value('luck',1000,hold=False)
        i=CACHED_KEYS.index('luck')
        self.assertEqual(n.read32(0x100+i*4),1)
        self.assertEqual(n.read32(0x200+i*4,'f'),10.)
    @patch('runtime_features.log')
    def test_locked_rerolls_do_not_refill_or_rebuild_from_python_tick(self,_):
        r,p,a,n=with_native();r.set_value('rerolls',99,hold=True);r.sync_cards=Mock();p.writes.clear();r.tick()
        self.assertFalse(any(addr==a+0x568 for addr,b in p.writes))
        r.sync_cards.assert_not_called()
    @patch('native_v3.log')
    def test_clear_stops_god_kill_speed_and_all_masks(self,_):
        r,p,a,n=with_native();n.toggle('invulnerable',True);n.toggle('one_hit',True);n.setting('game_speed',3);n.modifier('thorns',1)
        n.clear();s=n.info()
        self.assertFalse(s['invulnerable']);self.assertFalse(s['one_hit']);self.assertEqual(s['game_speed'],1);self.assertIsNone(s['thorns'])
    def test_choice_bounds_reject_unusable_counts(self):
        for key in ('card_choices','treasure_choices'):
            for bad in [0,7,100,1.5]:
                with self.assertRaises(ValueError):FEATURES[key].encode(bad)
    @patch('native_v3.log')
    def test_treasure_and_upgrade_counts_have_independent_controls(self,_):
        r,p,a,n=with_native();n.setting('card_choices',2);n.setting('treasure_choices',6)
        self.assertEqual((n.read32(32),n.read32(36)),(1,2))
        self.assertEqual((n.read32(88),n.read32(92)),(1,6))
        n.stop('treasure_choices')
        self.assertIsNone(n.info()['treasure_choices']);self.assertEqual(n.info()['card_choices'],2)
        n.setting('treasure_choices',1);n.clear()
        self.assertIsNone(n.info()['treasure_choices']);self.assertIsNone(n.info()['card_choices'])
    def test_native_relocations_have_no_fixed_image_or_control_addresses(self):
        b=code_bytes(0x7ff900000000,0x123450000)
        self.assertNotIn(struct.pack('<Q',0xbbb000000000),b)
        for offset,kind,addend in T.FIXUPS:
            self.assertEqual(struct.unpack_from('<Q',b,offset)[0],(0x7ff900000000 if kind=='base' else 0x123450000)+addend)
    def test_keyboard_hotkey_registration_removed(self):
        source=Path(__file__).with_name('app_v2.py').read_text(encoding='utf-8')
        self.assertNotIn('RegisterHotKey',source);self.assertNotIn('Ctrl+Alt',source);self.assertNotIn('Hotkeys(',source)
    @patch('native_v3.log')
    def test_detach_failure_rolls_all_entries_back_to_installed_hooks(self,_):
        r,p,a=fixture();p.pid=123;p.started=456;p.alive=lambda:True
        n=NativeManager(r);r.native=n;n.session={'control':0x700000,'code':0x800000,'pid':123,'started':456,'base':p.base}
        p.seed(0x800000,code_bytes(p.base,0x700000));expected={}
        for key,d in T.PATCHES.items():
            b=jump(0x800000+T.ENTRIES[key])+b'\x90'*(len(bytes.fromhex(d['original']))-14)
            p.seed(p.base+d['rva'],b);expected[p.base+d['rva']]=b
        original=p.write;calls=0
        def write_code(addr,data):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('injected detach failure')
            original(addr,data)
        p.write_code=write_code
        with self.assertRaises(OSError):n.disable()
        for addr,b in expected.items():self.assertEqual(p.read(addr,len(b)),b)

if __name__=='__main__':unittest.main(verbosity=2)
