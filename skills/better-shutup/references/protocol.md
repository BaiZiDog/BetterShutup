# BetterShutup wire protocol

BetterShutup listens on a Windows named pipe in **message mode**. Agents send
one complete frame per connection. The desktop app closes the connection after
reading the frame. There is no acknowledgement channel.

## Pipe

- Default name: `\\.\pipe\BetterShutup`
- Override with the app's `--pipe` / `BETTER_SHUTUP_PIPE` setting and pass the
  same value to the agent helper with `--pipe` / `BETTER_SHUTUP_PIPE`.
- The server rejects clients from remote machines.

## Frame header

All integers are big-endian. The payload is UTF-8 JSON.

```text
byte 0:  0 0 0 0 0 0 SS
byte 1:  L23 ... L16
byte 2:  L15 ... L8
byte 3:  L7  ... L0
```

- `SS`: 2-bit status code. The upper six bits of byte 0 are reserved and must
  be zero.
- `L`: unsigned 24-bit length of the JSON **body** in bytes. The header itself
  is not included. Maximum body size is `0xFFFFFF` (16,777,215 bytes).

Frame bytes = 4-byte header + exactly `L` bytes of body. The app rejects
frames with a short body, trailing bytes, or a reserved-bit violation.

## Status codes

| Binary | Decimal | Meaning | JSON body fields |
|---|---:|---|---|
| `00` | 0 | Register session | `session_name`, `session_id` |
| `01` | 1 | Task complete | `session_id`, `message` |
| `10` | 2 | Action needed | `session_id`, `instruction` |
| `11` | 3 | Error | `session_id`, `error` |

Bodies are JSON objects. Unknown extra keys are ignored; required fields must
be strings. `session_id` is 1–128 characters and must not contain whitespace
or control characters. `session_name` is 1–256 characters and must not be
empty. Text fields allow Unicode and newlines but not NUL.

## Examples

### 00 Register

```json
{"session_name":"Claude Code · 优化登录流程","session_id":"7f3ac2e9d1ab"}
```

### 01 Complete

```json
{"session_id":"7f3ac2e9d1ab","message":"重构完成，测试通过。"}
```

### 10 Action needed

```json
{"session_id":"7f3ac2e9d1ab","instruction":"需要确认是否保留旧版兼容层。"}
```

### 11 Error

```json
{"session_id":"7f3ac2e9d1ab","error":"依赖安装失败：无法访问内部包仓库。"}
```

For the register example above (80 UTF-8 bytes of JSON), the complete header is
`00 00 00 50`:

```text
00        status 00 (register)
00 00 50  body length = 0x000050 = 80 bytes
7b 22 ... UTF-8 JSON body
```

The status byte for `10` is `0x02`, not decimal 10. The status byte for `11`
is `0x03`.

## Connection semantics

- Open the pipe with write access.
- Write header + body in **one** `WriteFile` call. Do not split the header and
  body across separate writes: each write is a separate message in message
  mode.
- The helper does not read from the pipe and closes immediately after writing.
- The app processes the frame and closes its side.
- If the pipe is busy, wait and retry. If the app is not running, the helper
  reports a pipe-unavailable error.

## JavaScript / Python outline

```python
body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
frame = bytes([status]) + len(body).to_bytes(3, "big") + body
# Write frame with a single WriteFile call to \\.\pipe\BetterShutup
```

Use the bundled helper rather than reimplementing ctypes unless necessary.

## CLI

```text
python better_shutup_pipe.py register --name "Agent · Task"
python better_shutup_pipe.py complete --session-id "<id>" --message "done"
python better_shutup_pipe.py action   --session-id "<id>" --instruction "..."
python better_shutup_pipe.py error    --session-id "<id>" --error "..."
```

The CLI prints one JSON object and uses exit code 0 for success, 2 for pipe
availability/write failures, and 3 for invalid input or command-line arguments.
Argument errors are emitted as a JSON object with `"ok": false` rather than
argparse's plain-text output.
