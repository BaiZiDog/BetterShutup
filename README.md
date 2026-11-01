# BetterShutup

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

仓库：<https://github.com/BaiZiDog/BetterShutup>

> ⚠️ **早期开发阶段，尚未经过完整测试。** 真实关机流程可能受 Windows、权限和正在运行的应用影响。首次使用请先执行 `--dry-run`，不要在无人值守或含重要任务的机器上直接启用真实关机。

BetterShutup 是一个 Windows 多 Agent 协同工具：Agent 通过命名管道注册任务、汇报完成/需要操作/错误，桌面应用用置顶卡片和不同音效提醒你；当你开启“计划关机”后，所有已注册会话都完成时自动倒计时关机。

- 桌面应用：Python + tkinter，运行时无第三方依赖。
- Agent Skill：标准 `SKILL.md` + 独立 Python CLI，兼容 Claude Code、DSH、TRAE。
- 通信：Windows 消息模式命名管道，`\\.\pipe\BetterShutup`。
- 确认过的协议：4 字节头，低 2 位状态码 + 3 字节大端 JSON 长度。
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

安装后重启 Agent（或在 TRAE 设置中导入技能）。之后当你说“用 BetterShutup 跟踪这个任务”“注册会话并汇报完成”“协调自动关机”等，Agent 会被引导使用该 Skill。Skill 只在明确要求跟踪时注册，普通任务不会自动占用会话。

### 推荐工作流

1. 启动 BetterShutup，确认右上角显示“监听中”。
2. 让 Agent 使用 `better-shutup` Skill；Agent 在任务开始时注册，结束时发送完成消息。
3. 在主窗口点“开启计划关机”。全部已注册会话完成时开始倒计时；倒计时期间若有新会话注册，本次倒计时会取消并等待新会话完成。
4. 倒计时窗口置顶显示剩余时间，随时可点“取消计划关机”。
5. 主窗口可移除失联会话、清除已完成会话，避免过期会话阻塞计划。

## 通知

| 状态 | 卡片 | 音效 | 关闭方式 |
|---|---|---|---|
| `01` 完成任务 | 绿色“任务完成” | 上行三音 | 10 秒后自动关闭，也可手动关闭 |
| `10` 需要操作 | 橙色“需要操作” | 双声提示 | 必须手动关闭 |
| `11` 错误 | 红色“错误” | 低频蜂鸣 | 必须手动关闭 |

- 卡片位于主屏工作区右下角，置顶、不占用任务栏，可堆叠。
- 较长内容在卡片中截断，点击“查看完整内容”可打开完整文本窗口。
- 同一时间最多显示约 4 张卡片，其余排队；完成状态卡片会自动让出位置。
- 音效按队列顺序播放，避免连续消息互相打断。可在“提示音设置”中分别试听、替换或恢复内置音效。

## 计划关机

- 倒计时默认 60 秒，可在主界面设置为 5–3600 秒；仅对下一次倒计时生效。
- 开启计划关机且没有会话时，只进入等待状态。
- 开启计划关机时若已有会话且全部完成，立即开始倒计时。
- 倒计时期间若有新会话注册/重新注册，本次倒计时取消，但计划保持开启；新会话完成后再倒计时。
- 已完成会话若又发送 `10`/`11`，会被重新视为未完成并取消当前倒计时，避免在仍需操作或仍有错误时关机。
- 关闭计划开关、点击倒计时窗口取消、关闭应用，都会取消倒计时。
- 倒计时为应用内计时，不使用系统级延迟关机；退出或崩溃应用不会留下关机任务。
- 到点后调用 `shutdown.exe /s /t 0`，不强制关闭应用（不使用 `/f`）。Windows 或应用策略可能阻止关机；如果命令失败会显示错误卡片，如果 60 秒后系统仍未关机，应用会解除“关机中”状态并提示关机可能已被取消或阻止。

**请在测试时使用 `--dry-run`。** 正式版本只有在用户主动开启计划关机和倒计时结束后才会实际关机。

## 协议

```text
byte0:  0 0 0 0 0 0 SS      状态码：00/01/10/11，高 6 位保留为 0
byte1:  L23 ... L16
byte2:  L15 ... L8
byte3:  L7  ... L0          L = UTF-8 JSON 正文的字节数
```

- 正文为 UTF-8 JSON 对象；长度仅计算正文，不含 4 字节头；最大 `0xFFFFFF` 字节。
- 每个管道连接只发送一帧，且必须用一次 `WriteFile` 写完头部和正文；服务端读完一帧后关闭连接。
- 协议没有 ACK。Agent CLI 返回成功只表示帧已写入管道，不表示应用已经受理。
- 字段：

