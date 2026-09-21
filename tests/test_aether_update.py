import hashlib
import io
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/aether-update.in'
PACKAGE = 'termux-aether-suite-aarch64.pkg.tar.xz'


class UpdateTests(unittest.TestCase):
    def execute(self, corrupt=None, arguments=()):
        contents = {PACKAGE: b'package', 'aether-install.py': b'helper'}
        def download(url, **kwargs):
            name = url.rsplit('/', 1)[1]
            if name.endswith('.sha256'):
                target = name[:-7]
                digest = '0' * 64 if target == corrupt else hashlib.sha256(contents[target]).hexdigest()
                return io.BytesIO(f'{digest}  {target}\n'.encode())
            return io.BytesIO(contents[name])
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(Path, 'home', return_value=Path(temporary)), \
             patch('urllib.request.urlopen', side_effect=download), \
             patch('subprocess.run') as run, \
             patch.object(sys, 'argv', [str(SCRIPT), *arguments]):
            if corrupt:
                with self.assertRaisesRegex(SystemExit, 'Checksum mismatch'):
                    runpy.run_path(str(SCRIPT), run_name='__main__')
                run.assert_not_called()
            else:
                runpy.run_path(str(SCRIPT), run_name='__main__')
                run.assert_called_once()
                argv = run.call_args.args[0]
                self.assertTrue(argv[2].endswith(PACKAGE))
                for argument in arguments:
                    self.assertIn(argument, argv)
                self.assertNotIn('--overwrite', argv)

    def test_bad_package_stops_before_install(self):
        self.execute(corrupt=PACKAGE)

    def test_bad_helper_stops_before_execute(self):
        self.execute(corrupt='aether-install.py')

    def test_check_and_legacy_options_are_forwarded(self):
        self.execute(arguments=['--check', '--adopt-legacy'])


if __name__ == '__main__':
    unittest.main()
