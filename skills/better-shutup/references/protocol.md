# BetterShutup 线协议 / Wire Protocol

BetterShutup 使用 **消息模式** 的 Windows 命名管道。Agent 每个连接发送一个完整帧，桌面应用读取该帧后关闭连接。协议没有确认通道。

BetterShutup listens on a Windows named pipe in **message mode**. Agents send one complete frame per connection. The desktop app closes the connection after reading the frame. There is no acknowledgement channel.

这是协议修订 2：状态字段宽度为 4 位。只理解 `00`–`11` 的修订 1 客户端必须与应用一起升级。

This is protocol revision 2: the status field is four bits wide. A revision-1 client that only understands `00`–`11` must be upgraded together with the app.

**应用生命周期：** 用户要求跟踪时，Agent 可以启动 BetterShutup，但绝不能关闭、结束或重启它。只有用户可以关闭应用或取消计划关机。

**Application lifecycle:** an Agent may start BetterShutup when tracking is requested, but must never close, kill, or restart it. Only the user may close the app or cancel a planned shutdown.

**子 Agent：** 每个执行被跟踪工作的子 Agent 都应使用唯一 ID 注册自己的会话并完成它。父 Agent 必须提供 helper 的绝对路径，并确保子 Agent 的会话完成；遗忘的会话可能阻塞计划关机。

**Subagents:** every subagent doing tracked work should register its own session with a unique ID and complete it. The parent must provide the absolute helper path and ensure subagent sessions finish; a forgotten session can block a planned shutdown.

## 管道 / Pipe

- 默认名称：`\\.\pipe\BetterShutup`
- Default name: `\\.\pipe\BetterShutup`

- 可通过应用的 `--pipe` / `BETTER_SHUTUP_PIPE` 设置覆盖，并把相同的值用 `--pipe` / `BETTER_SHUTUP_PIPE` 传给 Agent helper。
- Override with the app's `--pipe` / `BETTER_SHUTUP_PIPE` setting and pass the same value to the agent helper with `--pipe` / `BETTER_SHUTUP_PIPE`.

- 服务器拒绝来自远程机器的客户端。
- The server rejects clients from remote machines.

## 帧头 / Frame Header

所有整数均采用大端字节序。载荷为 UTF-8 JSON。

All integers are big-endian. The payload is UTF-8 JSON.

```text
byte 0:  0 0 0 0 S S S S
byte 1:  L23 ... L16
byte 2:  L15 ... L8
byte 3:  L7  ... L0
```

- `SSSS`：4 位状态码。byte 0 的高 4 位保留，必须为零。
- `SSSS`: 4-bit status code. The upper four bits of byte 0 are reserved and must be zero.

- `L`：JSON **消息体** 的无符号 24 位长度（字节）。不包含帧头。消息体最大为 `0xFFFFFF`（16,777,215 字节）。
- `L`: unsigned 24-bit length of the JSON **body** in bytes. The header itself is not included. Maximum body size is `0xFFFFFF` (16,777,215 bytes).

帧字节数 = 4 字节帧头 + 恰好 `L` 字节消息体。应用会拒绝消息体过短、尾部多余字节、保留位违规或未定义状态码（`1001`–`1111`）的帧。应用绝不会向 Agent 回发任何帧；独立 CLI 的 JSON 输出只是本地进程输出。

Frame bytes = 4-byte header + exactly `L` bytes of body. The app rejects frames with a short body, trailing bytes, a reserved-bit violation, or an undefined status code (`1001`–`1111`). The app never sends any frame back to the agent; the standalone CLI's JSON output is local process output.

## 状态码 / Status Codes

