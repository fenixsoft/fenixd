# fenixd — Fenix Loop Engineering Framework

> 基于 Claude Code 的自动化软件开发循环框架。将自然语言需求自动转化为「已实现、已验证、可推送」的代码，全程无需人工介入，仅保留一个推送审批门禁。

## 目录

- [作用](#作用)
- [原理](#原理)
- [依赖](#依赖)
- [安装](#安装)
- [使用方法](#使用方法)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [许可证](#许可证)

---

## 作用

fenixd 是一个**后台守护进程（daemon）**，它把「写软件」这个高度依赖人工的过程，编排成一个可自动推进的闭环：

1. **需求（Requirement）**：用户用一句话描述想法，需求 Agent 澄清并生成完整的 SPEC（proposal + design + specs + tasks）。
2. **实现（Implementer）**：实现 Agent 在隔离的 git worktree 中按 tasks.md 逐条实现并自测。
3. **验证（Verifier）**：验证 Agent 以「真实用户」视角独立测试实现结果，绝不信任实现 Agent。
4. **调度（PM Engine）**：按优先级、依赖与并发上限调度上述 Agent，检测卡顿并自动恢复。

最终产物直接推送到 `fenix/<spec-name>` 分支，等待人工审批推送（**唯一的人工门禁**）。

> 在 fenix-desktop（Chrome 新标签页扩展）项目中，fenixd 已自动完成了十余个 SPEC 的「实现 → 验证 → 修复」循环，是该框架的成熟实战验证。

## 原理

### 架构

```
config.yaml ──▶ ConfigLoader
                    │
STATE.md ──inotify──▶ EventBus ──▶ PM Engine（优先级/调度）
                                     │
                                     ▼
                        AgentRunner ──▶ claude 子进程 ──▶ WorktreeManager
                                     │
                                     ▼
                        Logger（JSON 结构化日志，写 .fenix/logs/fenixd.log）
```

- **StateMachine**：解析/维护 `STATE.md`，管理每个 SPEC 的状态与合法转换。
- **EventBus**：监听 `STATE.md` 变化（inotify + 周期轮询兜底），把状态事件分发给 PM Engine。
- **PMEngine**：按优先级排序、检查依赖、并发上限派发实现/验证 Agent，处理 bug-found → fix SPEC 的自动循环，并生成日报。
- **AgentRunner**：以子进程方式调用 `claude -p`，在工作区内运行实现/验证 Agent。
- **WorktreeManager**：为每个 Agent 运行创建/清理独立的 git worktree，隔离变更。
- **VerifyEngine**：确定性（零 LLM）的验证执行引擎，驱动 Playwright 做 DOM 断言与截图对比。

### SPEC 生命周期

```
drafted ─▶ ready ─▶ implementing ─▶ implemented ─▶ testing ─▶ verified ─▶ done ─▶ pushed
                        ▲                                      │
                        └──────────── fix SPEC ────────────────┘
                                      （bug-found 时自动创建，多轮迭代）
```

验证发现缺陷时，PM Engine 自动创建 `fix-<name>` SPEC 重新走一遍实现→验证循环，原 SPEC 回到 `implementing` 等待修复，直至全部通过。

### 验证流水线（三步）

1. **Planner（LLM）**：读取 SPEC，生成结构化测试场景。
2. **VerifyEngine（纯 Python）**：并行 Playwright → DOM 断言 → 截图对比，产出 JSON 报告。
3. **Judge（LLM）**：分析报告，判定「通过 / 发现 Bug」。

## 依赖

| 依赖 | 版本要求 | 用途 | 必需 |
|------|---------|------|------|
| Python | 3.10+ | 运行 fenixd 守护进程与全部核心模块 | ✅ |
| PyYAML | 任意 | 解析 `config.yaml` | ✅ |
| git | 任意 | worktree 隔离与分支管理 | ✅ |
| tmux | 任意 | 以守护会话方式托管 fenixd 进程 | ✅ |
| Claude Code CLI (`claude`) | 任意 | 实现/验证 Agent 的执行载体 | ✅ |
| Node.js | 18+ | 运行扩展集成验证脚本（`launch-chrome-extension.js`） | ⚠️ 仅 web/extension 项目 |
| Playwright（Python + Node） | 任意 | 浏览器驱动的验证测试 | ⚠️ 仅 web/extension 项目 |

> ⚠️ 表示按需依赖：仅当项目类型为 `web` 且需要浏览器级验证时才必需；`cli`/`library`/`api` 项目可不安装。

安装 PyYAML：

```bash
pip3 install pyyaml
```

> SPEC 生成已原生集成进 fenix：`/fenix-new` 使用内置生成器
> （`core/spec_gen.py` + `bin/fenix_spec.py`，数据 vendored 于 `schemas/spec-driven/`），
> 不再需要独立安装 openspec CLI 或 openspec skills。

## 安装

```bash
cd /path/to/fenixd
bash install.sh
```

`install.sh` 会：

1. 检查并提示安装缺失依赖（缺 PyYAML 时自动安装）；
2. 把 `skills/fenix-*` 软链到 `~/.claude/skills/`（供 Claude Code 的 `/fenix-*` 命令使用）；
3. 把 `fenix-init` 软链到 PATH（`~/.local/bin` 或 `/usr/local/bin`）。

> 框架代码**只保留一份**（本仓库）。项目通过软链接引用它，升级框架时只需更新本仓库，所有项目自动生效。

## 使用方法

### 1. 初始化项目

进入（或创建）你的项目目录，运行：

```bash
fenix-init [DIR] [--name 项目名] [--type web|cli|library|api]
```

生成工程骨架：`.fenix/`（配置 + 框架软链接 + 运行时目录）、`STATE.md`、`PROJECT_LOG.md`、`openspec/`、`.claude/agents/`、`.claude/worktrees/`，并追加 `.gitignore` 条目。

### 2. 启动框架

在项目目录内执行：

```
/fenix-setup
```

它会在 tmux 会话中启动守护进程。session 名由项目根路径派生（`fenixd-<目录名>-<哈希>`，见 `bin/fenix_session.py`），因此**同一台机器可同时用 fenixd 开发多个项目**，各自拥有独立的守护进程与 session，互不干扰。可通过 `tmux ls` 查看所有 fenixd session。

### 3. 创建需求

```
/fenix-new "添加用户登录功能"
```

需求 Agent 会澄清需求并生成完整 SPEC，注册到 `STATE.md`。fenixd 随后**全自动**完成实现与验证。

### 4. 查看进度

```
/fenix-status          # 总览：所有 SPEC 状态、守护进程健康、阻塞检测
/fenix-process <name>  # 查看某个 SPEC 的详细进展
```

### 5. 审批推送（唯一人工门禁）

```
/fenix-approve
```

审查 `done` 状态的 SPEC，确认后推送到远程分支。

### 常用命令速查

| 命令 | 作用 |
|------|------|
| `/fenix-setup` | 初始化 / 重启 fenixd |
| `/fenix-new "需求"` | 创建新需求 |
| `/fenix-status` | 查看框架状态 |
| `/fenix-process <name>` | 查看指定 SPEC 进展 |
| `/fenix-approve` | 审批并推送完成的工作 |

## 项目结构

```
fenixd/
├── README.md               # 本文档
├── install.sh              # 安装程序
├── fenix-init              # 项目初始化命令
├── fenixd.py               # 守护进程主入口
├── config.template.yaml    # 项目配置模板（fenix-init 渲染用）
├── launch-extension.cjs    # 扩展手动测试启动器
├── core/                   # 核心模块
│   ├── state_machine.py    # 状态机
│   ├── event_bus.py        # 事件总线
│   ├── pm_engine.py        # 调度引擎
│   ├── agent_runner.py     # Agent 执行器
│   ├── worktree_manager.py # worktree 管理
│   ├── config.py           # 配置加载
│   ├── logger.py           # 结构化日志
│   ├── spec_gen.py         # 原生 SPEC 生成器（new/status/instructions）
│   └── verify_engine/      # 确定性验证引擎
├── schemas/spec-driven/    # vendored spec-driven schema（模板与指令）
├── bin/                    # 辅助脚本
│   ├── fenix_dashboard.py  # 实时进度仪表盘
│   ├── fenix_process.py    # 单 SPEC 进展查看
│   ├── fenix_spec.py       # 原生 SPEC 生成 CLI（new/status/instructions）
│   ├── fenix_archive.py    # change 归档 CLI
│   ├── statusline.py       # Claude Code 状态栏
│   └── launch-chrome-extension.js  # 扩展集成验证（Tier 2）
├── skills/                 # Claude Code skills（/fenix-* 命令，含 fenix-new/fenix-archive）
├── agents/                 # 实现/验证 Agent 定义
├── templates/              # 工程骨架模板
└── tests/                  # 单元测试
```

## 配置说明

项目配置位于 `.fenix/config.yaml`（由 `config.template.yaml` 渲染生成），关键配置项：

- `project.type`：项目类型（web / cli / library / api）
- `agents.max_concurrent` / `max_retries` / `max_turns`：Agent 并发、重试与每轮上限
- `agents.use_new_verifier`：启用三步验证流水线
- `worktree.base_dir`：git worktree 存放目录
- `gates.require_push_approval`：推送审批门禁开关
- `commands.test` / `build` / `start`：项目自身的测试、构建、启动命令

## 许可证

MIT
