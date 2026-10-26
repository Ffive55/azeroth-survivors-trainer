"""Check release hook bytes against the supported installed executable, read-only."""
import hashlib, unittest
from pathlib import Path
from unittest.mock import patch
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64, CS_OP_MEM, CS_OP_IMM
from engine import Trainer, GAME
import talents
import runtime_features as R
import native_templates_v3 as T
import progression_rpc as P

class BuildCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GAME.is_file():
            raise unittest.SkipTest('未安装相邻的受支持游戏；跳过只读二进制兼容性检查')
        cls.data=GAME.read_bytes()
        cls.pe=pefile.PE(data=cls.data,fast_load=True)
        cls.md=Cs(CS_ARCH_X86,CS_MODE_64);cls.md.detail=True
    def test_release_signatures_match_complete_instructions(self):
        self.assertEqual(hashlib.sha256(self.data).hexdigest(),talents.GAME_SHA256)
        patches=talents.PATCHES+[(R.CAPTURE_RVA,R.CAPTURE_ORIGINAL),(R.UI_RVA,R.UI_ORIGINAL)]
        patches += [(d['rva'],bytes.fromhex(d['original'])) for d in T.PATCHES.values()]
        patches += [(P.HOOK_RVA,P.ORIGINAL)]
        for rva,original in patches:
            with self.subTest(rva=hex(rva)):
                self.assertGreaterEqual(len(original),14)
                self.assertEqual(self.pe.get_data(rva,len(original)),original)
                self.assertEqual(sum(i.size for i in self.md.disasm(original,rva)),len(original))
    def test_copied_prologues_have_no_unrelocated_branches_or_rip_operands(self):
        patches=talents.PATCHES+[(R.CAPTURE_RVA,R.CAPTURE_ORIGINAL),(R.UI_RVA,R.UI_ORIGINAL)]
        patches += [(d['rva'],bytes.fromhex(d['original'])) for k,d in T.PATCHES.items() if k not in ('reroll','leech','treasure_min')]
        patches += [(P.HOOK_RVA,P.ORIGINAL)]
        for rva,original in patches:
            for i in self.md.disasm(original,rva):
                self.assertFalse(i.mnemonic.startswith(('j','call')),hex(i.address))
                self.assertFalse(any(o.type==CS_OP_MEM and i.reg_name(o.mem.base)=='rip' for o in i.operands),hex(i.address))
    def test_reroll_and_leech_relocations_keep_native_branch_destinations(self):
        for key,expected in [('reroll',0x5c09967),('leech',0x5ba17e8),('treasure_min',0x5c050dc)]:
            d=T.PATCHES[key];instructions=list(self.md.disasm(bytes.fromhex(d['original']),d['rva']))
            branch=next(i for i in instructions if i.mnemonic.startswith('j'))
            self.assertEqual(branch.operands[0].imm,expected)
            self.assertIn(('base',expected),[(kind,addend) for _,kind,addend in T.FIXUPS])
    @patch('engine.game_pids',return_value=[123])
    @patch('engine.sha',return_value='0'*64)
    @patch('engine.Process')
    def test_unknown_build_closes_connection_before_any_write(self,process,sha,pids):
        p=process.return_value;p.path=str(GAME)
        t=Trainer()
        with self.assertRaisesRegex(RuntimeError,'0.119.0'):t.connect()
        p.write.assert_not_called();p.write_code.assert_not_called();p.close.assert_called_once()
        self.assertIsNone(t.p);self.assertIsNone(t.session)

if __name__=='__main__':unittest.main(verbosity=2)
