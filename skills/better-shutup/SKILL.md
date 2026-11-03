---
name: better-shutup
description: Connect an agent task to the local BetterShutup desktop monitor over its Windows named pipe. Register a session, report completion, action-needed, errors, informational messages, plan steps, and step completion so the user sees topmost notifications and coordinated shutdown can wait for all sessions. Use by default when the user asks to read/review documentation, browse or search a directory, or use this skill, and treat completion as task-based rather than tied to the conversation. Also use when the user asks to track work with BetterShutup, coordinate automatic shutdown, register a session, report progress/needs-action/error/plan steps to BetterShutup, or mentions BetterShutup, 自动关机协调, 关机协同, 注册会话 or 汇报任务完成.
---

# BetterShutup session reporting

## Default tracking rule

Unless the user explicitly says not to use BetterShutup, use this skill and
register a session by default when the user asks you to:

- read, review, summarize, or search documentation;
- list, browse, inspect, or search a directory;
- use the `better-shutup` skill itself.

Also register whenever the user explicitly asks to track a task, coordinate
automatic shutdown, or use BetterShutup. Do not register unrelated ordinary
chat that is none of the above and that the user did not ask to track; a
session that never completes can block a planned shutdown.

If the desktop app is not running, report that once and continue the task
without tracking. Do not retry in a loop or try to start/stop the app yourself.

## Completion is task-based, not conversation-based

A session ends only when the requested **task** is actually finished, not when
the current conversational turn ends:

- Do **not** send `complete` merely because your answer is ending, the user
  stops replying, or you are handing control back to the user.
- If you need a user decision or operation, send `action` and wait. After the
  user responds, send `resume` and keep the same session open.
- If the conversation continues with follow-up work that belongs to the same
  task, keep the same session; send `complete` only when the whole task is done.
- If the user starts a clearly different task, register a new session for it.
  Complete the previous session only when its own task is done.
- Send `complete` immediately before the final answer **for that task**, even
  if the conversation itself will continue.
- If the task is abandoned, tell the user to remove the session. Do not send
  `complete` just to clear it.

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

2. If you have a plan, send it with `plan`. The first call creates the plan;
   later calls add or overwrite individual indices.

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" plan --session-id "7f3ac2..." --step 1 "分析现有登录流程" --step 2 "修改认证模块" --step 3 "补充回归测试"
   ```

   `--steps-json '{"1":"...","2":"..."}'` is an alternative for many steps.
   Indices are positive integers from 1 to 9999. Re-sending an index
   overwrites its text; changing the text resets that step to incomplete.

3. As each planned step finishes, mark it:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" step-done --session-id "7f3ac2..." --index 2 --message "认证模块修改完成"
   ```

   Step completion is progress only. It does **not** complete the task and does
   not automatically start the shutdown countdown. The index must have been
   registered by an earlier `0110`; an unknown index is a protocol error and
   does not reopen a completed session or cancel a countdown.

4. If you are blocked and need a human decision, send `action` instead of
   completing. Put the exact decision needed in `--instruction`:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" action --session-id "7f3ac2..." --instruction "需要确认是否保留旧版登录接口的兼容层。"
   ```

   After the user answers or performs the requested operation, acknowledge it
   with `resume` using the same session ID:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" resume --session-id "7f3ac2..." --message "用户已回答，继续执行。"
   ```

   `resume` sends status `0100`, clears the app's “需要操作” state, and
   dismisses the outstanding action-needed card. It produces no new
   notification card or sound. It does not clear an error or complete the task.
   Continue the task; send `complete` only when the work is actually finished.

5. If you merely want to tell the user something and do not need an answer or
   an operation, send `notify`:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" notify --session-id "7f3ac2..." --message "第一轮分析已完成，正在修改实现。"
   ```

   This shows a blue auto-close “消息” card and plays the notify sound. It does
   not complete the task and does not clear action/error state. If you need a
   decision, use `action`, not `notify`.

   Agent-facing rule: **在需要对用户说话但无需使用报错时使用**。

6. If the task fails or encounters a blocking error, send `error`:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" error --session-id "7f3ac2..." --error "依赖安装失败：无法访问内部包仓库。"
   ```

   `resume` does not clear a reported error. After fixing or explaining it,
   continue and send `complete` when the whole task is done.

