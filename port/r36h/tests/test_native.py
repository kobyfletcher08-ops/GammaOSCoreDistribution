# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fdt import read
from package_native import LINUX_FS, copy_range, read_gpt, write_gpt
from port_dts import generate


class NativeImageTests(unittest.TestCase):
    def test_both_gpt_copies_and_partition_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'disk.img'
            with path.open('wb') as f:
                f.truncate(40*1024**2)
            write_gpt(path, [dict(name='system', start=32768, end=65535,
                                 type=LINUX_FS, guid=uuid.uuid4())], 40*1024**2//512)
            self.assertEqual(read_gpt(path), [dict(name='system', start=32768, end=65535)])
            # Damage only the backup header; verification must still reject it.
            with path.open('r+b') as f:
                f.seek(path.stat().st_size-512+24)
                f.write(b'X')
            with self.assertRaisesRegex(ValueError, 'CRC'):
                read_gpt(path)

    def test_oversized_payload_cannot_modify_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            source, disk = Path(temp)/'source', Path(temp)/'disk'
            source.write_bytes(b'A'*4096)
            disk.write_bytes(b'original')
            with self.assertRaisesRegex(ValueError, 'fit'):
                copy_range(source, disk, 0, 1024)
            self.assertEqual(disk.read_bytes(), b'original')

    def test_truncated_fdt_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'bad.dtb'
            path.write_bytes(struct.pack('>10I', 0xd00dfeed, 4096, 56, 64, 40, 17, 16, 0, 32, 8))
            with self.assertRaisesRegex(ValueError, 'truncated'):
                read(path)


class ReferenceBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = Path(os.environ.get('R36H_REFERENCE_DIR', 'hardware-reference'))
        if not (cls.reference/'r36h-v20.dtb').is_file() or not (cls.reference/'r36h-v21.dtb').is_file():
            raise RuntimeError('Both checksum-verified R36H reference DTBs are required')

    def test_reference_model_cannot_be_mislabeled(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'model mismatch'):
                generate(self.reference/'r36h-v20.dtb', Path(temp)/'bad.dts', 'v21')

    def test_v20_preferred_timing_uses_resolved_label(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'board.dts'
            generate(self.reference/'r36h-v20.dtb', output, 'v20')
            text = output.read_text()
            self.assertIn('native-mode = <&timing0>;', text)
            self.assertIn('timing0: 60Hz', text)
            self.assertIn('gammaos,r36h-joypad', text)
            self.assertIn('simple-panel-dsi', text)
            self.assertNotIn('native-mode = <0xa0>', text)


if __name__ == '__main__':
    unittest.main()
