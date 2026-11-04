# BetterShutup wire protocol

BetterShutup listens on a Windows named pipe in **message mode**. Agents send
one complete frame per connection. The desktop app closes the connection after
reading the frame. There is no acknowledgement channel.

This is protocol revision 2: the status field is four bits wide. A revision-1
client that only understands `00`–`11` must be upgraded together with the app.

**Application lifecycle:** an Agent may start BetterShutup when tracking is
requested, but must never close, kill, or restart it. Only the user may close
the app or cancel a planned shutdown.

**Subagents:** every subagent doing tracked work should register its own
session with a unique ID and complete it. The parent must provide the absolute
helper path and ensure subagent sessions finish; a forgotten session can block
a planned shutdown.

## Pipe

- Default name: `\\.\pipe\BetterShutup`
- Override with the app's `--pipe` / `BETTER_SHUTUP_PIPE` setting and pass the
  same value to the agent helper with `--pipe` / `BETTER_SHUTUP_PIPE`.
- The server rejects clients from remote machines.

## Frame header

All integers are big-endian. The payload is UTF-8 JSON.

```text
byte 0:  0 0 0 0 S S S S
byte 1:  L23 ... L16
byte 2:  L15 ... L8
byte 3:  L7  ... L0
```

- `SSSS`: 4-bit status code. The upper four bits of byte 0 are reserved and
  must be zero.
- `L`: unsigned 24-bit length of the JSON **body** in bytes. The header itself
  is not included. Maximum body size is `0xFFFFFF` (16,777,215 bytes).

Frame bytes = 4-byte header + exactly `L` bytes of body. The app rejects
frames with a short body, trailing bytes, a reserved-bit violation, or an
undefined status code (`1001`–`1111`). The app never sends any frame back to
the agent; the standalone CLI's JSON output is local process output.

## Status codes

| Binary | Hex | Name | Direction | Card / sound | Completes task? |
|---|---:|---|---|---|---|
| `0000` | `00` | Register | Agent → app | none | No |
| `0001` | `01` | Complete | Agent → app | green “任务完成” / complete sound, auto-close | **Yes** |
| `0010` | `02` | Action needed | Agent → app | orange “需要操作” / action sound, manual close | No |
| `0011` | `03` | Error | Agent → app | red “错误” / error sound, manual close | No |
| `0100` | `04` | Resume | Agent → app | none | No |
| `0101` | `05` | Notify | Agent → app | blue “消息” / notify sound, auto-close | No |
| `0110` | `06` | Plan update | Agent → app | blue “计划更新” / notify sound, auto-close | No |
| `0111` | `07` | Step complete | Agent → app | blue “步骤完成” / notify sound, auto-close | No |
| `1000` | `08` | File download | Agent → app | none at start; blue success or red failure card when finished | No |
| `1001`–`1111` | `09`–`0F` | Reserved | — | — | — |

The `0100`–`0111` codes use the third bit (bit 2); `1000` now uses the fourth
bit (bit 3), and `1001`–`1111` remain reserved. The status byte for `0010` is
`0x02`, not decimal 10. The status byte for `0011` is `0x03`. Do not use the
reserved codes; the current app rejects them.

## Common field rules

Bodies are JSON objects. Unless a status says otherwise, unknown extra keys are
ignored; required fields must have the specified types.

- `session_id`: 1–128 characters. It must not contain whitespace or control
  characters. It identifies one tracked task.
- `session_name`: 1–256 characters, not blank, no NUL.
- Text fields allow Unicode and newlines but not NUL or lone surrogates.
- Plan indices are canonical positive decimal integers from `1` to `9999`
  written as JSON object keys (`"1"`, `"2"`, …). Leading zeros are invalid.
- Download `url` must be http/https. Download `path` must be an absolute
  Windows path whose last segment is the file name; relative paths and
  directory-only paths are rejected.

## Status semantics and recommended use

### `0000` Register

Body:

```json
{"session_name":"Claude Code · 优化登录流程","session_id":"7f3ac2e9d1ab"}
```

