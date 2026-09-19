#!/usr/bin/env python3
"""Run inside Pixel Termux; requires an idle, stopped Arch VM. Never force-stops it."""
import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path


def status():
    result = subprocess.run(['termux-arch-vm', '--status'], capture_output=True, text=True, timeout=25, check=True)
    return json.loads(result.stdout)


def wait_for(predicate, seconds=30):
    end = time.monotonic() + seconds
    while True:
        state = status()
        if predicate(state):
            return state
        if state.get('idle_error') or state.get('reason'):
            raise RuntimeError(json.dumps(state))
        if time.monotonic() >= end:
            raise TimeoutError(json.dumps(state))
        time.sleep(.5)


def command(*args, keep=False):
    return ['termux-arch', '--cwd', '/root', *(['--keep-memory'] if keep else []), '--', *args]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path.home() / 'arch-lifecycle-results.json')
    args = parser.parse_args()
    report = {'started_at': time.time(), 'checks': []}
    processes = []
    try:
        initial = status()
        report['initial'] = initial
        if initial.get('running') or initial.get('session_lifecycle') is not True:
            raise RuntimeError('Requires the updated API and a stopped guest; existing sessions were not changed')
        run = subprocess.run(command('sh', '-c', 'exit 37'), capture_output=True, text=True, timeout=90)
        assert run.returncode == 37, (run.returncode, run.stderr)
        state = wait_for(lambda s: not s.get('running'))
        assert state.get('clean_shutdown'), state
        report['checks'].append({'check': 'exit_status_and_default_shutdown', 'status': state})

        first = subprocess.Popen(command('sleep', '12'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(first)
        ready = wait_for(lambda s: s.get('status') == 'ready' and s.get('active_sessions') == 1)
        second = subprocess.Popen(command('sleep', '22'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(second)
        overlap = wait_for(lambda s: s.get('active_sessions') == 2)
        first.communicate(timeout=60)
        assert first.returncode == 0
        remaining = status()
        assert remaining.get('running') and remaining.get('active_sessions') == 1, remaining
        second.communicate(timeout=60)
        assert second.returncode == 0
        end = wait_for(lambda s: not s.get('running'))
        report['checks'].append({'check': 'overlap', 'both': overlap, 'one': remaining, 'end': end})

        token = uuid.uuid4().hex
        run = subprocess.run(command('sh', '-c', 'curl --fail --silent --show-error --retry 10 --retry-all-errors --retry-delay 1 --max-time 5 https://example.com -o /dev/null && printf %s "$1" > /run/termux-retention-check', 'sh', token, keep=True),
                             capture_output=True, text=True, timeout=90)
        assert run.returncode == 0, run.stderr
        asleep = wait_for(lambda s: s.get('suspended') is True)
        started = time.monotonic()
        run = subprocess.run(command('cat', '/run/termux-retention-check', keep=True), capture_output=True, text=True, timeout=90)
        assert run.returncode == 0 and run.stdout == token, (run.stdout, run.stderr)
        resumed = wait_for(lambda s: s.get('suspended') is True)
        assert resumed['cid'] == asleep['cid'], (asleep, resumed)
        report['checks'].append({'check': 'suspend_resume', 'before': asleep, 'after': resumed,
                                 'command_and_resuspend_seconds': time.monotonic() - started})
        run = subprocess.run(command('sh', '-c', 'curl --fail --max-time 30 -o /dev/null -s -w "%{http_code}" https://example.com'),
                             capture_output=True, text=True, timeout=90)
        assert run.returncode == 0 and run.stdout == '200', (run.stdout, run.stderr)
        final = wait_for(lambda s: not s.get('running'))
        assert final.get('clean_shutdown'), final
        report['checks'].append({'check': 'network_after_resume_and_default_release', 'status': final})
        report['passed'] = True
    except BaseException as error:
        report['passed'] = False
        report['error'] = repr(error)
        raise
    finally:
        # Reap only test clients; their leases own guest cleanup. Never force the VM.
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=25)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
        report['finished_at'] = time.time()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(args.output, flush=True)


if __name__ == '__main__':
    main()
