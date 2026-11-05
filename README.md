# BetterShutup

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

仓库：<https://github.com/BaiZiDog/BetterShutup>

> ⚠️ **早期开发阶段，尚未经过完整测试。** 真实关机流程可能受 Windows、权限和正在运行的应用影响。首次使用请先执行 `--dry-run`，不要在无人值守或含重要任务的机器上直接启用真实关机。

BetterShutup 是一个 Windows 多 Agent 协同工具：Agent 通过命名管道注册任务，汇报完成/需要操作/错误/普通消息，上报或更新执行计划与步骤进度，还可以让应用把 URL 文件下载到本地绝对路径；桌面应用用置顶卡片和不同音效提醒你，还可以在同一窗口查看某个会话的计划。当你开启“计划关机”后，所有已注册会话都完成时自动倒计时关机。

- 桌面应用：Python + tkinter，运行时无第三方依赖。
- Agent Skill：标准 `SKILL.md` + 独立 Python CLI，兼容 Claude Code、DSH、TRAE；父 Agent 和所有子 Agent 都可以用各自的会话 ID 调用。
- 应用图标：`better_shutup/assets/BetterShutup.ico`；源图保存在 `assets/BetterShutup-source.png`。
- 通信：Windows 消息模式命名管道，`\\.\pipe\BetterShutup`。
- 确认过的协议：4 字节头，低 4 位状态码 + 3 字节大端 JSON 长度；`1000` 为文件下载，`1001`–`1111` 预留给后续使用。
- 可选单文件构建：Nuitka 原生可执行文件，见“编译单文件 EXE”。

## 快速开始

### 环境

- Windows 10/11
- Python 3.10+（需包含 tkinter；当前开发环境为 Python 3.13.1）
- 应用和服务在同一台机器上，使用同一 Windows 用户会话

### 启动桌面应用

任选一种：

```text
双击 start.bat
双击 better_shutup\BetterShutup.pyw
python -m better_shutup
```

构建后的独立程序为 `dist\BetterShutup.exe`，不需要本机安装 Python。

`start-debug.bat` 会保留控制台，适合排查启动问题。

演练模式会走完整的消息、通知、倒计时流程，但不会真正关机：

```text
python -m better_shutup --dry-run
```

### 安装 Agent Skill

Skill 本体在 `skills/better-shutup/`。安装脚本只复制这一个目录，不会覆盖已有技能，除非显式加 `--force`。

```text
# 安装到当前项目的 Claude Code / DSH / TRAE
python tools/install_skill.py --scope project --agents claude,dsh,trae

# 安装到用户全局目录
python tools/install_skill.py --scope user --agents claude,dsh
```

目标目录：

| Agent | 项目级 | 用户级 |
|---|---|---|
| Claude Code | `.claude/skills/better-shutup` | `~/.claude/skills/better-shutup` |
| DSH | `.dsh/skills/better-shutup` | `~/.dsh/skills/better-shutup` |
| TRAE | `.trae/skills/better-shutup` | `~/.trae/skills/better-shutup` |
| TRAE CN | `.trae/skills/better-shutup` | `~/.trae-cn/skills/better-shutup` |

安装后重启 Agent（或在 TRAE 设置中导入技能）。当用户要求阅读/审查文档、浏览或搜索目录、或使用本 Skill 时，Agent 默认注册会话并跟踪；也支持明确的“用 BetterShutup 跟踪这个任务”“注册会话并汇报完成”“协调自动关机”等指令。会话是否结束按**任务本身**判定，而不是按当前对话轮次；任务未完成时，不会因为一轮回答结束就发送完成。无关的普通聊天不会自动占用会话。

**管开不管关**：Agent 可以在需要时启动 BetterShutup（使用实际安装路径、`start.bat` 或 `python -m better_shutup`），但不得关闭窗口、结束进程、重启应用或取消计划关机；这些操作只能由用户执行。Agent 启动应用后应保持其运行。

### 推荐工作流

