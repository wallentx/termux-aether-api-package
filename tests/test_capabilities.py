import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class CapabilitiesCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="capabilities-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name) / "prefix with spaces"
        (self.prefix / "bin").mkdir(parents=True)
        (self.prefix / "libexec").mkdir()
        self.marker = self.prefix / "called"
        helper = self.prefix / "libexec/termux-api"
        helper.write_text('#!/bin/sh\n[ "$#" = 1 ] && [ "$1" = Capabilities ] || exit 9\n'
                          'touch "' + str(self.marker) + '"\nprintf \'{"schema_version":1}\\n\'\n')
        helper.chmod(0o700)
        timeout = self.prefix / "bin/timeout"
        timeout.write_text('#!/bin/sh\n[ "$1" = --foreground ] && [ "$2" = 15 ] || exit 8\nshift 2\nexec "$@"\n')
        timeout.chmod(0o700)
        template = Path(__file__).resolve().parents[1] / "scripts/termux-capabilities.in"
        self.script = self.prefix / "bin/termux-capabilities"
        self.script.write_text(template.read_text().replace("@TERMUX_PREFIX@", str(self.prefix)))

    def invoke(self, *args):
        return subprocess.run(["sh", str(self.script), *args], text=True, capture_output=True, timeout=5)

    def test_default_and_json_forward_the_correct_method(self):
        for args in ((), ("--json",)):
            result = self.invoke(*args)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('{"schema_version":1}\n', result.stdout)
            self.assertTrue(self.marker.exists())

    def test_help_does_not_contact_android(self):
        for flag in ("-h", "--help"):
            self.assertEqual(0, self.invoke(flag).returncode)
        self.assertFalse(self.marker.exists())

    def test_invalid_arguments_do_not_contact_android(self):
        for args in (("--unknown",), ("--json", "extra"), ("--json", "--json")):
            self.assertEqual(2, self.invoke(*args).returncode)
        self.assertFalse(self.marker.exists())

    def test_timeout_exit_status_is_preserved(self):
        (self.prefix / "bin/timeout").write_text('#!/bin/sh\nexit 124\n')
        self.assertEqual(124, self.invoke().returncode)


if __name__ == "__main__":
    unittest.main()
