---
name: better-shutup
description: Connect an agent task to the local BetterShutup desktop monitor over its Windows named pipe, register a work session and report task completion, action-needed, or error so the user sees topmost notifications and coordinated shutdown can wait for all sessions. Use when the user asks to track work with BetterShutup, coordinate automatic shutdown, register a session, report completion/needs-action/error to BetterShutup, or mentions BetterShutup, 自动关机协调, 关机协同, 注册会话 or 汇报任务完成.
---

# BetterShutup session reporting

Use this skill only when the user explicitly wants this task to participate in
BetterShutup's session tracking / coordinated shutdown, or when project rules
ask you to do so. Do **not** register for ordinary, untracked tasks: a session
that never completes would block the user's planned shutdown.

The desktop app must already be running. The skill only sends messages to it;
it cannot start the app, enable planned shutdown, or cancel a countdown.

## Locate the helper script

This skill's root is the directory containing this `SKILL.md`. Call it
`<SKILL_DIR>` and never assume the agent's current working directory.

- Claude Code: use `${CLAUDE_SKILL_DIR}` directly in the command path.
- DSH / TRAE and other Agent Skills hosts: resolve the absolute directory of
  this `SKILL.md` and substitute it for `<SKILL_DIR>`.

Always quote the script path.

## Workflow

1. At the beginning of the tracked task, register a session and use a unique,
   descriptive session ID. If you do not pass `--session-id`, the helper
   generates a UUID and prints it.

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" register --name "Claude Code · 优化登录流程"
   ```

   Example output:

   ```json
   {"ok": true, "event": "register", "session_id": "7f3ac2...", "pipe": "\\\\.\\pipe\\BetterShutup", "bytes_written": 74}
   ```

   Save `session_id` for the rest of the task. Reuse it for every follow-up
   message. Do not create a new session for every progress update.

2. Report task completion immediately before your final answer:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" complete --session-id "7f3ac2..." --message "登录流程重构完成，测试通过。"
   ```

3. If you are blocked and need a human decision, send `action` instead of
   completing. Put the exact decision needed in `--instruction`:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" action --session-id "7f3ac2..." --instruction "需要确认是否保留旧版登录接口的兼容层。"
   ```

4. If the task fails or encounters a blocking error, send `error`:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" error --session-id "7f3ac2..." --error "依赖安装失败：无法访问内部包仓库。"
   ```

5. A session that sent `action` or `error` is still incomplete. Continue after
   the user resolves it, then send `complete` when the work is actually done.
   If the task is abandoned, tell the user that the session should be removed
   in the BetterShutup window. Sending `action`/`error` after a previous
   `complete` reopens the session and cancels any running shutdown countdown,
   so send another `complete` once it is resolved.

## Exit codes and failure handling

- Exit code `0`: the frame was written to the pipe. The protocol has no ACK,
  so a successful write does not prove the app accepted the session contents.
- Exit code `2`: the app is not running or the pipe could not be reached. Tell
  the user once and continue the coding task without tracking; do not retry in
  a loop. Do not try to launch or stop the app yourself.
- Exit code `3`: the input was invalid (for example, an empty session ID, a
  session ID containing spaces, an oversized message, or missing/invalid
  command-line arguments).

All normal output and argument errors are one JSON object on stdout. Parse the
JSON rather than relying on stderr. PowerShell and Bash quoting are fine; pass
the text as a single argument.

If `python` is unavailable, try `py -3` or the project's Python executable.
The script only uses the Python standard library.

## Message content

- Session names should identify the agent and task, for example
  `TRAE · 生成发布说明`.
- Keep notifications short and actionable. Messages are shown as topmost
  cards; very long text is truncated in the card (the app keeps a preview).
- Do not include secrets, credentials, or irrelevant log dumps.
- `complete` means the tracked work is truly finished. Do not send it merely
  because you are pausing.
- The app displays `action` and `error`; it never executes text from messages.

## Options

- `--pipe <path>`: use a non-default pipe. The path must match the app setting.
  The environment variable `BETTER_SHUTUP_PIPE` is also supported.
- `--timeout-ms <ms>`: connection timeout; default 5000.
- `--dry-run`: build and validate the frame without sending it. For diagnostics
  only; do not use it in normal reporting.

The default pipe is `\\.\pipe\BetterShutup`.

## Optional project-rule snippet

To opt a whole project into this workflow, add a rule such as:

```text
When the user asks to coordinate a task with BetterShutup, use the
better-shutup skill: register one session at task start, retain its session ID,
and send exactly one completion/action/error message before the final response.
Do not register ordinary tasks that the user did not ask to track.
```

This keeps sessions intentional and prevents stale sessions from blocking a
planned shutdown.

See `references/protocol.md` for the exact wire format used by the helper.
