import base64
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'scripts/termux-arch.in'
loader = importlib.machinery.SourceFileLoader('arch_shell', str(source))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
KEY = 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(32)).decode()


class ArchShellTest(unittest.TestCase):
    def test_argv_round_trip_without_shell_injection(self):
        args = ['', 'two words', "single'quote", '"double"', '$(touch should-not-exist)', 'line\nbreak', '*', ';exit 9']
        command = module.remote_command(os.getcwd(), ['printf', r'%s\0', *args])
        result = subprocess.run(['bash', '-c', command], capture_output=True)
        self.assertEqual(0, result.returncode)
        self.assertEqual(b'\0'.join(arg.encode() for arg in args) + b'\0', result.stdout)

    def test_missing_cwd_does_not_execute_command(self):
        command = module.remote_command('/this-path-must-not-exist-termux-arch', ['printf', 'executed'])
        result = subprocess.run(['bash', '-c', command], capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b'', result.stdout)

    def test_invalid_cwd_and_nul_fail_before_launch(self):
        for cwd, args in [('relative', ['true']), ('/root', ['bad\0arg'])]:
            with self.assertRaises(ValueError):
                module.remote_command(cwd, args)

    def test_host_key_is_pinned_and_change_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as work:
            path = module.pin_host(Path(work), KEY)
            self.assertEqual(f'termux-arch-v2 {KEY}\n', path.read_text())
            self.assertEqual(path, module.pin_host(Path(work), KEY))
            other = KEY[:-1] + ('B' if KEY[-1] == 'A' else 'A')
            with self.assertRaises(RuntimeError):
                module.pin_host(Path(work), other)

    def test_ssh_preserves_pty_choice_and_ignores_user_config(self):
        for tty in (True, False):
            args = module.ssh_command('/key', '/path with spaces/known', 12345, '/root', ['false'], tty)
            self.assertIn('-tt' if tty else '-T', args)
            self.assertEqual(['/dev/null'], args[args.index('-F') + 1:args.index('-F') + 2])
            self.assertIn('StrictHostKeyChecking=yes', args)
            self.assertIn('IdentityAgent=none', args)
            self.assertEqual('cd -- /root && exec false', args[-1])

    def test_ready_wait_and_error_handling(self):
        ready = dict(status='ready', running=True, vm_name='termux-arch-v2', ssh_port=22222, ssh_host_key=KEY)
        with patch.object(module, 'api', side_effect=[{'status': 'booting'}, ready]), patch.object(module.time, 'sleep'):
            self.assertEqual(ready, module.ensure_ready(KEY))
        for result in ({'status': 'denied', 'reason': 'permission'}, dict(ready, ssh_port=0), dict(ready, vm_name='other')):
            with patch.object(module, 'api', return_value=result), self.assertRaises(RuntimeError):
                module.ensure_ready(KEY)

    def test_public_key_wire_validation(self):
        self.assertEqual(KEY, module.public_key(KEY))
        with self.assertRaises(ValueError):
            module.public_key('ssh-ed25519 ' + 'A' * 68)


if __name__ == '__main__':
    unittest.main()
