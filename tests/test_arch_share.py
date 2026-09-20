import importlib.machinery
import importlib.util
import contextlib
import io
import signal
from types import SimpleNamespace
from unittest import mock
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


class ShareCleanupTest(unittest.TestCase):
    def run_share(self, signals=(), unmount_results=(), client_wait_errors=0,
                  server_wait_errors=0, client_start_error=False, loop_error=False):
        handlers = {}
        clients = []
        unmounts = []
        pending_signals = iter(signals)
        outcomes = iter(unmount_results)

        class Child:
            def __init__(self, wait_errors=0, trigger=False):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO()
                self.returncode = None
                self.wait_errors = wait_errors
                self.trigger = trigger
                self.terminated = False
                self.killed = False

            def poll(self):
                if self.trigger and self.returncode is None:
                    number = next(pending_signals, None)
                    if number is not None:
                        handlers[number](number, None)
                return self.returncode

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True
                self.returncode = -signal.SIGKILL

            def wait(self, timeout):
                if self.wait_errors:
                    self.wait_errors -= 1
                    raise subprocess.TimeoutExpired('child', timeout)
                if self.returncode is None:
                    self.returncode = -signal.SIGTERM if self.terminated else 0
                return self.returncode

        server = Child(server_wait_errors)
        client = Child(client_wait_errors, trigger=True)
        clients.extend([server, client])

        def set_signal(number, handler):
            previous = handlers.get(number, signal.SIG_DFL)
            handlers[number] = handler
            return previous

        def run(command, **kwargs):
            if command[0] != 'fusermount3':
                return SimpleNamespace(returncode=0)
            unmounts.append(command)
            outcome = next(outcomes)
            if callable(outcome):
                outcome = outcome(handlers)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome == 0:
                client.returncode = 0
            return SimpleNamespace(returncode=outcome)

        arch = mock.Mock()
        arch.credentials.return_value = ('identity', 'key')
        arch.vm_session.side_effect = lambda _: contextlib.nullcontext()
        arch.ensure_ready.return_value = {'ssh_host_key': 'host', 'ssh_port': 22}
        arch.pin_host.return_value = 'known'
        arch.ssh_command.side_effect = lambda identity, known, port, cwd, command, tty: command
        self.children = clients
        self.unmounts = unmounts
        self.handlers = handlers
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(module.Path, 'home', return_value=Path(directory)), \
             mock.patch.object(module.shutil, 'which', return_value='/bin/rclone'), \
             mock.patch.object(module, 'load_arch', return_value=arch), \
             mock.patch.object(module.signal, 'signal', side_effect=set_signal), \
             mock.patch.object(module.time, 'sleep', side_effect=RuntimeError('loop failed') if loop_error else None), \
             mock.patch.object(module.subprocess, 'run', side_effect=run), \
             mock.patch.object(module.subprocess, 'Popen', side_effect=[
                 server, OSError('client launch failed') if client_start_error else client]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return module.main([directory, '/mnt/project'])

    def assert_cleaned(self):
        server, client = self.children
        self.assertTrue(server.stdin.closed)
        self.assertTrue(server.stdout.closed)
        self.assertIsNotNone(server.returncode)
        self.assertIsNotNone(client.returncode)
        self.assertTrue(all(handler == signal.SIG_DFL for handler in self.handlers.values()))

    def test_term_and_hup_exit_after_busy_unmount(self):
        for number in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=number):
                self.assertEqual(128 + number, self.run_share([number], [1]))
                self.assertEqual(1, len(self.unmounts))
                self.assert_cleaned()

    def test_interrupt_allows_busy_unmount_retry(self):
        self.assertEqual(0, self.run_share([signal.SIGINT, signal.SIGINT], [1, 0]))
        self.assertEqual(2, len(self.unmounts))
        self.assert_cleaned()

    def test_termination_during_interrupt_unmount_takes_priority(self):
        def terminate(handlers):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            handlers[signal.SIGINT](signal.SIGINT, None)
            return 1
        self.assertEqual(143, self.run_share([signal.SIGINT], [terminate]))
        self.assertEqual(1, len(self.unmounts))
        self.assert_cleaned()

    def test_unmount_errors_still_stop_both_children(self):
        for error in (OSError('ssh failed'), subprocess.TimeoutExpired('ssh', 20)):
            with self.subTest(error=error):
                self.assertEqual(143, self.run_share([signal.SIGTERM], [error]))
                self.assert_cleaned()

    def test_both_children_are_killed_after_termination_timeout(self):
        self.assertEqual(143, self.run_share([signal.SIGTERM], [1],
                                           client_wait_errors=1, server_wait_errors=1))
        self.assertTrue(all(child.killed for child in self.children))
        self.assert_cleaned()

    def test_client_wait_failure_cannot_skip_server_cleanup(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_share([signal.SIGHUP], [1], client_wait_errors=2)
        self.assertTrue(self.children[1].killed)
        self.assert_cleaned()

    def test_server_eof_timeout_falls_back_to_termination_and_kill(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_share([signal.SIGINT], [0], server_wait_errors=2)
        self.assertTrue(self.children[0].killed)
        self.assert_cleaned()

    def test_client_start_failure_closes_pipes_and_stops_server(self):
        with self.assertRaisesRegex(OSError, 'client launch failed'):
            self.run_share(client_start_error=True)
        server = self.children[0]
        self.assertTrue(server.stdin.closed)
        self.assertTrue(server.stdout.closed)
        self.assertIsNotNone(server.returncode)
        self.assertTrue(all(handler == signal.SIG_DFL for handler in self.handlers.values()))

    def test_cleanup_unmount_error_does_not_skip_children(self):
        for error in (OSError('ssh failed'), subprocess.TimeoutExpired('ssh', 20)):
            with self.subTest(error=error):
                with self.assertRaisesRegex(RuntimeError, 'loop failed'):
                    self.run_share(unmount_results=[error], loop_error=True)
                self.assert_cleaned()

    def test_interrupt_timeout_allows_retry(self):
        self.assertEqual(0, self.run_share([signal.SIGINT, signal.SIGINT],
                                         [subprocess.TimeoutExpired('ssh', 20), 0]))
        self.assertEqual(2, len(self.unmounts))
        self.assert_cleaned()
