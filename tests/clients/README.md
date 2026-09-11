# tests/clients/ — the CLI and the desktop client

Four files. These test things a person runs, not things a browser calls.

```
test_symoneural_cli.py   bin/symoneural-cli: subcommands, output, exit codes
test_cli_upgrade.py      upgrading in place without losing a session
test_desktop_client.py   the desktop client
test_desktop_shell.py    its shell integration
```

## The failure this directory is named after

**#94 shipped a desktop client whose eighteen declared checks were all green and whose chat
surface was dead on arrival.** A missing capability meant the page was never permitted to
hear the stream it had asked for, so it rendered one turn and then nothing, with no error to
read. The timer archived the task two minutes later.

`exists`, `grep` and `ngrep` ask what is written on disk. None of them can ask whether the
thing works. A client test that only reads source is the same check that let that through —
run the command, assert on its output and its exit code.