```json
{"session_name": "Claude Code · 任务", "session_id": "abc-123"}
{"session_id": "abc-123", "message": "任务完成"}
{"session_id": "abc-123", "instruction": "请确认是否发布"}
{"session_id": "abc-123", "error": "依赖安装失败"}
```

状态码 `00` 有两种作用：

- `session_id` 不存在：注册一个新会话；若倒计时正在运行，会因新工作到达而取消。
- `session_id` 已存在：这是 Agent 在用户回答或完成操作后的确认信号，用来清除该会话的“需要操作”状态、关闭该会话尚未关闭的“需要操作”通知卡片，使界面恢复正常进行中状态。它会更新会话名称，但不会改变完成状态、不会清除错误状态，也不会取消正在运行的关机倒计时。
- 两种 `00` 都不新增通知卡片，也不播放提示音。

Agent Skill 提供 `resume` 命令专门发送这种确认；普通 `register` 也可以对已有 ID 发送 `00`。

完整线协议见 `skills/better-shutup/references/protocol.md`。

## Agent CLI

Skill 自带一个仅依赖 Python 标准库的独立 CLI。它不导入桌面应用代码，可单独复制使用：

```text
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" register --name "Claude Code · 重构 API"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" resume   --session-id "<id>" --name "Claude Code · 重构 API"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" complete --session-id "<id>" --message "测试通过"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" action   --session-id "<id>" --instruction "请确认是否发布"
python "<SKILL_DIR>/scripts/better_shutup_pipe.py" error    --session-id "<id>" --error "依赖安装失败"
```

- `register` 未指定 `--session-id` 时生成 UUID，并输出 JSON 供 Agent 记录。
- `resume` 用已有 ID 发送状态 `00`，清除“需要操作”状态；不会生成通知。
- 输出为 ASCII 安全 JSON；退出码：`0` 成功，`2` 管道不可用/写入失败，`3` 参数校验失败。
- `--pipe` / `BETTER_SHUTUP_PIPE` 可覆盖管道名；默认 `\\.\pipe\BetterShutup`。
- `--dry-run` 只校验并构造帧，不连接管道，用于诊断。

## 数据、设置与日志

默认数据目录：`%LOCALAPPDATA%\BetterShutup`

- `config.json`：倒计时秒数、三个音效覆盖路径。
- `sounds\complete.wav` / `action.wav` / `error.wav`：首次启动自动生成的内置音效。
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
- `10`/`11` 通知里的指令/错误文本只用于展示，应用不会执行任何消息内容。
- 会话必须由 Agent 主动注册；符合协议的其他工具也可以发送消息。
- Agent 必须在任务结束时发送完成；失联会话会让应用持续等待，可在界面中移除。
- 应用必须保持运行；退出应用会取消应用内倒计时。
- 目前每个管道连接只接受一帧；没有 ACK、心跳或断线重连。Agent CLI 每次命令使用一条新连接。

## 开发与测试

项目只使用标准库；测试使用 pytest（开发依赖，不参与运行时）。

```text
python -m pytest -q
```

测试覆盖协议位布局与校验、状态机、真实 Windows 命名管道（并发、大帧、快速连续消息、异常帧）、Skill CLI 端口协议一致性、配置、音效生成和关机命令参数。GUI 与倒计时流程可用 `--dry-run` 手工/自动体验。

```text
better_shutup/        桌面应用（协议、核心状态机、Win32 管道、Tk UI）
  BetterShutup.pyw    无控制台启动入口，也是 Nuitka 构建入口
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

构建参数：Nuitka `--onefile`、`--zig`、Tkinter 插件、Windows GUI 模式（无控制台）。首次构建会安装/准备 Zig 工具链，耗时较长；如果自动下载失败，可先执行 `python -m pip install ziglang`，再重新运行 `python tools/build_exe.py`。

说明：Nuitka 将 Python 编译为原生机器码，其代码生成链路以 C 为后端，并不是把项目重写成手写 C++；这里交付的是原生单文件 Windows 可执行程序。

## 许可证

本项目使用 [GNU General Public License v3.0](LICENSE)（GPL-3.0-only）。

对应源码即本仓库；分发编译产物时请同时遵守 GPLv3 的源码提供要求。

## Agent Skill 兼容性参考

- Claude Code Skills：<https://code.claude.com/docs/zh-CN/skills>
- DSH Skills 目录与格式说明：<https://github.com/TimeMachineLab/awesome-deepseek-harness-zh/blob/main/docs/skills.md>
- TRAE Skills：<https://docs.trae.ai/ide/skills> / <https://docs.trae.cn/ide_skills>

三者的技能核心都是包含 `SKILL.md` 的目录；本项目的 Skill 只使用标准的 `name`、`description` frontmatter 和相对资源目录，并明确要求 Agent 不假设当前工作目录。