| 二进制 / Binary | 十六进制 / Hex | 名称 / Name | 方向 / Direction | 卡片与音效 / Card & sound | 完成任务？/ Completes task? |
|---|---:|---|---|---|---|
| `0000` | `00` | 注册 / Register | Agent → 应用 / Agent → app | 无 / none | 否 / No |
| `0001` | `01` | 完成 / Complete | Agent → 应用 / Agent → app | 绿色“任务完成”卡片；完成音效；自动关闭 / green “任务完成” card; complete sound; auto-close | **是 / Yes** |
| `0010` | `02` | 需要操作 / Action needed | Agent → 应用 / Agent → app | 橙色“需要操作”卡片；操作音效；手动关闭 / orange “需要操作” card; action sound; manual close | 否 / No |
| `0011` | `03` | 错误 / Error | Agent → 应用 / Agent → app | 红色“错误”卡片；错误音效；手动关闭 / red “错误” card; error sound; manual close | 否 / No |
| `0100` | `04` | 恢复 / Resume | Agent → 应用 / Agent → app | 无 / none | 否 / No |
| `0101` | `05` | 通知 / Notify | Agent → 应用 / Agent → app | 蓝色“消息”卡片；通知音效；自动关闭 / blue “消息” card; notify sound; auto-close | 否 / No |
| `0110` | `06` | 计划更新 / Plan update | Agent → 应用 / Agent → app | 蓝色“计划更新”卡片；通知音效；自动关闭 / blue “计划更新” card; notify sound; auto-close | 否 / No |
| `0111` | `07` | 步骤完成 / Step complete | Agent → 应用 / Agent → app | 蓝色“步骤完成”卡片；通知音效；自动关闭 / blue “步骤完成” card; notify sound; auto-close | 否 / No |
| `1000` | `08` | 文件下载 / File download | Agent → 应用 / Agent → app | 开始时无卡片；完成后蓝色成功或红色失败卡片 / none at start; blue success or red failure card when finished | 否 / No |
| `1001`–`1111` | `09`–`0F` | 保留 / Reserved | — | — | — |

`0100`–`0111` 使用第 3 位（bit 2）；`1000` 使用第 4 位（bit 3），`1001`–`1111` 保持保留。`0010` 的状态字节是 `0x02`，不是十进制 10；`0011` 的状态字节是 `0x03`。不要使用保留状态码；当前应用会拒绝它们。

The `0100`–`0111` codes use the third bit (bit 2); `1000` uses the fourth bit (bit 3), and `1001`–`1111` remain reserved. The status byte for `0010` is `0x02`, not decimal 10. The status byte for `0011` is `0x03`. Do not use the reserved codes; the current app rejects them.

## 通用字段规则 / Common Field Rules

消息体是 JSON 对象。除非某个状态另有说明，未知的额外键会被忽略；必填字段必须具有指定类型。

Bodies are JSON objects. Unless a status says otherwise, unknown extra keys are ignored; required fields must have the specified types.

- `session_id`：1–128 个字符。不能包含空白或控制字符。它标识一个被跟踪任务。
- `session_id`: 1–128 characters. It must not contain whitespace or control characters. It identifies one tracked task.

- `session_name`：1–256 个字符，不能为空，不能包含 NUL。
- `session_name`: 1–256 characters, not blank, no NUL.

- 文本字段允许 Unicode 和换行，但不能包含 NUL 或孤立代理项。
- Text fields allow Unicode and newlines but not NUL or lone surrogates.

- 计划索引是 `1` 到 `9999` 的规范正十进制整数，写成 JSON 对象键（`"1"`、`"2"`……）。前导零无效。
- Plan indices are canonical positive decimal integers from `1` to `9999` written as JSON object keys (`"1"`, `"2"`, …). Leading zeros are invalid.

- 下载 `url` 必须是 http/https。下载 `path` 必须是绝对 Windows 路径，且最后一段是文件名；相对路径和只给目录的路径会被拒绝。
- Download `url` must be http/https. Download `path` must be an absolute Windows path whose last segment is the file name; relative paths and directory-only paths are rejected.

## 状态语义与建议用法 / Status Semantics and Recommended Use

### `0000` 注册 / Register

消息体：

Body:

```json
{"session_name":"Claude Code · 优化登录流程","session_id":"7f3ac2e9d1ab"}
```

- 新 `session_id`：创建会话。如果关机倒计时正在运行，新会话到达会取消该倒计时，因为有新工作到达；计划保持开启。
- New `session_id`: creates a session. A new session arriving while the shutdown countdown is running cancels that countdown, because new work has arrived. The plan stays armed.

- 已存在的 `session_id`：只更新显示名称。它**不会**清除需要操作状态、清除错误、重新打开已完成会话或取消正在运行的倒计时。
- Existing `session_id`: updates only the display name. It does **not** clear action-needed, clear an error, reopen a completed session, or cancel a running countdown.

