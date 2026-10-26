"""Progression regression tests; no actual game process or user save is opened."""
import unittest,struct
from unittest.mock import Mock,patch
from pathlib import Path
from types import SimpleNamespace
from progression_catalog import GEAR,JEWELS,LEGENDARY,ACHIEVEMENTS
from progression_model import Document,change,selected_state
from progression_rpc import GameThread,code_bytes,HOOK_RVA,ORIGINAL
import progression_template as T
from save_codec import encode,decode
from test_trainer import Memory

BASE='pick|8|1|0|elwynn|Hero|0,0,0,0,0|100,100,100,100\nitems|108000\nopen|8|duskwood\nseen|accuria=1,legendary:fireball=4\nach|class:mage\nachat|class:mage=123\nperk|rerolls:3,banish:2\nstat|kills=12345,gold=6789\ntalent|8|71901|impact:5\nspec|8|0|impact:5||\nequip|8|0:108000\nlook|8|\ncustom|keep-this-record\n'

class ProgressionModelTests(unittest.TestCase):
    def test_every_class_has_its_native_gear_count(self):
        self.assertEqual(len(GEAR),9);self.assertEqual(sum(map(len,GEAR.values())),498)
        self.assertEqual((len(GEAR[4]),len(GEAR[7])),(60,60))
        self.assertEqual(len(set(i for ids in GEAR.values() for i in ids)),498)
    def test_each_class_unlocks_gear_and_drop_regions_in_isolation(self):
        for cls in GEAR:
            with self.subTest(cls=cls):
                r=change(BASE,'gear',[cls]);d=Document(r['text'])
                self.assertTrue(set(GEAR[cls])<=d.numbers('items'));self.assertEqual(d.get('open',cls),'naxx')
                for other in GEAR:
                    if other!=cls:self.assertEqual(d.numbers('items')&set(GEAR[other]),Document(BASE).numbers('items')&set(GEAR[other]))
                self.assertEqual(d.get('perk'),Document(BASE).get('perk'))
                self.assertEqual(d.get('seen'),Document(BASE).get('seen'))
    def test_all_class_codex_pools_include_shared_and_own_legendaries(self):
        self.assertEqual(len(JEWELS),39);self.assertEqual(sum(map(len,LEGENDARY.values())),103)
        for cls in LEGENDARY:
            r=change(BASE,'codex',[cls]);seen=Document(r['text']).mapping('seen')
            self.assertTrue(all(seen[k]==4 for k in (*JEWELS,*LEGENDARY[cls])))
            self.assertEqual(Document(r['text']).get('items'),Document(BASE).get('items'))
    def test_achievement_award_uses_exact_catalog_and_is_idempotent(self):
        first=change(BASE,'achievements',now=999);d=Document(first['text'])
        self.assertEqual((first['after']['achievements'],first['after']['points_total'],first['points_added']),(98,2270,2260))
        self.assertEqual(d.mapping('achat')['class:mage'],123)
        second=change(first['text'],'achievements',now=1000)
        self.assertFalse(second['changed']);self.assertEqual(second['points_added'],0);self.assertEqual(first['text'],second['text'])
    def test_existing_reward_spending_and_unrelated_progress_are_preserved(self):
        r=change(BASE,'all',now=999);d=Document(r['text']);old=Document(BASE)
        for kind in ('perk','stat','talent','spec','equip','look','custom','pick'):
            self.assertEqual(d.get(kind),old.get(kind))
    def test_existing_rare_and_unknown_records_are_preserved(self):
        source=BASE.replace('accuria=1','future_jewel=4,accuria=1').replace('108000','999999,108000',1)
        d=Document(change(source,'all',now=999)['text'])
        self.assertIn(999999,d.numbers('items'));self.assertEqual(d.mapping('seen')['future_jewel'],4)
    def test_all_unlock_is_repeatable_without_rewriting(self):
        first=change(BASE,'all',now=999);second=change(first['text'],'all',now=1000)
        self.assertFalse(second['changed']);self.assertEqual(first['text'],second['text'])
    def test_invalid_targets_and_damaged_text_are_rejected(self):
        for classes in [[],[6],[1,1],[True]]:
            with self.assertRaises(ValueError):change(BASE,'gear',classes)
        for text in ['not a save',BASE+'items|101000\n',BASE.replace('accuria=1','accuria=99')]:
            with self.assertRaises(ValueError):change(text,'all')
    def test_authenticated_native_save_roundtrip_and_tampering_rejection(self):
        blob=encode(BASE,bytes(range(16)));self.assertEqual(decode(blob),BASE)
        raw=bytearray(blob);raw[40]=ord('A') if raw[40]!=ord('A') else ord('B')
        with self.assertRaises(ValueError):decode(bytes(raw))
        for bad in [b'',b'RSE1:bad',b'RSE1:',b'pick|1']:
            with self.assertRaises(ValueError):decode(bad)
    def test_no_duplicate_achievement_timestamps_are_introduced(self):
        d=Document(change(BASE,'all',now=999)['text'])
        self.assertEqual(len(d.mapping('achat')),98);self.assertEqual(len(d.keys('ach')),98)

