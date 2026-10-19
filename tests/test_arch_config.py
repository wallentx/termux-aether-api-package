import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


source = Path(__file__).resolve().parents[1] / 'scripts/termux-arch.in'
loader = importlib.machinery.SourceFileLoader('arch_config', str(source))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

DEFAULTS = {
    'user': 'root',
    'cwd': None,
    'memory': None,
    'graphics_mode': None,
    'keep_memory': False,
    'tty': None,
}
YQ = shutil.which('yq')


class ConfigPathTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name) / 'home'

    def test_absolute_xdg_directory_is_used(self):
        config = Path(self.directory.name) / 'config with spaces'
        with patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(config)}):
            self.assertEqual(config / 'termux-arch/config.yml', module.config_path())

    def test_unset_empty_or_relative_xdg_uses_home_config(self):
        for value in (None, '', 'relative/config'):
            with self.subTest(value=value), patch.dict(os.environ, {'HOME': str(self.home)}):
                if value is None:
                    os.environ.pop('XDG_CONFIG_HOME', None)
                else:
                    os.environ['XDG_CONFIG_HOME'] = value
                self.assertEqual(self.home / '.config/termux-arch/config.yml', module.config_path())


@unittest.skipUnless(YQ, 'mikefarah yq is needed for YAML integration tests')
class ConfigFileTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {
            'HOME': str(self.root / 'home'),
            'XDG_CONFIG_HOME': str(self.root / 'configuration'),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.path = self.root / 'configuration/termux-arch/config.yml'

    def write_config(self, contents):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(contents)

    def test_first_load_creates_all_defaults_with_private_permissions(self):
        self.assertEqual(DEFAULTS, module.load_config())
        self.assertTrue(self.path.is_file())
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        result = subprocess.run([YQ, '-p=yaml', '-o=json', '-I=0', '.', str(self.path)],
                                capture_output=True, text=True, check=True)
        self.assertEqual(DEFAULTS, json.loads(result.stdout))
        self.assertEqual(DEFAULTS, module.load_config())

    def test_partial_config_is_merged_without_rewriting_user_content(self):
        contents = '# User preferences must survive loading.\nuser: alice\nkeep_memory: true\n'
        self.write_config(contents)
        before = self.path.stat()
        self.assertEqual(dict(DEFAULTS, user='alice', keep_memory=True), module.load_config())
        self.assertEqual(contents, self.path.read_text())
        self.assertEqual(before.st_ino, self.path.stat().st_ino)
        self.assertEqual(before.st_mtime_ns, self.path.stat().st_mtime_ns)

    def test_configured_size_and_quoted_guest_path_are_parsed(self):
        self.write_config('user: alice\ncwd: "/home/alice/project with spaces"\n'
                          'memory: 1.5G\nkeep_memory: true\ntty: false\n')
        options = module.parse_options(['--', 'printf', 'literal argument'])
        self.assertEqual('alice', options.user)
        self.assertEqual('/home/alice/project with spaces', options.cwd)
        self.assertEqual(1536, options.memory)
        self.assertTrue(options.keep_memory)
        self.assertIs(options.tty, False)
        self.assertEqual(['printf', 'literal argument'], options.command)

    def test_unknown_duplicate_and_invalid_yaml_are_rejected(self):
        invalid = (
            'unknown_setting: true\n',
            'user: alice\nuser: root\n',
            '- user\n- root\n',
            'user: [\n',
            'user: root\n---\nuser: alice\n',
        )
        for contents in invalid:
            with self.subTest(contents=contents):
                self.write_config(contents)
                with self.assertRaises((ValueError, RuntimeError)):
                    module.load_config()
                self.assertEqual(contents, self.path.read_text())