**使用时机：** 开始一个被跟踪任务，或刷新已有会话的显示名称。如果需要清除“需要操作”，请改用 `0100`。

**Use when:** starting a tracked task, or refreshing the display name of an existing session. If you need to clear “需要操作”, use `0100` instead.

### `0001` 完成 / Complete

消息体：

Body:

```json
{"session_id":"7f3ac2e9d1ab","message":"重构完成，测试通过。"}
```

把会话标记为已完成。如果计划关机已开启且当前所有已注册会话都已完成，应用开始倒计时。已完成的会话可以之后被 `0010`、`0011`、`0101`、`0110`、`0111` 或 `1000` 重新打开。

Marks the session completed. If planned shutdown is armed and every registered session is now complete, the app starts the countdown. A completed session can be reopened by a later `0010`, `0011`, `0101`, `0110`, `0111`, or `1000`.

**使用时机：** 被跟踪的**任务**真正完成时。不要仅仅因为暂停、或当前对话轮次/回答结束就发送；也不要依赖 `0111` 完成任务。完成判断按任务而不是按对话轮次；属于同一任务的后续工作继续使用同一个会话。

**Use when:** the tracked **task** is truly finished. Do not send it merely because you are pausing or because the current conversational turn/answer is ending, and do not rely on `0111` to complete the task. Completion is task-based, not conversation-based; a follow-up that belongs to the same task keeps the same session open.

### `0010` 需要操作 / Action Needed

消息体：

Body:

```json
{"session_id":"7f3ac2e9d1ab","instruction":"需要确认是否保留旧版兼容层。"}
```

显示需要手动关闭的橙色卡片。它不会完成会话。如果会话已完成，会被重新打开并取消倒计时。只有 `0010` 和 `0011` 表示阻塞的人工需求（信息类状态也会重新打开已完成会话）。

Shows a manual-close orange card. It does not complete the session. If the session was already complete, it is reopened and the countdown is cancelled. Only `0010` and `0011` represent a blocking human need (plus informational statuses also reopen a completed session).

**使用时机：** 在你需要用户做决定或执行操作才能继续时。把确切的决定或操作写进 `instruction`。用户回复或执行后，使用同一个会话 ID 发送 `0100`，然后继续。

**Use when:** you cannot proceed until the user makes a decision or performs an operation. Put the exact decision or operation in `instruction`. After the user responds or performs it, send `0100` with the same session ID, then continue.

### `0011` 错误 / Error

消息体：

Body:

```json
{"session_id":"7f3ac2e9d1ab","error":"依赖安装失败：无法访问内部包仓库。"}
```

显示需要手动关闭的红色卡片。它不会完成会话。如果会话已完成，会被重新打开并取消倒计时。`0100` **不会**清除错误状态；只有之后的 `0001` 才完成工作。

Shows a manual-close red card. It does not complete the session. If the session was already complete, it is reopened and the countdown is cancelled. `0100` does **not** clear an error state; only a later `0001` completes the work.

**使用时机：** 任务失败或遇到阻塞错误时。修复或说明后，在任务真正完成时发送 `0001`。用户可以手动关闭错误卡片。

**Use when:** the task failed or hit a blocking error. After fixing or explaining it, send `0001` when the task is actually done. The user can close the error card manually.

### `0100` 恢复 / 确认操作 / Resume / Acknowledge Action

消息体：

Body:

```json
{"session_id":"7f3ac2e9d1ab","message":"用户已回答，继续执行。"}
```

`message` 可选。这是专门的“用户已回答或已执行所请求操作”信号：

`message` is optional. This is the dedicated “the user answered or performed the requested operation” signal:

- 清除会话的**需要操作**状态。
- Clears the session's **action-needed** state.

- 关闭该会话尚未关闭的需要操作卡片。
- Dismisses outstanding action-needed cards for that session.

- 不产生新卡片或声音。
- Produces no new card or sound.

- **不会**清除错误状态。
- Does **not** clear an error state.

- **不会**把会话标记为完成。
- Does **not** mark the session complete.

- **不会**重新打开已完成会话或取消正在运行的倒计时。
- Does **not** reopen a completed session or cancel a running countdown.

