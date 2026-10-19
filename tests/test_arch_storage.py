import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


loader = importlib.machinery.SourceFileLoader('arch_resources_test',
    str(Path(__file__).resolve().parents[1] / 'scripts/termux-arch-resources.in'))
spec = importlib.util.spec_from_loader(loader.name, loader)
resources = importlib.util.module_from_spec(spec)
loader.exec_module(resources)


class SharedStorageCli(unittest.TestCase):
    def invoke(self, args, status=None, response=None):
        if status is None:
            status = {'shared_storage_supported': True, 'running': False, 'active_sessions': 0}
        if response is None:
            response = dict(status, status='stopped')
        api = mock.Mock(side_effect=[status, response])
        arch = SimpleNamespace(api=api, memory_mib=int)
        with mock.patch.object(resources, 'load_arch', return_value=arch), \
             mock.patch.object(Path, 'mkdir') as mkdir, \
             mock.patch.object(Path, 'resolve', return_value=Path(resources.DEFAULT_SHARE)), \
             contextlib.redirect_stdout(io.StringIO()):
            result = resources.main(args)
        return result, api, mkdir

    def test_default_enable_and_disable_are_explicit(self):
        result, api, mkdir = self.invoke(['--share-enable'])
        self.assertEqual(result, 0)
        api.assert_called_with('share-configure', shared_path=resources.DEFAULT_SHARE)
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        result, api, mkdir = self.invoke(['--share-disable'])
        self.assertEqual(result, 0)
        api.assert_called_with('share-configure', shared_path='')
        mkdir.assert_not_called()

    def test_running_unsupported_and_sessions_block_configuration(self):
        for status in ({}, {'shared_storage_supported': True, 'running': True, 'active_sessions': 0},
                       {'shared_storage_supported': True, 'running': False, 'active_sessions': 1}):
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                self.invoke(['--share-enable'], status)

    def test_path_boundary_and_spaces(self):
        valid = '/storage/emulated/0/Documents/My Files'
        self.assertEqual(resources.shared_folder(valid), valid)
        for invalid in ('/data/data/com.termux/files/home', '/storage/emulated/0/../1/files',
                        '/storage/emulated/0/a//b', '/storage/emulated/0/a/./b',
                        '/storage/emulated/0/a\n', '/storage/emulated/0/a/'):
            with self.subTest(path=invalid), self.assertRaises(argparse.ArgumentTypeError):
                resources.shared_folder(invalid)

    def test_api_error_is_not_reported_as_success(self):
        result, _, _ = self.invoke(['--share-disable'], response={
            'shared_storage_supported': True, 'status': 'error', 'reason': 'guest_already_owned'})
        self.assertEqual(result, 1)


class DiskGrowthCli(unittest.TestCase):
    def invoke(self, config_memory=None, graphics_mode=None, resize_returncode=0, config_error=None):
        arch = mock.Mock()
        arch.api.side_effect = [
            {'filesystem_growth_required': True},
            {'status': 'stopped', 'running': False},
        ]
        arch.load_config.return_value = {'memory': config_memory, 'graphics_mode': graphics_mode,
                                         'keep_memory': True, 'user': 'alarm', 'cwd': '/home/alarm'}
        arch.load_config.side_effect = config_error
        arch.memory_mib.side_effect = lambda value: {
            '16384': 16384, '8G': 8192, '8192': 8192}[value]
        arch.credentials.return_value = ('identity', 'key')
        arch.ready_vm.side_effect = lambda *args, **kwargs: contextlib.nullcontext({
            'ssh_host_key': 'host', 'ssh_port': 22})
        arch.pin_host.return_value = 'known'
        arch.ssh_command.return_value = ['ssh', 'resize2fs', '/dev/vda']
        self.arch = arch
        with mock.patch.object(resources, 'load_arch', return_value=arch), \
             mock.patch.object(Path, 'home', return_value=Path('/host-home')), \
             mock.patch.object(resources.subprocess, 'run',
                               return_value=SimpleNamespace(returncode=resize_returncode)) as run, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            result = resources.main(['--grow-disk', '16384'])
        return result, arch, run, output.getvalue()

    def test_growth_boot_applies_saved_graphics_and_memory_as_root(self):
        for memory in ('8G', 8192):
            with self.subTest(memory=memory):
                result, arch, run, output = self.invoke(memory, 'gfxstream')
                self.assertEqual(0, result)
                arch.load_config.assert_called_once_with()
                self.assertEqual([mock.call('16384'), mock.call(str(memory))], arch.memory_mib.call_args_list)
                arch.ready_vm.assert_called_once_with(Path('/host-home/.config/termux/arch-vm'), 'key',
                    memory=8192, graphics_mode='gfxstream')
                arch.vm_session.assert_not_called()
                arch.ensure_ready.assert_not_called()
                arch.ssh_command.assert_called_once_with('identity', 'known', 22, '/',
                    ['resize2fs', '/dev/vda'], False)
                self.assertEqual(120, run.call_args.kwargs['timeout'])
                self.assertIn('"filesystem_growth_completed": true', output)
                self.assertEqual([mock.call('disk-grow', disk_bytes=16384 * 1024 * 1024),
                                  mock.call('status')], arch.api.call_args_list)

    def test_growth_without_saved_preferences_keeps_release_on_exit(self):
        result, arch, _, _ = self.invoke()
        self.assertEqual(0, result)
        arch.ready_vm.assert_called_once_with(Path('/host-home/.config/termux/arch-vm'), 'key',
            memory=None, graphics_mode=None)
        arch.memory_mib.assert_called_once_with('16384')

    def test_invalid_config_fails_before_capacity_changes(self):
        with self.assertRaisesRegex(ValueError, 'Invalid config'):
            self.invoke(config_error=ValueError('Invalid config'))
        self.arch.api.assert_not_called()
        self.arch.ready_vm.assert_not_called()

    def test_resize_failure_is_reported_without_claiming_completion(self):
        with self.assertRaisesRegex(RuntimeError, 'ext4 growth failed'):
            self.invoke(resize_returncode=1)
        self.arch.api.assert_called_once_with('disk-grow', disk_bytes=16384 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
