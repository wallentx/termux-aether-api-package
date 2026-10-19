import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class ShizukuCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="shizuku-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name) / "prefix with spaces"
        (self.prefix / "bin").mkdir(parents=True)
        (self.prefix / "libexec").mkdir()
        self.marker = self.prefix / "called"
        helper = self.prefix / "libexec/termux-api"
        helper.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "' + str(self.marker) + '"\n')
        helper.chmod(0o700)
        timeout = self.prefix / "bin/timeout"
        timeout.write_text('#!/bin/sh\n[ "$1" = --foreground ] && [ "$2" = 20 ] || exit 8\nshift 2\nexec "$@"\n')
        timeout.chmod(0o700)
        template = Path(__file__).resolve().parents[1] / "scripts/termux-shizuku.in"
        self.script = self.prefix / "bin/termux-shizuku"
        self.script.write_text(template.read_text().replace("@TERMUX_PREFIX@", str(self.prefix)))

    def invoke(self, *args):
        return subprocess.run(["sh", str(self.script), *args], text=True, capture_output=True, timeout=5)

    def test_default_is_read_only_status(self):
        self.assertEqual(0, self.invoke().returncode)
        self.assertEqual(['Shizuku', '--es', 'operation', 'status'], self.marker.read_text().splitlines())

    def test_exact_operation_is_forwarded_without_a_shell_expression(self):
        for operation in ('status', 'thermal', 'request-permission'):
            for args in (("--" + operation, "--json"), ("--json", "--" + operation)):
                self.assertEqual(0, self.invoke(*args).returncode)
                self.assertEqual(['Shizuku', '--es', 'operation', operation], self.marker.read_text().splitlines())

    def test_bad_or_repeated_operations_never_contact_android(self):
        for args in (("--thermal", "--status"), ("--json", "--json"), ("shell",), ("--thermal;id",)):
            self.assertEqual(2, self.invoke(*args).returncode)
        self.assertFalse(self.marker.exists())

    def test_help_never_contacts_android(self):
        self.assertEqual(0, self.invoke('--help').returncode)
        self.assertFalse(self.marker.exists())

    def test_deadline_exit_code_is_preserved(self):
        (self.prefix / "bin/timeout").write_text('#!/bin/sh\nexit 124\n')
        self.assertEqual(124, self.invoke('--thermal').returncode)


if __name__ == '__main__':
    unittest.main()