- 对已存在会话发送 `0000` 不再承担这一职责。
- `0000` for an existing session no longer performs this job.

**使用时机：** 用户回答 `0010` 请求之后立即发送。然后继续任务，完成后发送 `0001`。

**Use when:** immediately after the user answers an `0010` request. Then continue the task and send `0001` when finished.

### `0101` 通知 / Notify

消息体：

Body:

```json
{"session_id":"7f3ac2e9d1ab","message":"已完成第一轮分析，正在修改实现。"}
```

显示蓝色自动关闭的“消息”卡片并播放通知音效。它纯粹是信息性的：不会完成任务，也不会清除需要操作或错误状态。如果会话已完成，它会重新打开会话并取消倒计时。

Shows a blue auto-close “消息” card and plays the notify sound. It is purely informational: it does not complete the task and does not clear action-needed or error state. If the session was already complete, it reopens the session and cancels the countdown.

**使用时机：** 你需要向用户说些什么，但它既不是错误也不是完成。面向 Agent 的规则：**在需要对用户说话但无需使用报错时使用**。例如进度更新、重要观察、非阻塞上下文或“我还在处理”。如果需要决定或操作，请改用 `0010`。不要把 `0101` 当作 `0001` 的替代品。

**Use when:** you need to say something to the user but it is neither an error nor a completion. Agent-facing rule: **在需要对用户说话但无需使用报错时使用**. For example: progress updates, important observations, non-blocking context, or “I am still working”. If you need a decision or an operation, use `0010` instead. Do not use `0101` as a substitute for `0001`.

### `0110` 计划更新 / Plan Update

消息体：顶层映射，唯一保留键为 `session_id`；其他每个键都是计划索引：

Body: a top-level mapping whose only reserved key is `session_id`; every other key is a plan index:

```json
{
  "session_id":"7f3ac2e9d1ab",
  "1":"分析现有登录流程",
  "2":"修改认证模块",
  "3":"补充回归测试"
}
```

- 会话的第一个 `0110` 创建计划。之后的 `0110` 增加新索引并覆盖已有索引。
- The first `0110` for a session creates the plan. A later `0110` adds new indices and overwrites existing indices.

- 索引键是 `1` 到 `9999` 的正十进制整数，在 UI 中按数值排序。前导零、`0`、非数字键和大于 `9999` 的值会被拒绝。
- Index keys are positive decimal integers from `1` to `9999`, sorted numerically in the UI. Leading zeros, `0`, non-numeric keys, and values above `9999` are rejected.

- 值是非空步骤文本，最多 2000 个字符。一条消息最多包含 200 个步骤。
- Values are non-empty step text, at most 2000 characters. One message may contain at most 200 steps.

- 用不同文本覆盖某个索引会将该步骤重置为未完成。重复发送完全相同的文本会保留其完成状态。
- Overwriting an index with different text resets that step to incomplete. Re-sending identical text preserves its completed state.

- 显示蓝色自动关闭的“计划更新”卡片并播放通知音效。它不会完成任务，也不会清除需要操作或错误状态。
- Shows a blue auto-close “计划更新” card and plays the notify sound. It does not complete the task and does not clear action-needed or error state.

- 如果会话已完成，计划更新会重新打开它并取消倒计时。
- If the session was already complete, the plan update reopens it and cancels the countdown.

**使用时机：** 你形成或修改计划时，包括在任务进行到后面才开始制定计划。先发送一条包含当前已知步骤的 `0110`；之后只发送包含变化或新增索引的 `0110`。

**Use when:** you form or revise a plan, including starting a plan later in the task. Send one `0110` with the steps you know now; later send `0110` again with only the changed or new indices.

### `0111` 步骤完成 / Step Complete

消息体：

Body:

```json
{"session_id":"7f3ac2e9d1ab","step_index":"2","message":"认证模块修改完成。"}
```

`message` 可选。把一个**已存在**的计划步骤标记为完成。从未被 `0110` 注册过的索引属于协议错误，会显示红色“协议错误”卡片。只有合法的步骤完成才算新工作；未知索引的 `0111` 不会重新打开已完成会话，也不会取消倒计时。