1. 启动 BetterShutup，确认右上角显示“监听中”。
2. 让 Agent 使用 `better-shutup` Skill。阅读/审查文档、浏览/搜索目录或使用本 Skill 时，Agent 默认在任务开始时注册会话；可随时上报计划（`0110`），并用 `1000` 让应用下载文件到本地绝对路径。**每完成一个计划步骤就立即发送 `0111` 更新状态，实时跟进，不要等到最后批量补报；长步骤可在关键节点用 `0101` 汇报进度。** 任务真正完成时才发送完成消息（`0001`），不按对话轮次结束判定。所有子 Agent 也应各自注册会话并完成。应用只接收消息，不向 Agent 回发；CLI 输出只是本地进程输出。
3. 单击主窗口中的会话行，会在同一窗口切换到该会话的“执行计划”视图；点击“返回会话”回到列表。计划更新和步骤完成会实时刷新。
4. 在主窗口点“开启计划关机”。全部已注册会话完成时开始倒计时；倒计时期间若有新会话注册，本次倒计时会取消并等待新会话完成。
5. 倒计时窗口置顶显示剩余时间，随时可点“取消计划关机”。
6. 主窗口可移除失联会话、清除已完成会话，避免过期会话阻塞计划。

## 通知

| 状态 | 卡片 | 音效 | 关闭方式 |
|---|---|---|---|
| `0001` 完成任务 | 绿色“任务完成” | 上行三音 | 10 秒后自动关闭，也可手动关闭 |
| `0010` 需要操作 | 橙色“需要操作” | 双声提示 | 必须手动关闭 |
| `0011` 错误 | 红色“错误” | 低频蜂鸣 | 必须手动关闭 |
| `0101` 普通通知 | 蓝色“消息” | 轻提示音 | 10 秒后自动关闭，也可手动关闭 |
| `0110` 计划更新 | 蓝色“计划更新” | 轻提示音 | 10 秒后自动关闭，也可手动关闭 |
| `0111` 步骤完成 | 蓝色“步骤完成” | 轻提示音 | 10 秒后自动关闭，也可手动关闭 |
| `1000` 文件下载 | 开始不弹；成功蓝色“文件下载完成”，失败红色“文件下载失败” | 成功轻提示音；失败错误音 | 成功自动关闭；失败手动关闭 |
| `0100` 撤销需要操作 | 不弹卡片 | 无 | — |
| `0000` 注册 / 更新名称 | 不弹卡片 | 无 | — |

- 卡片位于主屏工作区右下角，置顶、不占用任务栏，可堆叠。
- 较长内容在卡片中截断，点击“查看完整内容”可打开完整文本窗口。
- 同一时间最多显示约 4 张卡片，其余排队；完成状态卡片会自动让出位置。
- 音效按队列顺序播放，避免连续消息互相打断。可在“提示音设置”中分别试听、替换或恢复内置音效。

## 窗口行为

- 所有应用窗口无原生标题栏/边框；主窗口、提示音设置、完整内容窗口和关机倒计时均使用自绘界面。
- 主窗口仍保留任务栏按钮和图标（通过 `WS_EX_APPWINDOW` + `WM_SETICON`），无边框不会让应用从任务栏消失。
- 主窗口、提示音设置和完整内容窗口按 **F** 切换全屏；焦点在输入框/下拉框/数值框时 F 仍用于输入。
- **关机倒计时窗口强制全屏**；倒计时窗口中的“取消计划关机”和右上角 × 始终可用。
- 主窗口和设置/详情窗口可通过拖动标题区域移动；右上角 × 关闭当前窗口。
- 通知卡片从右侧滑入并淡入，关闭时滑出淡出，卡片堆叠位置平滑过渡；自动关闭卡片底部有剩余时间进度线。
- 关机倒计时窗口淡入，最后 10 秒数字轻微脉冲；主窗口、设置、详情窗口启动时淡入。
- 通知卡片本身是无边框临时窗口，不参与 F 全屏切换。
- 系统原生确认对话框（例如退出确认）仍由 Windows 绘制。

## 计划关机

- 倒计时默认 60 秒，可在主界面设置为 5–3600 秒；仅对下一次倒计时生效。
- 开启计划关机且没有会话时，只进入等待状态。
- 开启计划关机时若已有会话且全部完成，立即开始倒计时。
- 倒计时期间若有新会话注册，本次倒计时取消，但计划保持开启；新会话完成后再倒计时。
- 已完成会话若又发送 `0010`（需要操作）、`0011`（错误）、`0101`（普通通知）、`0110`（计划更新）、`0111`（步骤完成）或 `1000`（文件下载），会被重新视为未完成并取消当前倒计时，避免在 Agent 仍在工作或仍需用户处理时关机。文件下载失败若发生在完成之后，也会重新打开会话并取消倒计时。
- `0100` 只撤销“需要操作”状态，不会重新打开已完成会话，也不会取消倒计时。
- 关闭计划开关、点击倒计时窗口取消、关闭应用，都会取消倒计时。
- 倒计时为应用内计时，不使用系统级延迟关机；退出或崩溃应用不会留下关机任务。
- 到点后调用 `shutdown.exe /s /t 0`，不强制关闭应用（不使用 `/f`）。Windows 或应用策略可能阻止关机；如果命令失败会显示错误卡片，如果 60 秒后系统仍未关机，应用会解除“关机中”状态并提示关机可能已被取消或阻止。

