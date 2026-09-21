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
guest instead. There is no automatic host-to-guest working-directory mapping:
inline commands launched outside Termux home require an explicit guest `--cwd`.
Use `termux-arch-share` to mount a selected host directory inside the guest.

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
