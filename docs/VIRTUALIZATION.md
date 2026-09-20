# Virtualization status

```sh
termux-virtualization --status
```

Requires the matching fork of Termux:API. JSON is the default; `--json` is accepted.
The command reads AVF feature/permission/framework readiness. It never requests
access or starts a VM. `status` can be `ok`, `denied`, `unavailable` or `unsupported`;
inspect `readiness.blockers` for the individual gates. Exit 0 only means the API
returned JSON; timeout exits 124. Unknown or duplicate options exit 2 locally.

Even `can_attempt_custom_vm: true` means only preflight passed. A guest has not
been booted, Arch compatibility has not been established, and no speedup has been
measured. The future Arch backend should retain `Æ` for interactive use and `æ`
for inline commands, reusing a running VM and mapping shared working directories.
The existing PRoot installation and launch commands remain unchanged.

See the [API implementation and Arch acceptance plan](https://github.com/wallentx/termux-aether-api/blob/wallentx/capabilities/docs/VIRTUALIZATION.md).

## Experimental Arch guest lifecycle

`termux-arch-vm --start`, `--status` (default), and `--stop` use the API fork's
fixed Shizuku VM service. The current guest is a fresh read-only Arch boot proof:
one vCPU, 1 GiB RAM, no network and no guest command execution. It requires the
separately verified/staged CI image and authorized shell Shizuku. The command
accepts no image paths, shell text or VM IDs. JSON `status=ready` and
`guest_boot=verified` indicate the guest readiness marker was observed;
CLI exit 0 only establishes delivery, not boot success.

The existing `termux-virtualization` command stays read-only. Neither command
changes existing `Æ`/`æ` or PRoot installations. See the API fork's
`docs/VIRTUALIZATION.md` for image build, staging and lifecycle guarantees.