`message` is optional. Marks an **existing** plan step as complete. An index that was never registered by `0110` is a protocol error and is shown as a red “协议错误” card. Only a valid step completion counts as new work; an unknown-index `0111` does not reopen a completed session or cancel a countdown.

- 显示蓝色自动关闭的“步骤完成”卡片并播放通知音效。
- Shows a blue auto-close “步骤完成” card and plays the notify sound.

- **不会**完成会话，即使所有步骤都已完成。应用会记录一条提醒；Agent 仍必须发送 `0001`。
- Does **not** complete the session, even when every step is complete. The app logs a reminder; the Agent must still send `0001`.

- 如果会话已完成，合法的步骤完成会重新打开它并取消倒计时。
- If the session was already complete, a valid step completion reopens it and cancels the countdown.

**使用时机：** 一个计划步骤完成时。每完成一个步骤就立即发送 `0111`；不要在最后批量补报。必须实时跟进：长步骤可以在关键节点发送 `0101`，计划/操作/错误变化应在发生时立即上报。整个任务结束时发送 `0001`。

**Use when:** a planned step is finished. Send `0111` immediately when each step is actually complete; do not batch step updates at the end. Real-time follow-up is required: long steps may send `0101` at meaningful milestones, and plan/action/error changes should be reported as they happen. Send `0001` at the end of the whole task.

### `1000` 文件下载 / File Download

消息体：

Body:

```json
{
  "session_id":"7f3ac2e9d1ab",
  "url":"https://example.com/archive.zip",
  "path":"C:\\Users\\me\\Downloads\\archive.zip"
}
```

应用把 URL 下载到绝对目标路径。`path` 必须是绝对 Windows 路径，且最后一段是文件名；父目录会自动创建。应用绝不会向 Agent 回发结果帧。Agent 必须自己观察目标文件：

The app downloads the URL to the absolute destination path. `path` must be an absolute Windows path whose last segment is the file name; parent directories are created automatically. The app never sends a result frame back to the agent. The Agent must observe the destination itself:

- **成功：** 目标文件出现且内容完整。应用先下载到临时文件，只有整个下载成功后才原子替换目标。
- **Success:** the target file appears with the complete content. The app downloads to a temporary file and atomically replaces the target only after the whole download succeeds.

- **失败：** 目标保持不变（或不存在），应用在目标父目录的 `err.err` 中追加一条记录。记录包含时间戳、URL、目标路径、已下载字节数和错误。成功不会删除已有 `err.err`；发送下载请求前请清理过期的目标/错误文件。
- **Failure:** the target is left unchanged (or absent) and the app appends an entry to `err.err` in the target's parent directory. The entry includes a timestamp, URL, target path, bytes downloaded, and the error. Success does not delete an existing `err.err`; remove stale target/error files before sending a download request.

- 如果目标已存在，失败时保留，成功时原子替换。
- If an existing target is present, it is preserved on failure and replaced atomically on success.

应用使用自适应多线程范围下载：从 4 个 worker 开始，根据吞吐量调整 worker 数量，没有固定线程上限。如果服务器不支持字节范围，回退到单流。多个文件下载消息可以并行执行。Agent 不能指定线程数。

The app uses adaptive multi-threaded range downloads: it starts four workers, adjusts the worker count according to throughput, and has no fixed thread cap. If the server does not support byte ranges, it falls back to a single stream. Multiple file-download messages can run in parallel. The Agent cannot specify the thread count.

`1000` 消息算作新工作：如果会话已完成，会重新打开并取消倒计时。它不会完成任务，也不会清除需要操作或错误状态。开始只写日志；成功显示蓝色自动关闭卡片并播放通知音效，失败显示红色手动关闭卡片并播放错误音效。如果下载失败在会话完成之后到达，应用会把它视为未完成工作并取消倒计时。

A `1000` message counts as new work: if the session was complete it is reopened and the countdown is cancelled. It does not complete the task and does not clear action-needed or error state. The start is logged only; success shows a blue auto-close card and the notify sound, failure shows a red manual-close card and the error sound. If a download failure arrives after the session was completed, the app treats it as unfinished work and cancels the countdown.

