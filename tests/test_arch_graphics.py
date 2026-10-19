import base64
import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import call, patch


source = Path(__file__).resolve().parents[1] / 'scripts/termux-arch.in'
loader = importlib.machinery.SourceFileLoader('arch_graphics', str(source))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
KEY = 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(32)).decode()


def stopped(**changes):
    return dict(status='stopped', running=False, graphics_configurable=True,
                graphics_kernel_present=True, graphics_mode='none', **changes)


def ready(mode='gfxstream', **changes):
    report = dict(status='ready', running=True, vm_name='termux-arch-v2', ssh_port=22222,
                  ssh_host_key=KEY, graphics_configurable=True, graphics_mode=mode)
    report.update(changes)
    return report


class GraphicsReadyTest(unittest.TestCase):
    def test_api_forwards_explicit_graphics_mode_only(self):
        result = subprocess.CompletedProcess([], 0, '{}', '')
        for mode in (None, 'none', 'gfxstream'):
            with self.subTest(mode=mode), patch.object(module.subprocess, 'run', return_value=result) as run:
                module.api('start', KEY, graphics_mode=mode)
                command = run.call_args.args[0]
                if mode is None:
                    self.assertNotIn('graphics_mode', command)
                else:
                    self.assertEqual(['--es', 'graphics_mode', mode], command[-3:])

    def test_unset_graphics_preserves_legacy_reuse_or_fresh_headless(self):
        for mode in ('none', 'gfxstream'):
            with self.subTest(mode=mode), patch.object(module, 'api', return_value=ready(mode)) as api:
                self.assertEqual(mode, module.ensure_ready(KEY)['graphics_mode'])
                api.assert_called_once_with('start', KEY)

    def test_explicit_modes_are_forwarded_and_verified(self):
        for mode in ('none', 'gfxstream'):
            with self.subTest(mode=mode), patch.object(module, 'api', side_effect=[stopped(), ready(mode)]) as api:
                self.assertEqual(mode, module.ensure_ready(KEY, graphics_mode=mode)['graphics_mode'])
                self.assertEqual([call('status'), call('start', KEY, graphics_mode=mode)], api.call_args_list)

    def test_matching_running_gpu_reuses_loaded_kernel(self):
        report = ready(graphics_kernel_present=False)
        with patch.object(module, 'api', return_value=report) as api:
            self.assertEqual(report, module.ensure_ready(KEY, graphics_mode='gfxstream'))
            self.assertEqual(['status', 'start'], [c.args[0] for c in api.call_args_list])

    def test_stopped_gpu_requires_kernel_but_headless_does_not(self):
        report = stopped()
        report['graphics_kernel_present'] = False
        with patch.object(module, 'api', return_value=report) as api:
            with self.assertRaisesRegex(RuntimeError, 'Image-gfxstream'):
                module.ensure_ready(KEY, graphics_mode='gfxstream')
            api.assert_called_once_with('status')
        with patch.object(module, 'api', side_effect=[report, ready('none')]):
            self.assertEqual('none', module.ensure_ready(KEY, graphics_mode='none')['graphics_mode'])

    def test_missing_capability_and_invalid_running_state_fail_before_start(self):
        for report, message in ((dict(status='stopped', running=False), 'configurable graphics'),
                                (dict(status='ready', graphics_configurable=True), 'whether the VM is running')):
            with self.subTest(report=report), patch.object(module, 'api', return_value=report) as api:
                with self.assertRaisesRegex(RuntimeError, message):
                    module.ensure_ready(KEY, graphics_mode='gfxstream')
                api.assert_called_once_with('status')

    def test_all_incompatible_live_states_fail_before_start(self):
        for state in ('ready', 'starting', 'booting', 'suspended', 'stopping'):
            for mode in ('none', 'gfxstream'):
                with self.subTest(state=state, mode=mode), patch.object(module, 'api',
                        return_value=ready(mode, status=state)) as api:
                    requested = 'none' if mode == 'gfxstream' else 'gfxstream'
                    with self.assertRaisesRegex(RuntimeError, 'Graphics change requires a clean stop'):
                        module.ensure_ready(KEY, graphics_mode=requested)
                    api.assert_called_once_with('status')

    def test_ready_fast_path_and_polled_ready_must_confirm_requested_mode(self):
        for mode in ('none', None):
            for poll in (False, True):
                reports = [stopped()]
                if poll:
                    reports.append(dict(status='booting', running=True))
                reports.append(ready(mode))
                with self.subTest(mode=mode, poll=poll), patch.object(module, 'api', side_effect=reports), \
                     patch.object(module.time, 'sleep'), \
                     self.assertRaisesRegex(RuntimeError, 'did not apply requested graphics mode'):
                    module.ensure_ready(KEY, graphics_mode='gfxstream')

    def test_memory_and_graphics_share_one_preflight(self):
        current = stopped(memory_configurable=True)
        report = ready(memory_mib=4096)
        with patch.object(module, 'api', side_effect=[current, report]) as api:
            self.assertEqual(report, module.ensure_ready(KEY, 4096, 'gfxstream'))
            self.assertEqual([call('status'), call('start', KEY, 4096, graphics_mode='gfxstream')],
                             api.call_args_list)

    def test_previous_failed_boot_can_be_retried(self):
        current = stopped(vm_name='termux-arch-v2', reason='old_boot_failure')
        current['status'] = 'error'
        with patch.object(module, 'api', side_effect=[current, ready()]) as api:
            self.assertEqual('gfxstream', module.ensure_ready(KEY, graphics_mode='gfxstream')['graphics_mode'])
            self.assertEqual(2, api.call_count)

    def test_access_errors_precede_update_required_classification(self):
        failures = [(dict(status='unavailable', reason='binder_not_connected'), 'binder_not_connected'),
                    (dict(status='denied', authorized=False), 'not authorized'),
                    (dict(status='unsupported', reason='requires_shell_shizuku_v13'), 'requires_shell_shizuku_v13'),
                    (dict(status='error', reason='invalid_request'), 'invalid_request')]
        for report, message in failures:
            for operation in ('preferences', 'lease'):
                with self.subTest(report=report, operation=operation), \
                     patch.object(module, 'api', return_value=report) as api:
                    with self.assertRaisesRegex(RuntimeError, message) as caught:
                        if operation == 'preferences':
                            module.check_preferences(graphics_mode='gfxstream')
                        else:
                            with module.vm_session():
                                self.fail('Must not acquire denied session')
                    self.assertNotIn('update', str(caught.exception).lower())
                    self.assertEqual(1, api.call_count)

    def test_start_rejections_keep_their_cause(self):
        for reason, message in [('graphics_change_requires_stop', 'Graphics change requires a clean stop'),
                                ('graphics_kernel_missing', 'graphics_kernel_missing'),
                                ('binder_not_connected', 'binder_not_connected')]:
            response = dict(status='error', reason=reason)
            with self.subTest(reason=reason), patch.object(module, 'api', side_effect=[stopped(), response]), \
                 self.assertRaisesRegex(RuntimeError, message):
                module.ensure_ready(KEY, graphics_mode='gfxstream')


class GraphicsMainTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.credentials_dir = self.root / '.config/termux/arch-vm'
        self.credentials_dir.mkdir(parents=True)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(module.Path, 'home', return_value=self.root))
        self.stack.enter_context(patch.object(module.shutil, 'which', return_value='/test/bin'))
        self.stack.enter_context(patch.object(module, 'credentials', return_value=(self.root / 'identity', KEY)))
        self.config = dict(module.DEFAULT_CONFIG, user='alarm', graphics_mode='gfxstream')
        self.stack.enter_context(patch.object(module, 'load_config', return_value=self.config))
        self.stack.enter_context(patch.object(module, 'pin_host', return_value=self.root / 'known_hosts'))
        self.api = self.stack.enter_context(patch.object(module, 'api'))
        self.ssh = self.stack.enter_context(patch.object(module, 'run_ssh', return_value=0))

    def assert_startup_lock_held(self):
        with (self.credentials_dir / 'startup.lock').open('r+') as stream:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_mismatch_rejects_without_lease_or_guest_command(self):
        self.api.return_value = ready('none')
        with self.assertRaisesRegex(RuntimeError, 'clean stop'):
            module.main(['--', 'true'])
        self.api.assert_called_once_with('status')
        self.ssh.assert_not_called()

    def test_shared_context_keeps_lease_through_caller_and_releases_on_error(self):
        self.api.side_effect = [stopped(),
                               dict(session_lifecycle=True, session_status='acquired'),
                               ready(), dict(session_status='released', running=False)]
        with self.assertRaisesRegex(ValueError, 'caller failed'):
            with module.ready_vm(self.credentials_dir, KEY, graphics_mode='gfxstream') as report:
                self.assertEqual('gfxstream', report['graphics_mode'])
                self.assertEqual(['status', 'session-acquire', 'start'],
                                 [c.args[0] for c in self.api.call_args_list])
                with (self.credentials_dir / 'startup.lock').open('r+') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                raise ValueError('caller failed')
        self.assertEqual(['status', 'session-acquire', 'start', 'session-release'],
                         [c.args[0] for c in self.api.call_args_list])

    def test_capability_or_kernel_error_has_no_lease_side_effect(self):
        for report in (dict(status='stopped', running=False),
                       dict(status='stopped', running=False, graphics_configurable=True)):
            with self.subTest(report=report):
                self.api.reset_mock()
                self.api.return_value = report
                with self.assertRaises(RuntimeError):
                    module.main(['--', 'true'])
                self.api.assert_called_once_with('status')
                self.ssh.assert_not_called()

    def test_lock_covers_preflight_acquire_start_but_not_guest_command(self):
        def respond(operation, *_args, **kwargs):
            if operation != 'session-release':
                self.assert_startup_lock_held()
            if operation == 'status':
                return stopped()
            if operation == 'session-acquire':
                self.assertTrue(kwargs['keep_memory'])
                return dict(session_lifecycle=True, session_status='acquired')
            if operation == 'start':
                self.assertEqual('gfxstream', kwargs['graphics_mode'])
                return ready()
            if operation == 'session-release':
                return dict(session_status='released', running=False)
            self.fail(f'Unexpected API operation: {operation}')

        def execute(invocation):
            with (self.credentials_dir / 'startup.lock').open('r+') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual('root@127.0.0.1', invocation[-2])
            self.assertEqual(module.remote_command(None, ['printf', 'two words'], 'alarm'), invocation[-1])
            return 37

        self.api.side_effect = respond
        self.ssh.side_effect = execute
        self.assertEqual(37, module.main(['--keep-memory', '--', 'printf', 'two words']))
        self.assertEqual(['status', 'session-acquire', 'start', 'session-release'],
                         [c.args[0] for c in self.api.call_args_list])

    def test_standalone_start_holds_lock_without_acquiring_a_lease(self):
        def respond(operation, *_args, **_kwargs):
            self.assert_startup_lock_held()
            return stopped() if operation == 'status' else ready()
        self.api.side_effect = respond
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, module.main(['--start']))
        self.assertEqual('gfxstream', json.loads(output.getvalue())['graphics_mode'])
        self.assertEqual(['status', 'start'], [c.args[0] for c in self.api.call_args_list])
        self.ssh.assert_not_called()

    def test_null_preference_still_serializes_startup(self):
        self.config['graphics_mode'] = None

        def respond(operation, *_args, **kwargs):
            if operation == 'session-acquire':
                self.assert_startup_lock_held()
                return dict(session_lifecycle=True, session_status='acquired')
            if operation == 'start':
                self.assert_startup_lock_held()
                self.assertNotIn('graphics_mode', kwargs)
                return ready('none')
            if operation == 'session-release':
                return dict(session_status='released', running=False)
            self.fail(f'Unexpected API operation: {operation}')
        self.api.side_effect = respond
        self.assertEqual(0, module.main(['--', 'true']))


if __name__ == '__main__':
    unittest.main()