**请在测试时使用 `--dry-run`。** 正式版本只有在用户主动开启计划关机和倒计时结束后才会实际关机。

## 协议

> 协议版本 2：状态码扩为 4 位。桌面应用与 Agent Skill 必须一起升级；旧版 Skill 用 `0000` + `--name` 撤销“需要操作”的方式已不再生效，请改用 `0100`（新 `resume`）。

```text
byte0:  0 0 0 0 S S S S      状态码：4 位，高 4 位保留为 0
byte1:  L23 ... L16
byte2:  L15 ... L8
byte3:  L7  ... L0          L = UTF-8 JSON 正文的字节数
```

- 正文为 UTF-8 JSON 对象；长度仅计算正文，不含 4 字节头；最大 `0xFFFFFF` 字节。
- 每个管道连接只发送一帧，且必须用一次 `WriteFile` 写完头部和正文；服务端读完一帧后关闭连接。
- 协议没有 ACK。Agent CLI 返回成功只表示帧已写入管道，不表示应用已经受理。应用**只接收**消息，不会向 Agent 回发任何内容；CLI 的 JSON 只是本地进程输出。
- `0100`–`0111` 使用第三个二进制位（bit 2）；`1000` 使用第四个二进制位（bit 3），`1001`–`1111` 继续保留。
- 状态码：

| 状态 | 名称 | 作用 |
|---|---|---|
| `0000` | 注册会话 | 新 ID 注册；已有 ID 只更新名称，不撤销“需要操作” |
| `0001` | 完成任务 | 标记会话完成；全部完成且计划开启时开始关机倒计时 |
| `0010` | 需要操作 | 弹出需手动关闭的橙色卡片；不完成任务 |
| `0011` | 错误 | 弹出需手动关闭的红色卡片；不完成任务 |
| `0100` | 撤销需要操作 | 用户已回答/已完成操作；清除“需要操作”并关闭对应卡片，无新通知 |
| `0101` | 普通通知 | Agent 想对用户说话但无需报错；蓝色自动关闭卡片 |
| `0110` | 更新计划 | 顶层键值对，键为步骤索引；同一索引覆盖，首次发送即创建计划 |
| `0111` | 步骤完成 | 标记已有计划步骤完成；不会自动完成任务 |
| `1000` | 文件下载 | 下载 URL 到绝对本地路径；成功原子替换目标，失败追加 `err.err`；应用不回发结果 |
| `1001`–`1111` | 预留 | 当前应用会拒绝，Agent 不得使用 |

- JSON 示例：

```json
{"session_name": "Claude Code · 任务", "session_id": "abc-123"}
{"session_id": "abc-123", "message": "任务完成"}
{"session_id": "abc-123", "instruction": "请确认是否发布"}
{"session_id": "abc-123", "error": "依赖安装失败"}
{"session_id": "abc-123", "message": "用户已回答，继续执行"}
{"session_id": "abc-123", "message": "已完成第一轮分析"}
{"session_id": "abc-123", "1": "分析现有流程", "2": "修改实现"}
{"session_id": "abc-123", "step_index": "1", "message": "分析完成"}
{"session_id": "abc-123", "url": "https://example.com/a.zip", "path": "C:\\Users\\me\\Downloads\\a.zip"}
```

状态码 `0000` 与 `0100` 的职责已经分开：