    def test_invalid_config_values_are_rejected_before_credentials_or_vm_access(self):
        invalid = (
            'user: null\n',
            'user: 123\n',
            'user: "-root"\n',
            'user: "alice; id"\n',
            'cwd: relative/path\n',
            'cwd: 123\n',
            'memory: true\n',
            'memory: -1\n',
            'graphics_mode: virgl\n',
            'graphics_mode: true\n',
            'graphics_mode: [gfxstream]\n',
            'keep_memory: "true"\n',
            'tty: 1\n',
        )
        for contents in invalid:
            with self.subTest(contents=contents):
                self.write_config(contents)
                with patch.object(module, 'credentials') as credentials, \
                     patch.object(module, 'api') as api, \
                     patch.object(module, 'run_ssh') as ssh, \
                     contextlib.redirect_stderr(io.StringIO()), \
                     self.assertRaises((ValueError, RuntimeError, SystemExit)):
                    module.main(['--', 'true'])
                credentials.assert_not_called()
                api.assert_not_called()
                ssh.assert_not_called()

    def test_oversized_config_is_rejected_before_yaml_subprocess(self):
        self.write_config('#' * (64 * 1024 + 1))
        with patch.object(module.subprocess, 'run') as run, \
             self.assertRaises((ValueError, RuntimeError)):
            module.load_config()
        run.assert_not_called()


class ConfigOptionsTest(unittest.TestCase):
    def parse(self, argv, **preferences):
        with patch.object(module, 'load_config', return_value=dict(DEFAULTS, **preferences)):
            return module.parse_options(argv)

    def test_default_options_use_guest_home_without_reading_host_cwd(self):
        with patch.object(module.Path, 'cwd', side_effect=AssertionError('must not map host cwd')):
            options = self.parse(['--', 'op'])
        self.assertEqual('root', options.user)
        self.assertIsNone(options.cwd)
        self.assertIsNone(options.memory)
        self.assertIsNone(options.graphics_mode)
        self.assertFalse(options.keep_memory)
        self.assertIs(options.tty, False)
        self.assertEqual(['op'], options.command)

    def test_cli_overrides_every_persistent_option(self):
        options = self.parse(['--user', 'bob', '--cwd', '/srv/bob', '--memory', '2G',
                              '--graphics-mode', 'none', '--no-keep-memory', '--no-tty', '--', 'true'],
                             user='alice', cwd='/home/alice', memory=1024,
                             graphics_mode='gfxstream', keep_memory=True, tty=True)
        self.assertEqual('bob', options.user)
        self.assertEqual('/srv/bob', options.cwd)
        self.assertEqual(2048, options.memory)
        self.assertEqual('none', options.graphics_mode)
        self.assertIs(options.keep_memory, False)
        self.assertIs(options.tty, False)

    def test_positive_flags_override_disabled_defaults(self):
        options = self.parse(['--keep-memory', '--tty', '--', 'true'], tty=False)
        self.assertIs(options.keep_memory, True)
        self.assertIs(options.tty, True)

    def test_graphics_defaults_and_overrides(self):
        for mode in (None, 'none', 'gfxstream'):
            with self.subTest(mode=mode):
                self.assertEqual(mode, self.parse(['--', 'true'], graphics_mode=mode).graphics_mode)
        self.assertEqual('gfxstream', self.parse(['--graphics-mode', 'gfxstream'],
                                                 graphics_mode='none').graphics_mode)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parse(['--graphics-mode', 'invalid'])

    def test_guest_argv_stays_literal_after_separator_or_command_name(self):
        guest = ['op', '--user', 'guest flag', '--cwd', '/literal', '--memory', 'invalid',
                 '--graphics-mode', 'guest graphics', '--keep-memory', '--no-tty',
                 '--', '', 'two words', '$(touch nope)']
        for argv in (guest, ['--', *guest]):
            with self.subTest(argv=argv):
                options = self.parse(argv)
                self.assertEqual(guest, options.command)
                self.assertEqual('root', options.user)
                self.assertIsNone(options.cwd)
                self.assertIsNone(options.memory)
                self.assertIsNone(options.graphics_mode)
                self.assertFalse(options.keep_memory)
                self.assertIs(options.tty, False)

