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

See the [API implementation and Arch acceptance plan](https://github.com/wallentx/termux-api/blob/wallentx/capabilities/docs/VIRTUALIZATION.md).
