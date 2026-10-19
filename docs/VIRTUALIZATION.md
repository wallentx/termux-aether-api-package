# Virtualization status

```sh
termux-virtualization --status
```

Requires the matching fork of Termux:API. JSON is the default; `--json` is accepted.
The command reads AVF feature/permission/framework readiness. It never requests
access or starts a VM. `status` can be `ok`, `denied`, `unavailable` or `unsupported`;
inspect `readiness.blockers` for the individual gates. Exit 0 only means the API
returned JSON; timeout exits 124. Unknown or duplicate options exit 2 locally.

Even `can_attempt_custom_vm: true` means only preflight passed. This status
command does not boot or validate a guest, and it does not establish a speedup.
The implemented Arch backend provides `Æ` for interactive use and `æ` for inline
commands. These launchers start/resume the guest on demand; the last session
normally shuts it down and releases RAM. `--keep-memory` retains a suspended
guest instead. `æ command args...` uses the configured guest user and directory,
regardless of the host working directory. By default this is `root` in `/root`.
There is no automatic host-to-guest working-directory mapping.
Use `termux-arch-share` to mount a selected host directory inside the guest.

### Launcher defaults

The first non-help `termux-arch` invocation creates
`${XDG_CONFIG_HOME:-$HOME/.config}/termux-arch/config.yml` with every launcher
setting populated. An unset, empty, or relative `XDG_CONFIG_HOME` uses
`$HOME/.config`. The file is created privately without overwriting an existing
config. YAML is read using `yq` version 4, included as a package dependency.

```yaml
user: root
cwd: null
memory: null
graphics_mode: null
keep_memory: false
tty: null
```

| Setting | Default behavior |
| --- | --- |
| `user` | Run as `root`; set an existing guest account such as `alarm`. |
| `cwd` | `null` starts in that user's guest home; otherwise use an absolute guest path. |
| `memory` | `null` retains the VM's saved allocation; a value such as `8G` requests a size. Changes require a stopped VM. |
| `graphics_mode` | `null` retains an existing VM's mode and starts new VMs headless. `gfxstream` requires a GPU-enabled VM; `none` explicitly requests headless mode. |
| `keep_memory` | `false` shuts down after the last session; `true` retains guest RAM/processes. |
| `tty` | `null` allocates a PTY for a shell and none for a command; `true`/`false` force the choice. |

Command-line options override the file for one invocation:

```sh
termux-arch --user alarm -- id -un
termux-arch --user root --cwd / -- id -un
termux-arch --no-keep-memory --no-tty -- uname -a
termux-arch --graphics-mode none -- uname -a
```

`Æ` and `æ` inherit these settings. `æ --keep-memory command...` and
`æ --no-keep-memory command...` override retention while preserving the remaining
guest arguments literally. Use `termux-arch` directly for other one-off overrides.
`--start` and `--shell` select actions and are not saved defaults; retention only
applies to sessions, so a configured `keep_memory: true` does not block `--start`.
`termux-arch-vm --start` also honors the shared configuration, including graphics
and RAM defaults.

To make the GPU available on each `Æ` and `æ` boot, set
`graphics_mode: gfxstream` in the existing config. This requires the graphics-aware
API and the separately staged `Image-gfxstream` kernel. An incompatible running
or suspended VM must be stopped normally before changing modes; the launchers
reject the mismatch before taking over its session lifecycle. Matching running
VMs are reused. The usual last-session shutdown or retention policy still applies.
Use `termux-arch --graphics-mode none -- command...` (or `Æ --graphics-mode none`)
for an explicit headless invocation after stopping the GPU VM. Lowercase `æ`
continues to pass guest command arguments literally; use the full launcher for
one-off graphics overrides.

The virtual GPU is exposed through the guest's Gfxstream Vulkan driver. Guest
applications need the driver and permission to open the render node; changing
the boot mode does not change the configured execution account. If the API is
unavailable or Shizuku is disconnected, the launcher reports that condition
instead of treating the missing capability response as an outdated APK.

Non-root execution uses the existing root SSH connection and `/usr/bin/runuser`
inside Arch. It sets the target account's identity and home before changing
directory or executing the command. No account is created and a missing account
fails without falling back to root. Direct commands do not load login profiles;
interactive shells retain the existing Bash login-shell behavior. The existing
SSH identity and host-key pins stay in `~/.config/termux/arch-vm`.

The preflight command leaves existing PRoot installations and launchers unchanged.
Install the Arch launchers only on the intended device, preserving any existing
PRoot `Æ`/`æ` commands separately before installing conflicting names.

See the [API implementation and Arch acceptance plan](https://github.com/wallentx/termux-aether-api/blob/dev/docs/VIRTUALIZATION.md).

## Arch guest lifecycle

`termux-arch-vm --start`, `--status` (default), and `--stop` use the API fork's
fixed Shizuku VM service. The v2 guest is writable and persistent, supports
authenticated SSH command execution over vsock, and provides userspace IPv4
networking through the host bridge. Live directory sharing uses the separate
`termux-arch-share` command. The guest requires the separately verified/staged
CI image and authorized shell Shizuku; these CLI wrappers do not contain the
image or install the VM backend.

The lifecycle command accepts no image paths, arbitrary shell text or VM IDs.
`--memory SIZE` selects RAM for `--start`; guest commands run through `termux-arch`
or the `Æ`/`æ` launchers. JSON `status=ready` and `guest_boot=verified` indicate
that the guest readiness marker was observed. CLI exit 0 only establishes API
delivery, not successful boot, networking, or command execution.

`termux-virtualization` remains a read-only preflight even when the Arch backend
is installed. See the [API virtualization documentation](https://github.com/wallentx/termux-aether-api/blob/dev/docs/VIRTUALIZATION.md)
for image staging and lifecycle guarantees, and this repository's README for
session lifetime and file-sharing behavior.
