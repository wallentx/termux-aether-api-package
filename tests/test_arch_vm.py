import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class ArchVmCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="virtualization-", dir=os.environ.get("TMPDIR"))
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
        template = Path(__file__).resolve().parents[1] / "scripts/termux-arch-vm.in"
        self.script = self.prefix / "bin/termux-arch-vm"
        self.script.write_text(template.read_text().replace("@TERMUX_PREFIX@", str(self.prefix)))

    def invoke(self, *args):
        return subprocess.run(["sh", str(self.script), *args], text=True, capture_output=True, timeout=5)

    def test_fixed_operations_preserve_argv(self):
        for args, operation in [((), "status"), (("--status",), "status"),
                                (("--start",), "start"), (("--stop",), "stop")]:
            self.assertEqual(0, self.invoke(*args).returncode)
            self.assertEqual(["Virtualization", "--es", "operation", "arch-" + operation],
                             self.marker.read_text().splitlines())

    def test_arbitrary_commands_paths_and_multiple_operations_are_rejected(self):
        for args in (("--exec", "id"), ("--start", "--stop"), ("--start;id",),
                     ("--image=/sdcard/evil",), ("--status", "--status")):
            self.assertEqual(2, self.invoke(*args).returncode)
        self.assertFalse(self.marker.exists())

    def test_help_is_local(self):
        self.assertEqual(0, self.invoke("--help").returncode)
        self.assertFalse(self.marker.exists())

    def test_deadline_is_preserved(self):
        (self.prefix / "bin/timeout").write_text('#!/bin/sh\nexit 124\n')
        self.assertEqual(124, self.invoke().returncode)


if __name__ == "__main__":
    unittest.main()