7. Report task completion immediately before your final answer:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" complete --session-id "7f3ac2..." --message "登录流程重构完成，测试通过。"
   ```

## Status code reference

The status field is four bits. The app and this helper use the same values.
Their Chinese names are, in order: 注册、完成、需要操作、错误、撤销需要操作、
普通通知、计划更新、步骤完成。

| Code | Name | CLI | Purpose | Recommended use |
|---|---|---|---|---|
| `0000` | Register | `register` | Create a session or update its display name | Start of tracked work. An existing ID updates the name only; it does not clear “需要操作”. |
| `0001` | Complete | `complete` | Mark the whole task complete | Only when the tracked **task** is truly finished, not when a conversational turn ends. This is the only status that completes a session and can start the shutdown countdown. |
| `0010` | Action needed | `action` | Ask the user for a decision or operation | When you cannot proceed without a human. The orange card must be closed manually. After the user responds, send `0100`. |
| `0011` | Error | `error` | Report a failure or blocking error | When the task failed or is blocked. The red card must be closed manually. Fix the issue and send `0001` when done; `0100` does not clear the error. |
| `0100` | Resume | `resume` | Acknowledge that the user answered/performed the action | Immediately after the user responds to `0010`. Clears only action-needed and dismisses its card. No new card or sound. |
| `0101` | Notify | `notify` | Inform the user without asking for action | Progress updates, observations, non-blocking context. Blue auto-close card. If you need an answer, use `0010`; if the task is done, use `0001`. |
| `0110` | Plan update | `plan` | Create or update plan steps | When you form or revise a plan, including late in the task. Top-level keys are 1-based indices; same index overwrites. Blue auto-close card. |
| `0111` | Step complete | `step-done` | Mark one existing plan step done | As each step finishes. Requires an index previously sent by `0110`. Does not complete the task. Blue auto-close card. |
| `1000`–`1111` | Reserved | — | Future protocol use | Never send these. The current app rejects them. |

### Important state interactions

- `0000` with an existing session ID only updates the display name. It never
  clears action-needed or an error, and it does not reopen a completed session.
  Use `0100` to clear action-needed.
- `0010` and `0011` reopen a completed session and cancel a running shutdown
  countdown. This prevents shutdown while a human decision or a fix is still
  outstanding.
- `0101`, `0110`, and `0111` are also treated as new work for this purpose:
  if the session was already complete, they reopen it and cancel the countdown.
  Do not send them after `0001` unless you intend to reopen the task.
- `0100` does not reopen a completed session and does not cancel a countdown.
- `0111` does not complete the session even when every step is done. Always
  send `0001` at the end.
- Overwriting a plan step with different text resets that step to incomplete.
  Re-sending the same text preserves its completed state.

## Choosing the right status

- Need the user to decide or do something → `0010`; then `0100` after they
  respond.
- Just need to say something → `0101`.
- Task failed or blocked by an error → `0011`; then `0001` after it is resolved.
- Have a plan or changed the plan → `0110`.
- Finished one planned step → `0111`.
- Whole task finished → `0001`.

Do not use `0101` for a question that needs an answer. Do not use `0010` for a
casual progress update. Do not use `0001` merely because you are pausing.

## Exit codes and failure handling

- Exit code `0`: the frame was written to the pipe. The protocol has no ACK,
  so a successful write does not prove the app accepted the session contents.
- Exit code `2`: the app is not running or the pipe could not be reached. Tell
  the user once and continue the coding task without tracking; do not retry in
  a loop. Do not try to launch or stop the app yourself.
- Exit code `3`: the input was invalid (for example, an empty session ID, a
  session ID containing spaces, an invalid plan index, an oversized message, or
  missing/invalid command-line arguments).

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
- Plan steps should be short and concrete. One message may contain at most 200
  steps; one step may contain at most 2000 characters.
- Do not include secrets, credentials, or irrelevant log dumps.
- `complete` means the tracked work is truly finished. Do not send it merely
  because you are pausing.
- The app displays all message text; it never executes text from messages.

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
When the user asks to read/review documentation, browse or search a directory,
or use the better-shutup skill, use the skill by default: register one session
at task start, retain its session ID, and keep it open until the task itself is
finished. Send complete only when the task is done, not when the conversational
turn ends. Use action when a user decision is required, and resume after the
user responds. Plan updates, step completion, and informational messages are
progress signals and never replace the final completion message. Do not
register unrelated tasks that the user did not ask to track.
```

This keeps sessions intentional and prevents stale sessions from blocking a
planned shutdown.

See `references/protocol.md` for the exact wire format, per-status semantics,
and examples used by the helper.
