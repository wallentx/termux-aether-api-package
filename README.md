# Termux-Æther CLI companion

Coordinated suite releases: [installation, upgrades and component dependencies](https://github.com/wallentx/termux-aether-app/blob/dev/docs/RELEASES.md). The `v1000.0.0` baseline keeps existing app IDs and data paths.

Shell commands for [Termux-Æther:API](https://github.com/wallentx/termux-aether-api),
including device capabilities, Shizuku diagnostics, Arch VM control, and live
project sharing. This fork retains the upstream Termux:API command wrappers.
Use the `dev` branch with the matching companion APK; the APK
and this command package are separate installations. See the API README for
[setup and requirements](https://github.com/wallentx/termux-aether-api#setup).

`dev` is the default development branch. `master` is reserved for unchanged
upstream syncs; rebase `dev` onto it after syncing. The permanent draft **Sync PR**
from `dev` to `master` is for reviewing the fork delta, including on-demand
Copilot reviews, and is never intended to be merged.

### Fresh Arch AVF workspace

With the matching Termux:API fork, staged v2 guest image, authorized shell Shizuku,
and Termux `python` and `openssh` packages:

```sh
Æ                                  # Interactive guest shell
æ uname -a                         # Inline command from Termux home
termux-arch --cwd /root -- ls -la    # Explicit guest directory
termux-arch-vm --stop               # Flush, remount read-only and shut down
```

The ext4 filesystem is writable and persistent across shutdowns. These commands
use authenticated SSH over vsock. Guest IPv4 networking is available through the
userspace bridge; selected-directory sharing is available through `termux-arch-share` below. A command from a host directory other
than Termux home requires an explicit guest `--cwd`. Install the wrappers only on
the intended Pixel; preserve existing PRoot launchers on other devices. Client
credentials live in `~/.config/termux/arch-vm`, and a changed guest host key fails
closed. No speed advantage over PRoot has been measured yet.

### Arch session lifetime

`Æ` and `æ command args...` start/resume Arch on demand. The last session exit
cleanly shuts down the guest and releases its RAM. Use `Æ --keep-memory` or
`æ --keep-memory command args...` to suspend instead, retaining RAM and processes.
The next ordinary invocation restores default shutdown behavior. Background jobs
stop on shutdown and freeze on suspension. For explicitly manual lifetime, use
`termux-arch --start` and `termux-arch-vm --stop`.

Run `python tests/device_arch_lifecycle.py` inside native Pixel Termux to verify
exit-code preservation, last-session shutdown, overlapping sessions, suspension,
RAM-state retention and network recovery. Start with a stopped guest; the test
refuses to disrupt an existing VM and never force-stops it. Results default to
`~/arch-lifecycle-results.json`.

### Live project sharing

Install `rclone` in Termux and `sshfs` in Arch, then run:

```sh
termux-arch-share ~/src/project /mnt/project
# In a second Termux session:
termux-arch --cwd /mnt/project -- ls
```

The share stays in the foreground and keeps Arch active until unmounted. Ctrl-C
requests an ordinary guest unmount; close files and shells using a busy mount
before retrying. `--read-only` disables guest writes. `--keep-memory` selects
suspension after the share and all other sessions exit.

This streams SFTP through the authenticated SSH/vsock connection, without new
listening ports. It serves the selected directory; symlinks are skipped. No guest
SSH forwarding is enabled. Files open for writing are cached privately and written
back on close; avoid editing the same file from both sides simultaneously. The
persistent cache is retained for recovery after interrupted writes. Unix metadata,
symlinks and locking do not have full native-filesystem semantics; keep build trees
and software requiring those semantics on guest ext4. This is a trusted-workspace
sharing feature, not a security sandbox for hostile guest code.

Implementation references: [rclone SFTP stdio](https://rclone.org/commands/rclone_serve_sftp/)
and [SSHFS passive transport](https://github.com/libfuse/sshfs/blob/master/sshfs.rst).

## Native Pacman package

On aarch64 Termux, run `python3 packaging/package.py` to build without installing.
The package is written to `build/packages/`. `VERSION` owns the release version; `PKGREL` increments packaging-only revisions.
Use the suite installer for upgrades so the preload remains available throughout the transaction.

For the combined Pacman suite, use `aether-update` (or `--check` to validate only).
Use `aether-update --adopt-legacy` once if older Aether commands were installed
manually. The helper backs up only recognized unowned commands; it never uses a
wildcard overwrite. APK confirmation remains separate with `aether-apks api` and
`aether-apks app`.
