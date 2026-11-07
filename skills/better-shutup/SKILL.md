---
name: better-shutup
description: Connect an agent task to the local BetterShutup desktop monitor over its Windows named pipe. Register a session, report completion, action-needed, errors, informational messages, plan steps, and step completion, or request a background file download to an absolute local path so the user sees topmost notifications and coordinated shutdown can wait for all sessions. Use by default when the user asks to read/review documentation, browse or search a directory, or use this skill, and treat completion as task-based rather than tied to the conversation. The agent may start the app but must never close it. Also use when the user asks to track work with BetterShutup, coordinate automatic shutdown, register a session, report progress/needs-action/error/plan steps to BetterShutup, or mentions BetterShutup, 自动关机协调, 关机协同, 注册会话 or 汇报任务完成.
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

If the desktop app is not running, you may start it once as described in
“Application lifecycle: start only, never stop”. Never stop it yourself. If it
cannot be started safely, report that once and continue the task without
tracking; do not retry in a loop.

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

BetterShutup must be running to send messages. You may start it when needed,
but you must never close it. The skill cannot enable planned shutdown or cancel
a countdown.

## Application lifecycle: start only, never stop

“管开不管关”: the Agent may **start** BetterShutup, but must **never close**
it.

- If BetterShutup is not running and the user wants tracking, you may start it
  once using a launcher/path the user or project actually provides (for
  example `start "" "C:\path\to\BetterShutup.exe"`, the project's `start.bat`,
  or `python -m better_shutup`). Do not guess an unrelated path.
- After starting it, leave it running. Do not close its window, kill/terminate
  the process (`taskkill`, `Stop-Process`, etc.), or restart it.
- Do not close or restart a BetterShutup instance that the user started.
- Only the user may close the application or cancel a planned shutdown.
- Starting the app does not authorize you to change its shutdown UI or enable
  planned shutdown.
- If you cannot start it safely, ask the user once to start it. If it remains
  unavailable, continue the task without tracking and do not retry in a loop.

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

   **完成一步后立马汇报，实时跟进。** Send `step-done` immediately after
   each step is actually completed, before starting the next step. Do not wait
   until the end of the task or batch all `step-done` messages in the final
   response; the UI and the user need the progress as it happens.

4. If you need a file downloaded, send `download`:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" download --session-id "7f3ac2..." --url "https://example.com/archive.zip" --path "C:\Users\me\Downloads\archive.zip"
   ```

   `path` must be absolute and its last segment is the file name. The app
   creates parent directories, downloads with adaptive multi-threaded range
   requests (falling back to a single stream when necessary), and runs multiple
   downloads in parallel. You cannot set the thread count.

   The app never sends a result back. The CLI exits after writing the frame.
   Poll the destination yourself:

   - success: the target file appears atomically with the full content;
   - failure: the target stays unchanged/absent and `err.err` is appended in
     the target directory with timestamp, URL, path, bytes, and error.

   Remove stale target/`err.err` files before sending if you need an
   unambiguous result. Do not send `complete` until you have observed the
   target or `err.err`. The start is logged only; success shows a blue
   auto-close card, failure a red manual-close card.

   Add `--quiet` with an explicit `--session-id` if you do not want the CLI's
   local success JSON. Errors still print JSON.

5. If you are blocked and need a human decision, send `action` instead of
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

6. If you merely want to tell the user something and do not need an answer or
   an operation, send `notify`:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" notify --session-id "7f3ac2..." --message "第一轮分析已完成，正在修改实现。"
   ```

   This shows a blue auto-close “消息” card and plays the notify sound. It does
   not complete the task and does not clear action/error state. If you need a
   decision, use `action`, not `notify`.

   Agent-facing rule: **在需要对用户说话但无需使用报错时使用**。

