# CLI 操作手册

Fenix 提供 7 个 `/fenix-*` 斜杠命令（skill）与若干 `bin/` 辅助脚本。前者覆盖日常使用的完整动线——从提出需求、查看状态到最终审批，后者是支撑这些命令与 daemon 的底层工具。本章逐个讲解每个命令的用途、触发方式与产出。

## 七个 /fenix-* skill

### /fenix-new — 提出需求、创建 SPEC

想提出新需求时使用。既可以显式输入 `/fenix-new <需求描述>`，也可以只用自然语言描述你想构建的东西，Claude Code 会自动启用这个 skill。命令执行时先与你澄清需求，随后依次生成 proposal（需求背景）、design（详细设计）与 tasks.md（任务清单），创建 `spec/changes/<name>/` 目录并把 SPEC 置为 `drafted`。最终产出一份完整的 SPEC 文档集，以及 STATE.md 中对应的条目。

```
/fenix-new 我要做一个用户认证功能
```

### /fenix-setup — 初始化与启动

第一次在项目上启用 Fenix 时使用。命令检查 Python/Git/Node/tmux 依赖是否就绪，创建 `.fenix/` 目录与配置、生成 `.fenix/config.yaml`，最后启动 fenixd daemon。跑完之后你就得到了一个可运行的 Fenix 环境。

```
/fenix-setup
```

### /fenix-status — 状态面板

想快速了解项目整体进展时使用。命令读取 STATE.md 与 daemon 状态，输出一句话总结加各 SPEC 状态表，让你一眼看清当前是全部完成、进行中、卡住还是 daemon 已停止。输出内容详细完整，不输出 ASCII 装饰横幅。

```
/fenix-status
```

### /fenix-approve — 审批与推送

SPEC 完成验证进入 `done` 后使用。命令引导你审阅已完成的 SPEC，人工确认后执行 git push 推送远程仓库，状态随之从 `done` 流转到 `pushed`。这是 Fenix 中**唯一的人工门禁点**；是否走人工由 `.fenix/config.yaml` 的 `gates.approve_mode` 控制——`manual` 为人工审批，`auto` 则自动推送跳过确认。

### /fenix-dashboard — Web Dashboard

想用图形界面监控时使用。命令解析框架目录后启动（或复用已有）dashboard 进程，把当前项目注册进去，最后输出一个可直接粘贴到浏览器的访问 URL（`http://localhost:<port>`）。

### /fenix-process — 查看 SPEC 进展

想追踪某个 SPEC 的详细进展时使用。命令读取该 SPEC 的 tasks.md 勾选进度、fenixd 时间线与工作区状态，汇总成一份进展报告。

```
/fenix-process my-feature
```

### /fenix-archive — 归档已完成的 change

SPEC 走完全生命周期后使用。命令把 `spec/changes/<name>/` 目录移动到 `spec/archive/YYYY-MM-DD-<name>/`，只移动目录、不改写 STATE.md，完成后输出归档后的目录位置。

## bin/ 辅助脚本

| 脚本 | 用途 |
|------|------|
| `fenix_dashboard.py` | Dashboard 统一入口（--serve Web / --tui 终端 / --add-project 注册） |
| `fenix_spec.py` | 原生 SPEC 生成 CLI（提供 new change/status/instructions 子命令，输出 JSON，供 fenix-new 调用） |
| `fenix_process.py` | 查看指定 SPEC 的详细进展 |
| `fenix_session.py` | 计算项目唯一 tmux session 名并查询运行状态 |
| `fenixd_supervisor.py` | daemon 托管入口（框架守护进程由 supervisor 托管，而非 tmux） |
| `fenix_archive.py` | 归档已完成的 change 到 archive 目录 |
| `statusline.py` | Claude Code 状态栏：daemon 健康 / 进度条 / 活跃任务 / 告警 |
| `launch-chrome-extension.js` | 启动 Chrome 扩展（验证用） |
| `test_for.py` | 验证辅助脚本 |

## full 模式 vs fast-track 模式选择

Fenix 根据四维标准自动选择实现路径：

| 维度 | full 模式 | fast-track 模式 |
|------|-----------|-----------------|
| **影响面** | 多文件/跨模块 | 单文件 |
| **模块数** | >1 | ≤1 |
| **UI 变动** | 有 UI 交互 | 无 UI 或纯逻辑 |
| **场景数** | >3 个验证场景 | ≤3 个 |

四个条件全部满足时走 fast-track——单次调用完成实现+验证，更省 token；任何一个不满足则自动走 full 模式。

## 相关文档

- [快速上手](01-quick-start.md) — 端到端流程实操
- [核心概念与架构](02-concepts.md) — Agent 角色与模式原理
- [关键配置](09-config.md) — gates.approve_mode 等开关
