# termux-api-package
Termux package containing scripts to call exposed API methods in the [Termux:API](https://github.com/termux/termux-api) app.

### Fresh Arch AVF workspace

With the matching Termux:API fork, staged v2 guest image, authorized shell Shizuku,
and Termux `python` and `openssh` packages:

```sh
Æ                                  # Interactive guest shell
æ uname -a                         # Inline command from Termux home
termux-arch --cwd /root -- ls -la    # Explicit guest directory
termux-arch-vm --stop               # Flush, remount read-only and shut down
```

The VM keeps running after you exit a shell. Its ext4 filesystem is writable and
persistent. These commands use authenticated SSH over vsock; guest networking and
Android project sharing are not enabled. A command from a host directory other
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
