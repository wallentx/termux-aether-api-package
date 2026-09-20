#!/usr/bin/env python3
"""Build a native aarch64 Pacman package without modifying the installed prefix."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '/data/data/com.termux/files/usr'


def main():
    if subprocess.check_output(['uname', '-m'], text=True).strip() != 'aarch64' or not Path('/system/bin/app_process').exists():
        raise SystemExit('Build this package in native aarch64 Termux.')
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise SystemExit('VERSION must contain major.minor.patch')
    build = ROOT / 'build/aether'
    output = ROOT / 'build/packages'
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(['cmake', '-S', str(ROOT), '-B', str(build),
                    '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', '-DCMAKE_BUILD_TYPE=Release',
                    f'-DCMAKE_INSTALL_PREFIX={PREFIX}'], check=True)
    subprocess.run(['cmake', '--build', str(build), '--parallel', '4'], check=True)
    with tempfile.TemporaryDirectory(prefix='aether-api-package-') as tmp:
        stage = Path(tmp)
        subprocess.run(['cmake', '--install', str(build)], env=dict(os.environ, DESTDIR=tmp), check=True)
        licenses = stage / PREFIX.lstrip('/') / 'share/licenses/termux-aether-api'
        licenses.mkdir(parents=True)
        shutil.copy2(ROOT / 'LICENSE', licenses / 'LICENSE')
        size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file() and not p.is_symlink())
        metadata = [
            'pkgname = termux-aether-api', 'pkgbase = termux-aether-api',
            f'pkgver = 1:{version}-1', 'pkgdesc = Termux-Aether API and Arch VM commands',
            'url = https://github.com/wallentx/termux-aether-api-package',
            f'builddate = {int(time.time())}', 'packager = wallentx <william.allentx@gmail.com>',
            f'size = {size}', 'arch = aarch64', 'license = MIT',
            f'provides = termux-api={version}', 'conflict = termux-api',
            'depend = bash', 'depend = util-linux', 'depend = termux-am>=0.8.0',
            'depend = python', 'depend = openssh', 'depend = termux-aether-exec>=1:1000.0.0',
            'optdepend = rclone: host directory sharing with the Arch guest',
        ]
        (stage / '.PKGINFO').write_text('\n'.join(metadata) + '\n')
        archive = output / f'termux-aether-api-{version}-1-aarch64.pkg.tar.xz'
        def owner(info):
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            return info
        with tarfile.open(archive, 'w:xz', format=tarfile.PAX_FORMAT) as tf:
            for name in ['.PKGINFO', 'data']:
                tf.add(stage / name, arcname=name, filter=owner)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_suffix('.xz.sha256').write_text(f'{digest}  {archive.name}\n')
        print(archive)


if __name__ == '__main__':
    main()
