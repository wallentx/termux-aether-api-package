#!/usr/bin/env python3
"""Exercise an enabled Arch Virtio-FS share on the Pixel; start with Arch stopped."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def status():
    return json.loads(subprocess.check_output(['termux-arch-vm', '--status'], text=True, timeout=25))


def settled(keep=False):
    deadline = time.monotonic() + 30
    while True:
        value = status()
        if value.get('reason') or value.get('idle_error'):
            raise RuntimeError(json.dumps(value))
        done = value.get('suspended') is True if keep else value.get('running') is False
        if done:
            return value
        if time.monotonic() >= deadline:
            raise TimeoutError(json.dumps(value))
        time.sleep(.25)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path.home() / 'arch-storage-results.json')
    args = parser.parse_args()
    initial = status()
    if initial.get('running') is not False or initial.get('shared_storage_enabled') is not True:
        raise RuntimeError('Requires a stopped VM with --share-enable already configured')
    host = Path(initial['shared_storage_host_path'])
    fixture = Path(tempfile.mkdtemp(prefix='.aether-storage-test-', dir=host))
    guest = '/mnt/android/' + fixture.name
    report = {'passed': False, 'uid': os.getuid(), 'host_folder': str(host),
              'fixture': str(fixture), 'checks': []}
    disabled = False

    def run(name, command, expected=0):
        result = subprocess.run(command, text=True, capture_output=True, timeout=90)
        report['checks'].append({'name': name, 'exit': result.returncode,
                                 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode != expected:
            raise RuntimeError(f'{name}: expected {expected}, got {result.returncode}: {result.stderr}')
        return result

    def arch(name, script, keep=False):
        return run(name, ['termux-arch', '--cwd', '/root', *(['--keep-memory'] if keep else []),
                          '--', 'bash', '-ceu', script, 'storage-test', guest])

    try:
        (fixture / 'host.txt').write_text('from-host-v1\n')
        arch('mount_and_bidirectional_write', '''
test "$(findmnt -rn -M /mnt/android -o FSTYPE)" = virtiofs
findmnt -rn -M /mnt/android -o SOURCE,FSTYPE,OPTIONS
test "$(cat "$1/host.txt")" = from-host-v1
printf 'from-guest-v1\\n' > "$1/pending.txt"
sync -f "$1/pending.txt"
mv "$1/pending.txt" "$1/guest.txt"
''', keep=True)
        first = settled(keep=True)
        assert first['shared_storage_mounted'] is True
        assert (fixture / 'guest.txt').read_text() == 'from-guest-v1\n'
        assert not (fixture / 'pending.txt').exists()
        report['suspended'] = first
        run('reject_configuration_while_suspended', ['termux-arch-vm', '--share-disable'], expected=1)
        with (fixture / 'host.txt').open('w') as output:
            output.write('from-host-v2\n'); output.flush(); os.fsync(output.fileno())
        arch('resume_and_host_edit', 'test "$(cat "$1/host.txt")" = from-host-v2; cat "$1/guest.txt"', keep=True)
        resumed = settled(keep=True)
        assert resumed['cid'] == first['cid']
        arch('default_release', 'test "$(cat "$1/guest.txt")" = from-guest-v1')
        stopped = settled()
        assert stopped['clean_shutdown'] is True
        assert 'TERMUX_ARCH_SHARED_UNMOUNTED_V1' in stopped['console_tail']
        assert stopped['shared_storage_mounted'] is False
        report['shutdown'] = stopped
        arch('restart_persistence', 'test "$(cat "$1/host.txt")" = from-host-v2; test "$(cat "$1/guest.txt")" = from-guest-v1')
        settled()
        run('disable', ['termux-arch-vm', '--share-disable']); disabled = True
        arch('disabled_boot_has_no_mount', '! mountpoint -q /mnt/android')
        off = settled()
        assert off['shared_storage_enabled'] is False and off['shared_storage_mounted'] is False
        assert (fixture / 'guest.txt').read_text() == 'from-guest-v1\n'
        run('restore_original_folder', ['termux-arch-vm', '--share-enable', str(host)]); disabled = False
        arch('reenable', 'test "$(cat "$1/guest.txt")" = from-guest-v1')
        report['final'] = settled()
        assert report['final']['clean_shutdown'] is True
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if disabled:
            # Only restore configuration after an ordinary clean stop; never force.
            subprocess.run(['termux-arch-vm', '--stop'], capture_output=True, timeout=25)
            if status().get('running') is False:
                subprocess.run(['termux-arch-vm', '--share-enable', str(host)], capture_output=True, timeout=25)
        if report['passed']:
            shutil.rmtree(fixture)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(args.output, flush=True)


if __name__ == '__main__':
    main()
