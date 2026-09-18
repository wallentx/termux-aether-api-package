# termux-capabilities

`termux-capabilities [--json]` prints a read-only JSON snapshot from the matching
`wallentx/termux-api` Android app. It requires that companion fork; stock Termux:API
does not implement the new `Capabilities` method yet.

The command uses the existing `libexec/termux-api` transport and GNU coreutils
`timeout`. The request is limited to 15 seconds. Exit 124 means timeout; a successful
report can still contain denied, unavailable or unsupported sections. Inspect the
section status before consuming its values. No permission requests or privileged
actions are made by the command.

Examples:

```sh
termux-capabilities --json
termux-capabilities --json > "$HOME/device-status.json"
```

Reported sections include device identity/version, CPU feature availability,
permission grants, battery temperature, thermal state, Shizuku availability,
all-files-access state and the transport boundary. No serial number or IMEI is
included. CPU flags are not proof of SIMD acceleration; battery temperature is not
CPU temperature. Avoid rapid polling of Android's thermal headroom API.

The [API schema and signing/transport decisions](https://github.com/wallentx/termux-api/blob/wallentx/capabilities/docs/CAPABILITIES.md)
live with the Android implementation. Compile/package through CI or the Termux
package infrastructure. The command is registered in CMake's script installation
list; adding this shell wrapper does not require changing the existing helper binary.

Lightweight local validation (no compilation):

```sh
sh -n scripts/termux-capabilities.in
python3 -B -m unittest discover -s tests -p 'test_*.py'
```
