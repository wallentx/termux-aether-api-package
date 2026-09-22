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


if __name__ == '__main__':
    unittest.main()