- `0000` 新 ID：注册新会话；若倒计时正在运行，会因新工作到达而取消。
- `0000` 已有 ID：只更新名称，不撤销“需要操作”、不清除错误、不改变完成状态、不取消倒计时。
- `0100`：用户回答或完成操作后的确认信号；清除“需要操作”状态并关闭对应卡片，不产生新卡片或音效；不清除错误、不完成任务、不取消倒计时。
- `0101`、`0110`、`0111`、`1000` 若发送给已完成的会话，会重新打开该会话并取消倒计时（视为仍在工作）。这些状态也不清除“需要操作”或错误状态。
- `0110` 的索引是 `1`–`9999` 的正整数，直接作为顶层 JSON 键；重复发送同一索引会覆盖内容，内容变化时该步骤重新变为未完成。
- `0111` 只能标记此前 `0110` 已登记的索引；未知索引是协议错误，不会重新打开已完成会话或取消倒计时；全部步骤完成也不会自动完成任务，仍需发送 `0001`。
- `1000` 的目标路径必须是绝对路径，最后一段是文件名；应用自动创建父目录，使用自适应多线程分片下载（服务器不支持 Range 时回退单线程），成功时原子替换目标，失败时保留旧目标并追加 `err.err`。应用不会回发下载结果；Agent 必须自行轮询目标文件或 `err.err`。

完整线协议与每个状态码的建议使用场景见 `skills/better-shutup/references/protocol.md`。

## Agent CLI

Skill 自带一个仅依赖 Python 标准库的独立 CLI。它不导入桌面应用代码，可单独复制使用：

```text
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" register  --name "Claude Code · 重构 API"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" complete  --session-id "<id>" --message "测试通过"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" action    --session-id "<id>" --instruction "请确认是否发布"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" error     --session-id "<id>" --error "依赖安装失败"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" resume    --session-id "<id>" --message "用户已回答"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" notify    --session-id "<id>" --message "进度更新"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" plan      --session-id "<id>" --step 1 "分析" --step 2 "实现"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" plan      --session-id "<id>" --steps-json '{"1":"分析","2":"实现"}'
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" step-done --session-id "<id>" --index 1 --message "分析完成"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" download  --session-id "<id>" --url "https://example.com/a.zip" --path "C:\Users\me\Downloads\a.zip"
```

- `register` 未指定 `--session-id` 时生成 UUID，并输出 JSON 供 Agent 记录。
- `resume` 发送 `0100`，只清除“需要操作”并关闭对应卡片；不会清除错误或完成任务，也不需要 `--name`。
- `notify` 发送 `0101`，显示蓝色自动关闭卡片；适合无需用户回答的进度/说明。
- `plan` 发送 `0110`，可重复使用 `--step 索引 内容` 或一次传入 `--steps-json`；同一索引覆盖，首次发送即创建计划。
- `step-done` 发送 `0111`，只能标记此前 `0110` 已登记的索引；每完成一个步骤就应立即发送并更新状态，实时跟进，不要等到最后批量补报；长步骤可在关键节点用 `notify` 汇报进度；全部步骤完成也不会自动结束会话，仍需 `complete`。
- `download` 发送 `1000`，`--path` 必须是绝对路径；应用在后台下载，成功原子替换目标，失败追加 `err.err`。应用不回发结果，Agent 需轮询目标文件或 `err.err`。
- `--quiet` 可抑制成功输出；`register --quiet` 必须显式提供 `--session-id`，错误仍输出 JSON。
- 应用只接收消息，不向 Agent 回发；CLI 的 JSON 是本地输出。
- 所有子 Agent 也应使用同一个 CLI，以各自的 session ID 注册和完成任务；父 Agent 应把 CLI 绝对路径和规则传给子 Agent。
- 输出为 ASCII 安全 JSON；退出码：`0` 成功，`2` 管道不可用/写入失败，`3` 参数校验失败。
- `--pipe` / `BETTER_SHUTUP_PIPE` 可覆盖管道名；默认 `\\.\pipe\BetterShutup`。
- `--dry-run` 只校验并构造帧，不连接管道，用于诊断。

## 数据、设置与日志

默认数据目录：`%LOCALAPPDATA%\BetterShutup`

- `config.json`：倒计时秒数、四个音效覆盖路径。
- `sounds\complete.wav` / `action.wav` / `error.wav` / `notify.wav`：首次启动自动生成的内置音效。
- `better-shutup.log`：UTF-8 轮转日志。

可用环境变量/参数隔离数据：

```text
BETTER_SHUTUP_DATA_DIR=D:\temp\better-shutup-data
BETTER_SHUTUP_PIPE=BetterShutup-Test
python -m better_shutup --pipe BetterShutup-Test --data-dir D:\temp\better-shutup-data
```

计划开关、倒计时状态和会话列表只保存在内存中；重启应用会回到“未开启 + 空会话”的安全状态。

## 安全与限制

