# termux-shizuku

Requires the matching `wallentx/termux-aether-api` app, Shizuku, the existing API helper,
and coreutils `timeout`.

```sh
termux-shizuku --status
termux-shizuku --request-permission
termux-shizuku --thermal
```

JSON is always emitted; `--json` is accepted explicitly. Status is read-only.
The permission command requests a foreground authorization UI; its `pending`
response is not proof of authorization. Review the dialog, then check status.
The thermal command requires Shizuku authorization and reads current HAL sensor
values through a fixed diagnostic operation. It accepts no arbitrary commands.

Exit 124 means the 20-second request deadline expired. Exit zero means a response
arrived; inspect its `status` for denied, unavailable, partial, busy or other errors.
Stopping Shizuku or rebooting can make it unavailable until started again.

The [Android integration contract](https://github.com/wallentx/termux-aether-api/blob/wallentx/capabilities/docs/SHIZUKU.md)
describes sensor units, privilege boundaries and cleanup.

Local checks do not compile anything:

```sh
sh -n scripts/termux-shizuku.in
python3 -B -m unittest discover -s tests -p 'test_*.py'
```
