# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

BetterShutup is a Windows-only Python/Tkinter application that receives agent
session messages over a Windows named pipe, shows topmost notifications, and
optionally shuts the machine down after every registered session completes.
The repository is public under GPL-3.0-only.

The desktop app and the Agent Skill are independent deliveries:

- `better_shutup/` is the desktop package. Its console-less launcher and Nuitka
  entry point is `better_shutup/BetterShutup.pyw`; `python -m better_shutup`
  uses `better_shutup/__main__.py`.
- `skills/better-shutup/` is portable across Claude Code, DSH, and TRAE. Its
  `scripts/better_shutup_pipe.py` must stay standalone (standard library only,
  no imports from the desktop package) and must match the app's wire format.
- `tools/install_skill.py` installs the skill into the per-agent skill roots.
- `tools/build_exe.py` is the Nuitka build entry point.

Runtime code has no third-party dependencies. pytest and Nuitka/Zig are
development/build dependencies declared in `pyproject.toml`.

## Common commands

```text
# Run the desktop GUI
python -m better_shutup

# Safe end-to-end run: full notification/countdown path, no real shutdown
python -m better_shutup --dry-run

# Full test suite
python -m pytest -q

# One test module / one test
python -m pytest -q tests/test_core.py
python -m pytest -q tests/test_core.py::test_plan_arm_with_all_complete_starts_countdown

# Install the Agent Skill
python tools/install_skill.py --scope project --agents claude,dsh,trae

# Install build dependencies and build the one-file EXE
python -m pip install -e ".[build]"
python tools/build_exe.py
# equivalent convenience wrapper: build.bat
# output: dist/BetterShutup.exe
```

Nuitka compiles the entry point with `--onefile`, the tk-inter plugin, Zig as
the C compiler (required for Python 3.13), and the Windows GUI console mode
disabled. Build options live only in `tools/build_exe.py`; keep them there
rather than duplicating long command lines in docs or CI.

There is no configured linter/formatter. For non-trivial changes, use the
available `code-review` skill and then the `simplify` skill where appropriate,
and run the relevant pytest modules before committing.

## Architecture

### Wire protocol

`better_shutup/protocol.py` owns the 4-byte header and JSON validation:

```text
byte0:  0 0 0 0 0 0 SS    status: 00 register, 01 complete, 10 action, 11 error
byte1-3: 24-bit big-endian length of the UTF-8 JSON body
```

Status values are binary (`10` is decimal 2). Each connection carries exactly
one frame, written in one `WriteFile`; the server closes after reading it. The
body maximum is 16 MiB − 1. The reserved six bits in byte 0 must be zero.
There is no acknowledgement channel.

Keep `protocol.py`, the standalone Skill CLI's framing, and
`skills/better-shutup/references/protocol.md` in sync. The parity tests in
`tests/test_skill_client.py` are the guardrail.

### Windows pipe and threading

- `win32_pipe.py` is the ctypes/Win32 layer: message-mode inbound pipes,
  `PIPE_REJECT_REMOTE_CLIENTS`, accept/read/write, client waiting, and errors.
- `pipe_server.py` runs a listener thread and one short-lived worker per
  connection. It creates the next listening instance before dispatching the
  accepted one, and reads buffered data even when `ConnectNamedPipe` reports
  `ERROR_NO_DATA` (a client may close immediately after writing). Do not
  regress this behavior; rapid sequential sends are covered by tests.
- `app.py` owns the only Tk event loop. Pipe workers must never touch Tk; they
  enqueue events and the UI polls the queue with `after`. Keep all session and
  shutdown state mutations on the UI thread.

### Session and shutdown state machine

`better_shutup/core.py` is pure, injectable-clock logic. Important rules:

- Registering a new/reopened session cancels a running countdown while keeping
  the plan armed.
- A task is complete only after status `01`; `10`/`11` are notifications and do
  not complete a session. If a previously completed session later sends `10`
  or `11`, it is reopened and any running countdown is cancelled.
- A countdown starts only when the plan is armed, at least one session exists,
  and all registered sessions are complete. Removing completed sessions does
  not cancel an already-running countdown.
- `tick()` is the only path that declares shutdown due; it disarms the plan and
  fires once. The app then calls `shutdown.perform_shutdown()`.
- Sessions and plan state are in-memory only; restart starts disarmed.

### UI and sound

- `ui/main_window.py`: plan/session/log UI and state rendering.
- `ui/notifications.py`: borderless topmost cards, bottom-right stacking,
  completion auto-dismiss, long-text detail window.
- `ui/countdown.py`: topmost countdown/cancel window.
- `ui/settings.py`: independent WAV overrides and preview.
- `ui/theme.py`: DPI scaling, fonts, colors, ttk styles.
- `sounds.py`: deterministic built-in WAV generation plus a serialized playback
  worker. Do not play sounds synchronously on the Tk thread.
- `config.py` stores settings/sounds/logs under `%LOCALAPPDATA%\BetterShutup`
  by default; environment/CLI overrides are used by tests and dry runs.

### Safety invariants

- Automated tests must never run the real shutdown command. Use `--dry-run`,
  injected/monkeypatched shutdown functions, and unit tests. This is a shared
  machine.
- The countdown is app-owned; selecting the app's close path must cancel it
  before showing any modal confirmation. Do not schedule a system `shutdown`
  timer that survives app exit.
- Do not execute or eval text received from the pipe. It is only displayed.
- Preserve `PIPE_REJECT_REMOTE_CLIENTS` and single-instance behavior.
- Build artifacts in `dist/`, Nuitka build directories, logs, caches, and
  generated data must stay untracked (`gitignore`).

## Repository conventions

- User-facing GUI text and README/docs are Chinese. Python identifiers, comments,
  and commit messages are English.
- The standalone Agent CLI writes exactly one ASCII-safe JSON object to stdout
  per invocation and uses non-zero exit codes for pipe or validation failures.
- Skill hosts resolve skill scripts relative to the skill directory; never
  assume the current working directory. Claude Code may use
  `${CLAUDE_SKILL_DIR}`, while DSH/TRAE must use the actual skill directory.
- The public repository is maintained as `BaiZiDog/BetterShutup` under the
  GNU General Public License v3.0, GPL-3.0-only (`LICENSE`, `NOTICE`).