- New `session_id`: creates a session. A new session arriving while the
  shutdown countdown is running cancels that countdown, because new work has
  arrived. The plan stays armed.
- Existing `session_id`: updates only the display name. It does **not** clear
  action-needed, clear an error, reopen a completed session, or cancel a
  running countdown.

**Use when:** starting a tracked task, or refreshing the display name of an
existing session. If you need to clear “需要操作”, use `0100` instead.

### `0001` Complete

Body:

```json
{"session_id":"7f3ac2e9d1ab","message":"重构完成，测试通过。"}
```

Marks the session completed. If planned shutdown is armed and every registered
session is now complete, the app starts the countdown. A completed session can
be reopened by a later `0010`, `0011`, `0101`, `0110`, `0111`, or `1000`.

**Use when:** the tracked **task** is truly finished. Do not send it merely
because you are pausing or because the current conversational turn/answer is
ending, and do not rely on `0111` to complete the task. Completion is
task-based, not conversation-based; a follow-up that belongs to the same task
keeps the same session open.

### `0010` Action needed

Body:

```json
{"session_id":"7f3ac2e9d1ab","instruction":"需要确认是否保留旧版兼容层。"}
```

Shows a manual-close orange card. It does not complete the session. If the
session was already complete, it is reopened and the countdown is cancelled.
Only `0010` and `0011` represent a blocking human need (plus informational
statuses also reopen a completed session).

**Use when:** you cannot proceed until the user makes a decision or performs an
operation. Put the exact decision or operation in `instruction`. After the user
responds or performs it, send `0100` with the same session ID, then continue.

### `0011` Error

Body:

```json
{"session_id":"7f3ac2e9d1ab","error":"依赖安装失败：无法访问内部包仓库。"}
```

Shows a manual-close red card. It does not complete the session. If the session
was already complete, it is reopened and the countdown is cancelled. `0100`
does **not** clear an error state; only a later `0001` completes the work.

**Use when:** the task failed or hit a blocking error. After fixing or
explaining it, send `0001` when the task is actually done. The user can close
the error card manually.

### `0100` Resume / acknowledge action

Body:

```json
{"session_id":"7f3ac2e9d1ab","message":"用户已回答，继续执行。"}
```

`message` is optional. This is the dedicated “the user answered or performed
the requested operation” signal:

- Clears the session's **action-needed** state.
- Dismisses outstanding action-needed cards for that session.
- Produces no new card or sound.
- Does **not** clear an error state.
- Does **not** mark the session complete.
- Does **not** reopen a completed session or cancel a running countdown.
- `0000` for an existing session no longer performs this job.

**Use when:** immediately after the user answers an `0010` request. Then
continue the task and send `0001` when finished.

### `0101` Notify

Body:

```json
{"session_id":"7f3ac2e9d1ab","message":"已完成第一轮分析，正在修改实现。"}
```

Shows a blue auto-close “消息” card and plays the notify sound. It is purely
informational: it does not complete the task and does not clear action-needed
or error state. If the session was already complete, it reopens the session and
cancels the countdown.

**Use when:** you need to say something to the user but it is neither an error
nor a completion. Agent-facing rule: **在需要对用户说话但无需使用报错时使用**。
For example: progress updates, important observations, non-blocking context, or
“I am still working”. If you need a decision or an operation, use `0010`
instead. Do not use `0101` as a substitute for `0001`.

### `0110` Plan update

Body: a top-level mapping whose only reserved key is `session_id`; every other
key is a plan index:

```json
{
  "session_id":"7f3ac2e9d1ab",
  "1":"分析现有登录流程",
  "2":"修改认证模块",
  "3":"补充回归测试"
}
```

- The first `0110` for a session creates the plan. A later `0110` adds new
  indices and overwrites existing indices.
- Index keys are positive decimal integers from `1` to `9999`, sorted
  numerically in the UI. Leading zeros, `0`, non-numeric keys, and values above
  `9999` are rejected.
- Values are non-empty step text, at most 2000 characters. One message may
  contain at most 200 steps.