**使用时机：** 你需要把文件取到本机，又不想编写并运行下载脚本时。在观察到目标文件或 `err.err` 之前不要发送 `0001`；协议没有应用→Agent 的响应。独立 CLI 会输出自己的本地 JSON；如果不想看到成功输出，请使用 `--quiet` 并显式指定 `--session-id`。

**Use when:** you need a file fetched to the local machine without writing and running a download script. Do not send `0001` until you have observed the target file or `err.err`; there is no app-to-agent response. The standalone CLI prints its own local JSON; use `--quiet` with an explicit `--session-id` if you do not want success output.

### 保留 `1001`–`1111` / Reserved

保留供未来协议使用。当前 Agent 不得发送它们。应用会将其作为未定义状态码拒绝。

Reserved for future protocol use. Current agents must not send them. The app rejects them as undefined status codes.

## 完成与关机的状态变化 / What Happens to Completion and Shutdown

| 收到状态 / Incoming status | 已完成会话 / Completed session | 需要操作 / Action-needed | 错误状态 / Error state | 运行中的倒计时 / Running countdown |
|---|---|---|---|---|
| `0000` 新 ID / new ID | — | — | — | 取消（新工作）/ cancelled (new work) |
| `0000` 已存在 ID / existing ID | 保持完成 / stays completed | 保留 / preserved | 保留 / preserved | 不变 / unchanged |
| `0001` | 变为/保持完成 / becomes/stays completed | 清除 / cleared | 清除 / cleared | 可能开始 / may start |
| `0010` | 重新打开 / reopened | 设置 / set | 清除 / cleared | 取消 / cancelled |
| `0011` | 重新打开 / reopened | 清除 / cleared | 设置 / set | 取消 / cancelled |
| `0100` | 不变 / unchanged | 清除 / cleared | 保留 / preserved | 不变 / unchanged |
| `0101` | 重新打开 / reopened | 保留 / preserved | 保留 / preserved | 取消 / cancelled |
| `0110` | 重新打开 / reopened | 保留 / preserved | 保留 / preserved | 取消 / cancelled |
| `0111` 合法步骤 / valid step | 重新打开 / reopened | 保留 / preserved | 保留 / preserved | 取消 / cancelled |
| `0111` 未知步骤 / unknown step | 不变 / unchanged | 保留 / preserved | 保留 / preserved | 不变 / unchanged |
| `1000` 请求 / request | 重新打开 / reopened | 保留 / preserved | 保留 / preserved | 取消 / cancelled |
| `1000` 成功结果 / success result | 不变 / unchanged | 保留 / preserved | 保留 / preserved | 不变 / unchanged |
| `1000` 失败结果 / failure result | 若已完成则重新打开 / reopened if completed | 保留 / preserved | 保留 / preserved | 若已完成则取消 / cancelled if completed |

只有当计划关机已开启、至少存在一个会话，并且所有已注册会话都已完成时，倒计时才开始。`0101`、`0110`、`0111` 和 `1000` 算作新工作，因为仍在工作的 Agent 不应在任务中途被关机。

Countdown starts only when planned shutdown is armed, at least one session exists, and all registered sessions are complete. `0101`, `0110`, `0111`, and `1000` count as new work because a still-working agent should not be shut down mid-task.

## Agent 决策指南 / Agent Decision Guide

1. **任务开始时：** 发送一次 `0000`，保存 `session_id` 并复用它。
   **At task start:** send `0000` once, save `session_id`, and reuse it.

2. **如果有计划：** 发送 `0110`（可选；也可以稍后发送）。
   **If you have a plan:** send `0110` (optional; may be sent later).

3. **每个计划步骤完成时：** 用对应索引发送 `0111`。这是进度，不是任务完成。
   **As each planned step finishes:** send `0111` with that index. This is progress, not task completion.

4. **如果需要一个文件下载：** 用 URL 和绝对目标路径发送 `1000`。应用在后台下载且绝不回发结果；继续前请轮询目标文件或 `err.err`。
   **If you need a file downloaded:** send `1000` with the URL and an absolute target path. The app downloads in the background and never sends a result back; poll the target file or `err.err` before continuing.

5. **如果只想告知用户：** 发送 `0101`。不要用它来提出需要回答的问题。
   **If you only want to inform the user:** send `0101`. Do not use it for a question that needs an answer.

