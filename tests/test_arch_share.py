import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

loader = importlib.machinery.SourceFileLoader('arch_share', str(Path(__file__).resolve().parents[1] / 'scripts/termux-arch-share.in'))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


@unittest.skipUnless(shutil.which('rclone') and shutil.which('sftp'), 'requires rclone and sftp binaries')
class ShareTransportTest(unittest.TestCase):
    def test_real_sftp_read_write_and_symlink_boundary(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            root = base / 'shared folder'
            root.mkdir()
            outside = base / 'outside'
            outside.mkdir()
            (root / 'original').write_text('host data')
            (outside / 'secret').write_text('outside canary')
            (root / 'escape').symlink_to(outside, target_is_directory=True)
            (base / 'upload').write_text('guest data')
            server = module.server_command(root, base / 'cache', False)
            def quote(path):
                return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'
            commands = ('get /original ' + quote(base / 'download') + '\n'
                        '-get /escape/secret ' + quote(base / 'leak') + '\n'
                        'put ' + quote(base / 'upload') + ' /created\n')
            p = subprocess.run(['sftp', '-D', shlex.join(server), '-b', '-'], input=commands,
                               text=True, capture_output=True, timeout=30,
                               env={k: v for k, v in os.environ.items() if not k.startswith('RCLONE_')})
            self.assertEqual(0, p.returncode, p.stderr)
            self.assertEqual('host data', (base / 'download').read_text())
            self.assertFalse((base / 'leak').exists())
            self.assertEqual('guest data', (root / 'created').read_text())
            server = module.server_command(root, base / 'readonly-cache', True)
            p = subprocess.run(['sftp', '-D', shlex.join(server), '-b', '-'],
                               input='-put ' + quote(base / 'upload') + ' /denied\n',
                               text=True, capture_output=True, timeout=30)
            self.assertEqual(0, p.returncode, p.stderr)
            self.assertFalse((root / 'denied').exists())