class ProgressionTransportTests(unittest.TestCase):
    def test_busy_command_arguments_are_never_overwritten(self):
        p=Memory();p.pid=1;p.started=2;g=GameThread(p);g.session={'control':0x900000};g.verify=lambda:None
        p.seed(g.control,struct.pack('<I',2))
        with self.assertRaises(RuntimeError):g.call(0x5acbb80,123,456)
        self.assertFalse(p.writes)
        with self.assertRaises(RuntimeError):g.commit(123,[(456,bytes(24),bytes(24),b'')])
        self.assertFalse(p.writes)
    def test_unknown_native_function_cannot_be_dispatched(self):
        p=Memory();p.pid=1;p.started=2;g=GameThread(p)
        with self.assertRaises(ValueError):g.call(0x123456)
        self.assertFalse(p.writes)
    def test_relocations_are_bound_to_this_process(self):
        b=code_bytes(0x123450000,0x7ff900000000)
        for off,kind in T.FIXUPS:self.assertEqual(struct.unpack_from('<Q',b,off)[0],0x123450000 if kind=='control' else 0x7ff900000000)
        self.assertNotIn(struct.pack('<Q',0xbbb000000000),b)
    def test_detach_failure_keeps_driver_hook_installed(self):
        from talents import jump
        p=Memory();p.pid=1;p.started=2;p.alive=lambda:True
        g=GameThread(p);g.session={'control':0x900000,'code':0xa00000};g.verify=lambda:None
        expected=jump(0xa00000)+b'\x90'*(len(ORIGINAL)-14);p.seed(p.base+HOOK_RVA,expected)
        calls=0
        def write_code(address,data):
            nonlocal calls
            calls+=1
            if calls==1:raise OSError('injected failure')
            p.write(address,data)
        p.write_code=write_code
        with self.assertRaises(OSError):g.close()
        self.assertEqual(p.read(p.base+HOOK_RVA,len(expected)),expected)
    def test_interface_snapshot_cannot_be_used_as_authoritative_roster(self):
        from progression_live import Progression
        p=Memory();a=Progression(SimpleNamespace(p=p));a.rpc=SimpleNamespace(control=0x900000);a.connect=lambda:None
        p.seed(0x900060,struct.pack('<QQQ',0x200000,1,0x300000))
        with self.assertRaisesRegex(RuntimeError,'真正保存'):a.roster()
        self.assertFalse(p.writes)
    def test_native_dispatcher_preserves_function_entry_stack_alignment(self):
        from capstone import Cs,CS_ARCH_X86,CS_MODE_64
        delta=0
        for ins in Cs(CS_ARCH_X86,CS_MODE_64).disasm(T.BLOB,0):
            if ins.mnemonic in ('push','pushfq'):delta+=8
            if ins.mnemonic=='sub' and ins.op_str.startswith('rsp,'):delta+=int(ins.op_str.split(',')[1].strip(),0)
            if ins.mnemonic=='call':break
        self.assertEqual((8-delta)%16,0)
        self.assertIn(ORIGINAL,T.BLOB)

if __name__=='__main__':unittest.main(verbosity=2)