    def test_automatic_tty_is_for_shells_and_can_be_disabled(self):
        self.assertIs(self.parse([]).tty, True)
        self.assertIs(self.parse(['--shell']).tty, True)
        self.assertIs(self.parse(['--shell', '--no-tty']).tty, False)
        self.assertIs(self.parse(['--shell'], tty=False).tty, False)
        self.assertIs(self.parse(['--', 'true'], tty=True).tty, True)

    def test_start_accepts_configured_keep_memory_but_rejects_explicit_flag(self):
        options = self.parse(['--start'], keep_memory=True)
        self.assertTrue(options.start)
        self.assertFalse(options.keep_memory)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.parse(['--start', '--keep-memory'])
        self.assertEqual(2, error.exception.code)

    def test_start_and_shell_actions_keep_their_argument_constraints(self):
        for argv in (['--shell', '--', 'true'], ['--start', '--shell'], ['--start', '--', 'true']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit) as error:
                self.parse(argv)
            self.assertEqual(2, error.exception.code)


class GuestUserTest(unittest.TestCase):
    def test_root_default_cwd_expands_remote_home_without_splitting(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as work:
            home = Path(work) / 'root home'
            home.mkdir()
            result = subprocess.run(['bash', '-c', module.remote_command(None, ['pwd'])],
                                    capture_output=True, text=True,
                                    env=dict(os.environ, HOME=str(home)))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(str(home) + '\n', result.stdout)

    def test_nonroot_command_preserves_literal_argv_and_uses_selected_home(self):
        arguments = ['', 'two words', "single'quote", '$(touch must-not-exist)',
                     ';exit 9', '*', 'line\nbreak', '--user', 'root']
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as work:
            guest_home = Path(work) / 'home with spaces'
            guest_home.mkdir()
            command = module.remote_command(None, ['printf', r'%s\0', *arguments], user='alice')
            invocation = shlex.split(command)
            self.assertEqual(['exec', '/usr/bin/runuser', '--user', 'alice', '--',
                              '/bin/bash', '-c'], invocation[:7])
            # Execute only the nested shell, with a simulated guest HOME; no runuser
            # or SSH command is run on the test host.
            result = subprocess.run(['bash', '-c', *invocation[7:]], capture_output=True,
                                    env=dict(os.environ, HOME=str(guest_home)))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(b'\0'.join(arg.encode() for arg in arguments) + b'\0', result.stdout)
            self.assertFalse((guest_home / 'must-not-exist').exists())

    def test_guest_home_and_explicit_cwd_are_resolved_in_selected_user_shell(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as work:
            home = Path(work) / 'guest home'
            explicit = Path(work) / "guest's project"
            home.mkdir()
            explicit.mkdir()
            for cwd, expected in ((None, home), (str(explicit), explicit)):
                with self.subTest(cwd=cwd):
                    invocation = shlex.split(module.remote_command(cwd, ['pwd'], user='alice'))
                    result = subprocess.run(['bash', '-c', *invocation[7:]], capture_output=True,
                                            text=True, env=dict(os.environ, HOME=str(home)))
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(str(expected) + '\n', result.stdout)

    def test_user_switch_failure_never_runs_command_as_transport_user(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as work:
            stub = Path(work) / 'runuser'
            stub.write_text('#!/bin/sh\nexit 77\n')
            stub.chmod(0o700)
            command = module.remote_command(None, ['printf', 'must not execute'], user='missing')
            self.assertTrue(command.startswith('exec /usr/bin/runuser '))
            simulated = command.replace('/usr/bin/runuser', shlex.quote(str(stub)), 1)
            result = subprocess.run(['bash', '-c', simulated], capture_output=True)
            self.assertEqual(77, result.returncode)
            self.assertEqual(b'', result.stdout)

    def test_ssh_authentication_stays_root_while_execution_selects_guest_user(self):
        invocation = module.ssh_command('/key', '/known', 2222, None, ['true'], False, user='alice')
        self.assertEqual('root@127.0.0.1', invocation[-2])
        self.assertEqual(module.remote_command(None, ['true'], user='alice'), invocation[-1])


if __name__ == '__main__':
    unittest.main()
