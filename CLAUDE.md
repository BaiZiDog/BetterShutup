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
- `installer/BetterShutup.iss` is the Inno Setup 6.3+ installer script.
- `tools/install_skill.py` installs the skill into the per-agent skill roots.
- `tools/build_exe.py` is the Nuitka build entry point.
- `tools/build_installer.py` builds the per-user Inno Setup installer.

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

# Build the Inno Setup 6 installer (after the EXE exists)
python tools/build_installer.py
# equivalent convenience wrapper: build-installer.bat
# output: dist/BetterShutup-<version>-setup.exe
```

Nuitka compiles the entry point with `--onefile`, the tk-inter plugin, Zig as
the C compiler (required for Python 3.13), and the Windows GUI console mode
disabled. Build options live only in `tools/build_exe.py`; keep them there
rather than duplicating long command lines in docs or CI. `build_exe.py` reads
the version from `better_shutup/__init__.py`; keep `pyproject.toml` in sync.
`build_installer.py` locates `ISCC.exe` from `INNO_SETUP_ISCC`, `PATH`, common
install directories, or the Inno Setup 6 uninstall registry entry.

There is no configured linter/formatter. For non-trivial changes, use the
available `code-review` skill and then the `simplify` skill where appropriate,
and run the relevant pytest modules before committing.

## Architecture

### Wire protocol

`better_shutup/protocol.py` owns the 4-byte header and JSON validation:

```text
byte0:  0 0 0 0 S S S S    status: 4 bits; upper four bits reserved as 0
byte1-3: 24-bit big-endian length of the UTF-8 JSON body
```

Statuses are `0000` register, `0001` complete, `0010` action, `0011` error,
`0100` resume, `0101` notify, `0110` plan, `0111` step complete, and `1000`
file download. Codes `1001`–`1111` are reserved and rejected. Each connection
carries exactly one frame, written in one `WriteFile`; the server closes after
reading it. The body maximum is 16 MiB − 1. There is no acknowledgement
channel: the app never sends anything to the agent, and the standalone CLI's
JSON is local process output.

Status `0000` never emits a notification and only registers a session or
updates its display name. An existing ID must not clear action-needed, clear an
error, reopen a completed session, or cancel a countdown. Status `0100` is the
dedicated user-response acknowledgement: it clears only action-needed and
dismisses that session's action card, with no new card or sound; it preserves
errors, completion, and any running countdown.

Statuses `0101`, `0110`, and `0111` are informational progress signals but
count as new work: if the session was already complete they reopen it and
cancel a running countdown. Status `0110` uses a flat JSON object whose
`session_id` key is reserved and whose other keys are 1-based plan indices
(`1`–`9999`, canonical decimal strings); values are non-empty step text. It
upserts steps, and changing an existing step's text resets that step to
incomplete. Status `0111` requires an existing step index and never completes
the task automatically.

Status `1000` carries `session_id`, `url` (http/https only), and `path` (an
absolute Windows path whose last segment is the file name). The core emits a
`DownloadRequest`; `downloader.py` performs an adaptive multi-threaded range
download in the background. The app never sends a result frame: success is an
atomic target-file replacement, failure leaves the old target untouched and
appends `err.err` in the target directory. `1001`–`1111` remain reserved.

Keep `protocol.py`, the standalone Skill CLI's framing, and
`skills/better-shutup/references/protocol.md` in sync. The protocol reference is
bilingual with Chinese first and the corresponding English paragraph directly
after it; preserve that pairing when editing. The parity tests in
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
- `downloader.py` runs each file download in a background manager thread with
  an adaptive pool of range workers. It writes only to disk and returns results
  through a thread-safe queue; the UI thread calls `Coordinator.download_finished`.
  Never start downloads or touch Tk from the pipe worker itself.

### Session and shutdown state machine

`better_shutup/core.py` is pure, injectable-clock logic. Important rules:

- Status `0000` never emits notifications. A new ID registers and cancels a
  running countdown as new work; an existing ID only updates the display name.
- Status `0100` clears only action-needed and requests dismissal of that
  session's action card. It does not clear an error, complete the session,
  reopen a completed session, or cancel a countdown.
- A task is complete only after status `0001`; `0010`, `0011`, `0101`, `0110`,
  and `0111` do not complete a session. If a previously completed session later
  sends any of those five statuses, it is reopened and any running countdown is
  cancelled. This is a deliberate user decision: informational messages and
  plan progress also mean the agent is still working.
- `Session` tracks `completed`, `action_needed`, `has_error`, `last_event`,
  `last_text`, and a `plan` mapping of index to `PlanStep`. The UI must use the
  boolean flags for state rendering, not `last_event`, because `0101`/`0110`/
  `0111` update `last_event` without clearing attention/error state.
- `0110` plan steps are upserted. New indices are added; existing indices with
  changed text are reset to incomplete; identical text preserves completion.
  `0111` requires the index to exist and only marks that step complete. An
  unknown-index `0111` is a protocol error and leaves session state and any
  countdown untouched; it does not reopen a completed session.
- `1000` file download counts as new work at request time; it does not complete
  the session. The core emits a `DownloadRequest`; `download_finished()` records
  success/failure, updates `last_text`, and emits `DOWNLOAD_SUCCESS` or
  `DOWNLOAD_FAILURE`. A failure that arrives after completion reopens the
  session and cancels the countdown.
- A countdown starts only when the plan is armed, at least one session exists,
  and all registered sessions are complete. Removing completed sessions does
  not cancel an already-running countdown.
- `tick()` is the only path that declares shutdown due; it disarms the plan and
  fires once. The app then calls `shutdown.perform_shutdown()`.
- Sessions and plan state are in-memory only; restart starts disarmed.

### UI and sound

- `ui/animation.py`: ease-out frame helper and window fade-in. Keep animation
  durations subtle (roughly 180–300 ms) and never block Tk with sleeps.
- `ui/main_window.py`: decorated main window with native title bar, border, and
  taskbar button; shutdown card, session table, event log, and an in-window
  plan view. Single-clicking a session row switches the sessions card to that
  session's plan view; a “返回会话” button returns to the list. The session
  table has a plan-progress column and uses `action_needed`/`has_error` flags
  for coloring. The header has “日志” and “设置” buttons; “日志” opens the
  rotated file log in the default text editor.
- `ui/notifications.py`: borderless topmost cards, bottom-right stacking,
  completion/message/plan/step/download-success auto-dismiss, and a decorated
  long-text details window. Cards slide/fade in and out, reposition with
  ease-out animation, and auto-close cards show a bottom progress line. Notify,
  plan, step-complete, and download-success cards use the blue primary color
  and the `notify` sound; action, error, and download-failure cards remain
  manual-close. Download start is log-only. `_animate_to` defers its `on_done`
  callback to the root event loop; destroying a notification Toplevel
  synchronously inside its own `after` callback triggers a Tkinter
  `_tclCommands` cleanup bug. Auto-close is scheduled when the card is shown,
  not when its slide-in animation ends, so a stacking animation cannot drop
  the timer.
- `ui/countdown.py`: decorated countdown/cancel window forced into native
  fullscreen, covering the taskbar, with a centered card; it fades in and
  pulses the timer during the last 10 seconds.
- `ui/settings.py`: decorated settings window (transient, no taskbar button)
  with “提示音” and “数据与日志” tabs. The sound tab has independent WAV
  overrides and preview for the four kinds (`complete`, `action`, `error`,
  `notify`); the data tab shows the data directory and log file and opens
  either through Explorer or the default file association.
- `ui/theme.py`: DPI scaling, fonts, colors, ttk styles.
- `better_shutup/assets/BetterShutup.ico` is the Tk default window icon and the
  Nuitka `--windows-icon-from-ico` source. The source PNG lives under `assets/`;
  keep the ICO in package data so the onefile build can set it at runtime.
- `sounds.py`: deterministic built-in WAV generation plus a serialized playback
  worker. Do not play sounds synchronously on the Tk thread.
- `config.py` stores settings/sounds/logs under `%LOCALAPPDATA%\BetterShutup`
  by default; environment/CLI overrides are used by tests and dry runs. The
  settings window exposes the data and log paths. The installer creates the same
  data directory and marks it `uninsneveruninstall`, so upgrades and uninstalls
  preserve configuration, logs, and sounds.
- `installer/BetterShutup.iss` installs per-user to
  `%LOCALAPPDATA%\Programs\BetterShutup` with Inno Setup 6.3+. Keep its version
  aligned with `better_shutup/__init__.py`; `build_installer.py` passes the
  version at build time.

### Safety invariants

- Automated tests must never run the real shutdown command. Use `--dry-run`,
  injected/monkeypatched shutdown functions, and unit tests. This is a shared
  machine.
- The countdown is app-owned; selecting the app's close path must cancel it
  before showing any modal confirmation. Do not schedule a system `shutdown`
  timer that survives app exit.
- Do not execute or eval text received from the pipe. It is only displayed.
- Status `1000` allows a local agent to make the app fetch an HTTP(S) URL and
  write the response to an arbitrary absolute path. Keep it restricted to
  trusted local agents; never execute downloaded content, and preserve the
  absolute-path/http(s)-only validation.
- The app is receive-only. The standalone CLI's JSON is local output; never add
  an app-to-agent response channel for downloads or progress.
- Every subagent that performs tracked work must register and complete its own
  session; the parent must pass the CLI path and ensure those sessions finish.
- The Agent Skill may start BetterShutup when tracking is requested, but it
  must never close, kill, or restart the app, or cancel a planned shutdown.
  Only the user may close the app; an agent that starts it leaves it running.
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
- The Agent Skill defaults to tracking tasks where the user asks to read/review
  documentation, browse/search a directory, or use the skill itself. Session
  completion is task-based, not conversation-based: `complete` means the task
  is finished, not that a conversational turn ended.
- Agents must send `step-done` immediately after each plan step is actually
  completed, not batch the status updates at the end of the task. Real-time
  follow-up is required; long steps should use `notify` at meaningful
  milestones, and plan/action/error changes must be reported as they happen.
- Parent agents must give every subagent the absolute helper path and require a
  unique session ID, task-based completion, and the start-only/never-close
  lifecycle rule. Subagents also update step status immediately. The parent
  must ensure subagent sessions complete.
- The CLI supports `--quiet` for successful commands; `register --quiet`
  requires an explicit `--session-id`. Errors always print JSON.
- The public repository is maintained as `BaiZiDog/BetterShutup` under the
  GNU General Public License v3.0, GPL-3.0-only (`LICENSE`, `NOTICE`).
  `LICENSE` is bilingual with Chinese first and the corresponding English
  paragraph after each Chinese paragraph; the English text is authoritative.
  The Inno Setup `LicenseFile` must keep pointing at this file so the installer
  displays the same bilingual license.

没有我的要求先不提交仓库

无论何时都使用better_shutup管理会话，我说类似“完成任务后关机也都自动等价为使用better_shutup的功能