7. If the task fails or encounters a blocking error, send `error`:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" error --session-id "7f3ac2..." --error "依赖安装失败：无法访问内部包仓库。"
   ```

   `resume` does not clear a reported error. After fixing or explaining it,
   continue and send `complete` when the whole task is done.

8. Report task completion immediately before your final answer:

   ```text
   python "<SKILL_DIR>/scripts/better_shutup_pipe.py" complete --session-id "7f3ac2..." --message "登录流程重构完成，测试通过。"
   ```

## Real-time progress reporting

**完成一步后立马汇报，实时跟进。** Keep the displayed session and plan
current while you work, not only at the end:

- Send `step-done` immediately after each planned step is actually complete,
  before starting the next step. Never batch step updates at the end.
- If a step is long-running, send a short `notify` at meaningful milestones
  (for example, “analysis complete, starting implementation”). Do not spam
  progress messages for every small action.
- If the plan changes, send `plan` as soon as the change is known. Keep the
  index/step text current.
- If you are blocked, send `action` immediately; after the user responds, send
  `resume`. If a real error occurs, send `error` immediately.
- The user should be able to see which step is current within seconds of it
  changing. Real-time reporting is part of the task, not an optional final
  summary.

## Status code reference

The status field is four bits. The app and this helper use the same values.
Their Chinese names are, in order: 注册、完成、需要操作、错误、撤销需要操作、
普通通知、计划更新、步骤完成、文件下载。

| Code | Name | CLI | Purpose | Recommended use |
|---|---|---|---|---|
| `0000` | Register | `register` | Create a session or update its display name | Start of tracked work. An existing ID updates the name only; it does not clear “需要操作”. |
| `0001` | Complete | `complete` | Mark the whole task complete | Only when the tracked **task** is truly finished, not when a conversational turn ends. This is the only status that completes a session and can start the shutdown countdown. |
| `0010` | Action needed | `action` | Ask the user for a decision or operation | When you cannot proceed without a human. The orange card must be closed manually. After the user responds, send `0100`. |
| `0011` | Error | `error` | Report a failure or blocking error | When the task failed or is blocked. The red card must be closed manually. Fix the issue and send `0001` when done; `0100` does not clear the error. |
| `0100` | Resume | `resume` | Acknowledge that the user answered/performed the action | Immediately after the user responds to `0010`. Clears only action-needed and dismisses its card. No new card or sound. |
| `0101` | Notify | `notify` | Inform the user without asking for action | Progress updates, observations, non-blocking context. Blue auto-close card. If you need an answer, use `0010`; if the task is done, use `0001`. |
| `0110` | Plan update | `plan` | Create or update plan steps | When you form or revise a plan, including late in the task. Top-level keys are 1-based indices; same index overwrites. Blue auto-close card. |
| `0111` | Step complete | `step-done` | Mark one existing plan step done | Report immediately as each step finishes, before starting the next. Requires an index previously sent by `0110`. Does not complete the task. Blue auto-close card. |
| `1000` | File download | `download` | Download a URL to an absolute local path | When you need a file locally without writing/running a download script. The app downloads in the background; poll the target or `err.err`. Start is logged only; success is a blue card, failure a red card. |
| `1001`–`1111` | Reserved | — | Future protocol use | Never send these. The current app rejects them. |

### Important state interactions

- `0000` with an existing session ID only updates the display name. It never
  clears action-needed or an error, and it does not reopen a completed session.
  Use `0100` to clear action-needed.
- `0010` and `0011` reopen a completed session and cancel a running shutdown
  countdown. This prevents shutdown while a human decision or a fix is still
  outstanding.
- `0101`, `0110`, `0111`, and `1000` are also treated as new work for this
  purpose: if the session was already complete, they reopen it and cancel the
  countdown. Do not send them after `0001` unless you intend to reopen the task.
- `0100` does not reopen a completed session and does not cancel a countdown.
- `0111` does not complete the session even when every step is done. Always
  send `0001` at the end.
- Overwriting a plan step with different text resets that step to incomplete.
  Re-sending the same text preserves its completed state.
- The app never sends download progress or results back to the Agent. The CLI's
  JSON is local output. Poll the target file for success, or `err.err` for
  failure; existing targets are preserved on failure and replaced atomically on
  success.
- A failed download is shown as a red card and appends `err.err`; it does not
  set the session's error state automatically. The Agent must inspect the
  result and send `0011` or retry as appropriate.
- Use `--quiet` with an explicit session ID to suppress successful CLI output;
  errors still print JSON.

## Choosing the right status

- Need the user to decide or do something → `0010`; then `0100` after they
  respond.
- Just need to say something → `0101`.
- Task failed or blocked by an error → `0011`; then `0001` after it is resolved.
- Have a plan or changed the plan → `0110`.
- Finished one planned step → `0111`.
- Need a file fetched to a local path → `1000`; then poll the target/`err.err`.
- Whole task finished → `0001`.

Do not use `0101` for a question that needs an answer. Do not use `0010` for a
casual progress update. Do not use `0001` merely because you are pausing.

## Subagents and nested agents

All subagents must also use BetterShutup for their own tracked work. The parent
agent is responsible for giving them the CLI path and the tracking rules,
because subagents may not load this skill automatically.

When spawning a subagent for a tracked task, include this in its prompt:

- The absolute path to `better_shutup_pipe.py` (the skill helper), or the
  installed skill directory. Do not make the subagent guess the working
  directory.
- A unique session ID, for example
  `<parent-session-id>-sub-<role>-<short-random>`, and a name such as
  `Parent Agent · Subtask name`.
- The instruction to register its own session and to send `complete`, `error`,
  or `action` for its own subtask. It must not complete the parent session.
- The rules in this skill: default tracking for documentation/directory/skill
  work, task-based completion (not turn-based), `--quiet` with an explicit
  session ID for low output, and the app lifecycle rule: it may start
  BetterShutup if needed but must never close, kill, or restart it or cancel a
  planned shutdown.
- The one-way rule: the app never sends results back. For `download`, poll the
  target file or `err.err` before reporting completion.
- A requirement to report its session ID and final status back to the parent.

A ready-to-use subagent instruction:

```text
Track this subtask with BetterShutup. Register a new session using
"python <absolute-skill-dir>/scripts/better_shutup_pipe.py" register
--name "<parent name> · <subtask>" --session-id "<parent-id>-sub-<unique>"
[--quiet]. Follow the BetterShutup skill defaults: track documentation and
directory work; completion is task-based, not turn-based; use action/resume
when the user must decide; use the app one-way only; poll target files or
err.err for downloads. You may start BetterShutup if it is not running, but
never close, kill, or restart it or cancel shutdown. Send complete/error for
this subtask before your final response, and report your session ID. Do not
complete the parent session.
```

- Subagents must mark each plan step with `step-done` as soon as it is actually
  completed, not only at the end of the subtask. They should also send a short
  `notify` at meaningful milestones in long steps; real-time follow-up is
  required.
- The parent must ensure every subagent session completes; a forgotten
  subagent session can block a planned shutdown.
- If a subagent cannot run the helper (for example, no Python/pipe access), it
  must tell the parent, which should track that subtask under the parent session
  or ask the user how to proceed.
- Subagents must not close or restart the shared app, even if they started a
  separate process for a test.

## Exit codes and failure handling

- Exit code `0`: the frame was written to the pipe. The protocol has no ACK,
  so a successful write does not prove the app accepted the session contents.
- Exit code `2`: the app is not running or the pipe could not be reached. If
  you know a safe launcher/path, you may try to start BetterShutup once;
  otherwise ask the user. Never stop, close, or restart the app. If it remains
  unavailable, tell the user once and continue the coding task without
  tracking; do not retry in a loop.
- Exit code `3`: the input was invalid (for example, an empty session ID, a
  session ID containing spaces, an invalid plan index, an oversized message, or
  missing/invalid command-line arguments).

All normal output and argument errors are one JSON object on stdout. Parse the
JSON rather than relying on stderr. With `--quiet`, successful commands print
nothing; errors still print JSON. PowerShell and Bash quoting are fine; pass
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
- `--quiet`: suppress successful output. `register --quiet` requires an explicit
  `--session-id`. Errors and argument problems still print JSON.

The default pipe is `\\.\pipe\BetterShutup`.

## Optional project-rule snippet

To opt a whole project into this workflow, add a rule such as:

```text
When the user asks to read/review documentation, browse or search a directory,
or use the better-shutup skill, use the skill by default: register one session
at task start, retain its session ID, and keep it open until the task itself is
finished. Send complete only when the task is done, not when the conversational
turn ends. Use action when a user decision is required, and resume after the
user responds. Plan updates, step completion, informational messages, and file
downloads are progress signals and never replace the final completion message.
Send `step-done` immediately after each step and use `notify` at meaningful
milestones; do not batch progress until the end. You may start BetterShutup if
it is not running, but never close, kill, or restart it, and never cancel a
planned shutdown; only the user may do that.
All subagents must register their own BetterShutup sessions, receive the CLI
path from the parent, and complete them; a forgotten subagent session can block
shutdown. Do not register unrelated tasks that the user did not ask to track.
```

This keeps sessions intentional and prevents stale sessions from blocking a
planned shutdown.

See `references/protocol.md` (bilingual, Chinese first) for the exact wire format, per-status semantics,
and examples used by the helper.
