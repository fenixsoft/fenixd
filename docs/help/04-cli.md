# CLI 操作手册

Fenix 提供 7 个 `/fenix-*` 斜杠命令（skill）与若干 `bin/` 辅助脚本。本章逐个详解触发方式、交互流程、产出与示例。

## 七个 /fenix-* skill

### /fenix-new — 提出需求、创建 SPEC

- **触发**：`/fenix-new <需求描述>`；或当用户描述想构建的东西时自动启用
- **流程**：澄清需求 → 生成 proposal（需求背景）→ design（详细设计）→ tasks.md（任务清单）→ 创建 `openspec/changes/<name>/` → 状态 `drafted`
- **产出**：完整的 SPEC 文档集 + STATE.md 条目
- **示例**：
  ```
  /fenix-new 我要做一个用户认证功能
  ```

### /fenix-setup — 初始化与启动

- **触发**：`/fenix-setup`
- **流程**：检查依赖（Python/Git/Node/tmux）→ 创建 `.fenix/` 目录与配置 → 生成 `.fenix/config.yaml` → 启动 fenixd daemon
- **产出**：可运行的 Fenix 环境
- **示例**：
  ```
  /fenix-setup
  ```

### /fenix-status — 状态面板

- **触发**：`/fenix-status`
- **流程**：读取 STATE.md 与 daemon 状态 → 输出一句话总结 + 各 SPEC 状态表
- **产出**：当前整体状态（全部完成/进行中/卡住/停止）
- **注意**：禁止输出 ASCII 装饰横幅，内容需详细完整

### /fenix-approve — 审批与推送

- **触发**：`/fenix-approve`
- **流程**：审阅已完成 SPEC → 人工确认 → git push 远程仓库 → 状态 `done → pushed`
- **含义**：这是 Fenix 中**唯一的人工门禁点**
- **审批模式**：受 `.fenix/config.yaml` 的 `gates.approve_mode` 控制（`manual` 人工审批 / `auto` 自动推送）

### /fenix-dashboard — Web Dashboard

- **触发**：`/fenix-dashboard`
- **流程**：解析框架目录 → 启动（或复用）dashboard 进程 → 注册当前项目 → 输出可直接粘贴的访问 URL
- **产出**：`http://localhost:<port>` 浏览器入口

### /fenix-process — 查看 SPEC 进展

- **触发**：`/fenix-process <spec-name>`
- **流程**：读取 tasks.md 进度、fenixd 时间线、工作区状态
- **产出**：该 SPEC 的详细进展
- **示例**：
  ```
  /fenix-process my-feature
  ```

### /fenix-archive — 归档已完成的 change

- **触发**：`/fenix-archive`
- **流程**：把 `openspec/changes/<name>/` 移动到 `openspec/changes/archive/YYYY-MM-DD-<name>/`，只移动目录不改 STATE.md
- **产出**：归档后的目录

## bin/ 辅助脚本

| 脚本 | 用途 |
|------|------|
| `fenix_dashboard.py` | Dashboard 统一入口（--serve Web / --tui 终端 / --add-project 注册） |
| `fenix_spec.py` | 原生 SPEC 生成 CLI（等价 openspec CLI 的 new change/status/instructions，输出 JSON，供 fenix-new 调用） |
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

fast-track 单次调用完成实现+验证，更省 token；不满足条件时自动走 full 模式。

## 相关文档

- [快速上手](01-quick-start.md) — 端到端流程实操
- [核心概念与架构](02-concepts.md) — Agent 角色与模式原理
- [关键配置](08-config.md) — gates.approve_mode 等开关