- Overwriting an index with different text resets that step to incomplete.
  Re-sending identical text preserves its completed state.
- Shows a blue auto-close “计划更新” card and plays the notify sound. It does
  not complete the task and does not clear action-needed or error state.
- If the session was already complete, the plan update reopens it and cancels
  the countdown.

**Use when:** you form or revise a plan, including starting a plan later in the
task. Send one `0110` with the steps you know now; later send `0110` again with
only the changed or new indices.

### `0111` Step complete

Body:

```json
{"session_id":"7f3ac2e9d1ab","step_index":"2","message":"认证模块修改完成。"}
```

`message` is optional. Marks an **existing** plan step as complete. An index
that was never registered by `0110` is a protocol error and is shown as a red
“协议错误” card. Only a valid step completion counts as new work; an
unknown-index `0111` does not reopen a completed session or cancel a countdown.

- Shows a blue auto-close “步骤完成” card and plays the notify sound.
- Does **not** complete the session, even when every step is complete. The app
  logs a reminder; the Agent must still send `0001`.
- If the session was already complete, a valid step completion reopens it and
  cancels the countdown.

**Use when:** a planned step is finished. Send `0111` immediately when each
step is actually complete; do not batch step updates at the end. Send `0001`
at the end of the whole task.

### `1000` File download

Body:

```json
{
  "session_id":"7f3ac2e9d1ab",
  "url":"https://example.com/archive.zip",
  "path":"C:\\Users\\me\\Downloads\\archive.zip"
}
```

The app downloads the URL to the absolute destination path. `path` must be an
absolute Windows path whose last segment is the file name; parent directories
are created automatically. The app never sends a result frame back to the
agent. The Agent must observe the destination itself:

- **Success:** the target file appears with the complete content. The app
  downloads to a temporary file and atomically replaces the target only after
  the whole download succeeds.
- **Failure:** the target is left unchanged (or absent) and the app appends an
  entry to `err.err` in the target's parent directory. The entry includes a
  timestamp, URL, target path, bytes downloaded, and the error. Success does
  not delete an existing `err.err`; remove stale target/error files before
  sending a download request.
- If an existing target is present, it is preserved on failure and replaced
  atomically on success.

The app uses adaptive multi-threaded range downloads: it starts four workers,
adjusts the worker count according to throughput, and has no fixed thread cap.
If the server does not support byte ranges, it falls back to a single stream.
Multiple file-download messages can run in parallel. The Agent cannot specify
the thread count.

A `1000` message counts as new work: if the session was complete it is reopened
and the countdown is cancelled. It does not complete the task and does not
clear action-needed or error state. The start is logged only; success shows a
blue auto-close card and the notify sound, failure shows a red manual-close
card and the error sound. If a download failure arrives after the session was
completed, the app treats it as unfinished work and cancels the countdown.

**Use when:** you need a file fetched to the local machine without writing and
running a download script. Do not send `0001` until you have observed the
target file or `err.err`; there is no app-to-agent response. The standalone
CLI prints its own local JSON; use `--quiet` with an explicit `--session-id`
if you do not want success output.

### Reserved `1001`–`1111`

Reserved for future protocol use. Current agents must not send them. The app
rejects them as undefined status codes.

## What happens to completion and shutdown

| Incoming status | Completed session | Action-needed | Error state | Running countdown |
|---|---|---|---|---|
| `0000` new ID | — | — | — | cancelled (new work) |
| `0000` existing ID | stays completed | preserved | preserved | unchanged |
| `0001` | becomes/stays completed | cleared | cleared | may start |
| `0010` | reopened | set | cleared | cancelled |
| `0011` | reopened | cleared | set | cancelled |
| `0100` | unchanged | cleared | preserved | unchanged |
| `0101` | reopened | preserved | preserved | cancelled |
| `0110` | reopened | preserved | preserved | cancelled |
| `0111` valid step | reopened | preserved | preserved | cancelled |
| `0111` unknown step | unchanged | preserved | preserved | unchanged |
| `1000` request | reopened | preserved | preserved | cancelled |
| `1000` success result | unchanged | preserved | preserved | unchanged |
| `1000` failure result | reopened if completed | preserved | preserved | cancelled if completed |