- 命名管道设置了 `PIPE_REJECT_REMOTE_CLIENTS`，但本地任意进程仍可尝试发送消息，也可以建立空闲连接占用管道实例/工作线程。只在你信任的机器和 Agent 环境中使用，并且只在需要时开启计划关机。
- **管开不管关**：Agent 可以启动 BetterShutup，但不得关闭窗口、结束进程、重启应用或取消计划关机；这些操作只能由用户执行。
- `1000` 文件下载会让应用访问 Agent 给出的 URL，并把内容写到 Agent 指定的任意绝对路径；只接受可信 Agent，注意磁盘、网络和路径覆盖风险。
- 应用只接收消息，不向 Agent 回发；CLI 输出是本地的。所有子 Agent 的会话也必须由父 Agent 确保完成，否则会阻塞计划关机。
- `0010`/`0011` 及其他通知里的指令、错误、消息和计划文本只用于展示，应用不会执行任何消息内容。
- 会话必须由 Agent 主动注册；符合协议的其他工具也可以发送消息。
- Agent 必须在任务结束时发送完成；失联会话会让应用持续等待，可在界面中移除。
- 应用必须保持运行；退出应用会取消应用内倒计时。
- 目前每个管道连接只接受一帧；没有 ACK、心跳或断线重连。Agent CLI 每次命令使用一条新连接。

## 开发与测试

项目只使用标准库；测试使用 pytest（开发依赖，不参与运行时）。

```text
python -m pytest -q
```

测试覆盖协议位布局与校验、状态机、真实 Windows 命名管道（并发、大帧、快速连续消息、异常帧）、文件下载（Range 分片、单线程回退、失败 `err.err`、并发任务）、Skill CLI 端口协议一致性、配置、音效生成和关机命令参数。GUI 与倒计时流程可用 `--dry-run` 手工/自动体验。

```text
better_shutup/        桌面应用（协议、核心状态机、Win32 管道、Tk UI）
  BetterShutup.pyw    无控制台启动入口，也是 Nuitka 构建入口
  downloader.py       自适应多线程分片下载、原子替换与 err.err
  ui/animation.py     缓出淡入与动画辅助
  assets/             应用图标（ICO）
assets/               图标源图与导出的 PNG
skills/better-shutup/ 标准 Agent Skill + 独立 CLI + 协议说明
tools/install_skill.py
tools/build_exe.py    Nuitka 单文件构建脚本
tests/
要求.md
```

## 编译单文件 EXE

需要 Windows 和 64 位 Python 3.10+。构建统一使用 Zig 作为 C 编译器（`ziglang` 已包含在 build 依赖中）；Python 3.13 下不能依赖 Nuitka 自动下载 MinGW64。

```text
python -m pip install -e ".[build]"
build.bat
```

也可以直接运行：

```text
python tools/build_exe.py
```

产物：

```text
dist\BetterShutup.exe
dist\LICENSE.txt
dist\NOTICE.txt
dist\SHA256SUMS.txt
```

构建参数：Nuitka `--onefile`、`--zig`、Tkinter 插件、Windows GUI 模式（无控制台）、应用图标 `--windows-icon-from-ico`，并通过 `--include-package-data=better_shutup` 打包窗口图标。首次构建会安装/准备 Zig 工具链，耗时较长；如果自动下载失败，可先执行 `python -m pip install ziglang`，再重新运行 `python tools/build_exe.py`。

说明：Nuitka 将 Python 编译为原生机器码，其代码生成链路以 C 为后端，并不是把项目重写成手写 C++；这里交付的是原生单文件 Windows 可执行程序。

## 许可证

本项目使用 [GNU General Public License v3.0](LICENSE)（GPL-3.0-only）。

对应源码即本仓库；分发编译产物时请同时遵守 GPLv3 的源码提供要求。

## Agent Skill 兼容性参考

- Claude Code Skills：<https://code.claude.com/docs/zh-CN/skills>
- DSH Skills 目录与格式说明：<https://github.com/TimeMachineLab/awesome-deepseek-harness-zh/blob/main/docs/skills.md>
- TRAE Skills：<https://docs.trae.ai/ide/skills> / <https://docs.trae.cn/ide_skills>

三者的技能核心都是包含 `SKILL.md` 的目录；本项目的 Skill 只使用标准的 `name`、`description` frontmatter 和相对资源目录，并明确要求 Agent 不假设当前工作目录。