6. **如果需要人工决定/操作：** 发送 `0010`，等待，然后在用户回复后发送 `0100`。继续任务。
   **If you need a human decision/operation:** send `0010`, wait, then send `0100` after the user responds. Continue the task.

7. **如果任务失败：** 发送 `0011`；解决后，在整个任务真正完成时发送 `0001`。`0100` 不会清除错误。
   **If the task fails:** send `0011`; after resolving it, send `0001` when the whole task is actually complete. `0100` does not clear the error.

8. **最后：** 发送 `0001`。绝不要用 `0111` 替代；不要在 `0001` 之后发送信息类状态，除非你打算重新打开会话并取消待执行的关机。
   **At the very end:** send `0001`. Never use `0111` as a substitute, and do not send informational statuses after `0001` unless you intend to reopen the session and cancel a pending shutdown.

## 示例 / Examples

对于上面的注册示例，帧头为 `00` 加上 24 位消息体长度。对于消息体为 100 个 UTF-8 字节的计划请求，帧头为：

For the register example above, the header is `00` plus the 24-bit body length. For a plan body with 100 UTF-8 bytes, the header is:

```text
06        status 0110 (plan update)
00 00 64  body length = 0x000064 = 100 bytes
...       UTF-8 JSON body
```

对于 `0100` 恢复，第一个字节是 `0x04`；`0101` 通知是 `0x05`；`0110` 计划是 `0x06`；`0111` 步骤完成是 `0x07`；`1000` 文件下载是 `0x08`。

For `0100` resume, the first byte is `0x04`; for `0101` notify it is `0x05`; for `0110` plan it is `0x06`; for `0111` step complete it is `0x07`; for `1000` file download it is `0x08`.

## 连接语义 / Connection Semantics

- 以写权限打开管道。
- Open the pipe with write access.

- 在**一次** `WriteFile` 调用中写入帧头和消息体。不要把帧头和消息体拆成多次写入：在消息模式下，每次写入都是一条独立消息。
- Write header + body in **one** `WriteFile` call. Do not split the header and body across separate writes: each write is a separate message in message mode.

- helper 不从管道读取，写入后立即关闭。
- The helper does not read from the pipe and closes immediately after writing.

- 应用处理该帧并关闭自己这一侧。
- The app processes the frame and closes its side.

- 如果管道忙，等待并重试。如果应用未运行，helper 会报告管道不可用错误。
- If the pipe is busy, wait and retry. If the app is not running, the helper reports a pipe-unavailable error.

- 没有 ACK。写入成功只表示帧到达了管道。
- There is no ACK. A successful write only means the frame reached the pipe.

## JavaScript / Python 概要 / Outline

```python
body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
frame = bytes([status]) + len(body).to_bytes(3, "big") + body
# Write frame with a single WriteFile call to \\.\pipe\BetterShutup
```

除非必要，请使用随附的 helper，不要重新实现 ctypes。

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

`resume` 发送状态 `0100`；它不再需要名称。对已存在 ID 使用 `register` 会发送 `0000`，只更新显示名称。`download` 发送 `1000`；应用异步下载，Agent 必须轮询目标文件或 `err.err`。

`resume` sends status `0100`; it no longer requires a name. `register` with an existing ID sends `0000` and only updates the display name. `download` sends `1000`; the app downloads asynchronously and the Agent must poll the target or `err.err`.

对任意命令添加 `--quiet` 可抑制成功输出；`register --quiet` 需要显式指定 `--session-id`。错误仍会打印 JSON。应用本身绝不回发任何内容；CLI 的 JSON 是本地进程输出。

Add `--quiet` to any command to suppress success output; `register --quiet` requires an explicit `--session-id`. Errors still print JSON. The app itself never sends anything back; the CLI's JSON is local process output.

CLI 否则会打印一个 JSON 对象，并使用退出码 0 表示成功、2 表示管道不可用/写入失败、3 表示无效输入或命令行参数。参数错误会以 `"ok": false` 的 JSON 对象输出，而不是 argparse 的纯文本。

The CLI prints one JSON object otherwise and uses exit code 0 for success, 2 for pipe availability/write failures, and 3 for invalid input or command-line arguments. Argument errors are emitted as a JSON object with `"ok": false` rather than argparse's plain-text output.