Countdown starts only when planned shutdown is armed, at least one session
exists, and all registered sessions are complete. `0101`, `0110`, `0111`, and
`1000` count as new work because a still-working agent should not be shut down
mid-task.

## Agent decision guide

1. **At task start:** send `0000` once, save `session_id`, and reuse it.
2. **If you have a plan:** send `0110` (optional; may be sent later).
3. **As each planned step finishes:** send `0111` with that index. This is
   progress, not task completion.
4. **If you need a file downloaded:** send `1000` with the URL and an absolute
   target path. The app downloads in the background and never sends a result
   back; poll the target file or `err.err` before continuing.
5. **If you only want to inform the user:** send `0101`. Do not use it for a
   question that needs an answer.
6. **If you need a human decision/operation:** send `0010`, wait, then send
   `0100` after the user responds. Continue the task.
7. **If the task fails:** send `0011`; after resolving it, send `0001` when the
   whole task is actually complete. `0100` does not clear the error.
8. **At the very end:** send `0001`. Never use `0111` as a substitute, and do
   not send informational statuses after `0001` unless you intend to reopen the
   session and cancel a pending shutdown.

## Examples

For the register example above, the header is `00` plus the 24-bit body length.
For a plan body with 100 UTF-8 bytes, the header is:

```text
06        status 0110 (plan update)
00 00 64  body length = 0x000064 = 100 bytes
...       UTF-8 JSON body
```

For `0100` resume, the first byte is `0x04`; for `0101` notify it is `0x05`;
for `0110` plan it is `0x06`; for `0111` step complete it is `0x07`; for
`1000` file download it is `0x08`.

## Connection semantics

- Open the pipe with write access.
- Write header + body in **one** `WriteFile` call. Do not split the header and
  body across separate writes: each write is a separate message in message
  mode.
- The helper does not read from the pipe and closes immediately after writing.
- The app processes the frame and closes its side.
- If the pipe is busy, wait and retry. If the app is not running, the helper
  reports a pipe-unavailable error.
- There is no ACK. A successful write only means the frame reached the pipe.

## JavaScript / Python outline

```python
body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
frame = bytes([status]) + len(body).to_bytes(3, "big") + body
# Write frame with a single WriteFile call to \\.\pipe\BetterShutup
```

Use the bundled helper rather than reimplementing ctypes unless necessary.

## CLI

```text
python better_shutup_pipe.py register  --name "Agent · Task"
python better_shutup_pipe.py complete  --session-id "<id>" --message "done"
python better_shutup_pipe.py action    --session-id "<id>" --instruction "..."
python better_shutup_pipe.py error     --session-id "<id>" --error "..."
python better_shutup_pipe.py resume    --session-id "<id>" [--message "..."]
python better_shutup_pipe.py notify    --session-id "<id>" --message "..."
python better_shutup_pipe.py plan      --session-id "<id>" --step 1 "..." --step 2 "..."
python better_shutup_pipe.py plan      --session-id "<id>" --steps-json '{"1":"...","2":"..."}'
python better_shutup_pipe.py step-done --session-id "<id>" --index 1 [--message "..."]
python better_shutup_pipe.py download  --session-id "<id>" --url "https://..." --path "C:\path\file.bin"
```

`resume` sends status `0100`; it no longer requires a name. `register` with an
existing ID sends `0000` and only updates the display name. `download` sends
`1000`; the app downloads asynchronously and the Agent must poll the target or
`err.err`.

Add `--quiet` to any command to suppress success output; `register --quiet`
requires an explicit `--session-id`. Errors still print JSON. The app itself
never sends anything back; the CLI's JSON is local process output.

The CLI prints one JSON object otherwise and uses exit code 0 for success, 2 for
pipe availability/write failures, and 3 for invalid input or command-line
arguments. Argument errors are emitted as a JSON object with `"ok": false`
rather than argparse's plain-text output.
