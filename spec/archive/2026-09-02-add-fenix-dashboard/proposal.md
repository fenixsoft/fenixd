## Why

Fenixd 目前唯一的进度观测手段是终端 TUI（`bin/fenix_dashboard.py`）与 `/fenix-status` skill，二者都只能看到「结果态」（SPEC 状态、任务勾选、验证摘要），无法看到「过程态」。当某个实现或验证 Agent 长时间运行却不写文件时，用户完全不知道 Fenixd 此刻在干什么；测试发现的 bug、失败截图、逐场景断言结果也只能通过翻找零散 markdown 文件获取。此外，用户往往同时用 Fenixd 驱动多个项目，却没有任何统一视图。

需要一个**独立进程的 Web Dashboard**：跨项目展示 SPEC 状态统计、任务进度、当前问题，并能下钻到每个 SPEC 的完整细节（bug 内容、失败截图、测试结果、运行中 Agent 的 LLM 对话），让长跑的 Agent 也「可见」。

## What Changes

- 新增 **Web Dashboard 服务器**（独立进程）：监听 localhost，聚合多项目的 `STATE.md` / tasks / 验证产物 / 事件日志，提供 REST 数据 API 与静态资源（含截图）服务，秒级刷新。
- 新增 **多项目发现与注册**：中心配置文件（`~/.config/fenixd/dashboard.yaml`）显式注册项目 + 可选目录扫描自动发现，两者结合。
- 新增 **Agent 运行过程落盘**（框架侧改造 `core/agent_runner.py`）：将 `claude -p` 子进程从阻塞式 `subprocess.run(capture_output=True)` 改为流式 `Popen`，用 `--output-format stream-json` 把运行期的 LLM 对话、工具调用、心跳逐行写入 `.fenix/runs/<run_id>.jsonl`，供 Dashboard 实时消费——这是「想知道 Fenixd 此刻在干什么」的关键数据源。
- 新增 **前端界面**：概览页（跨项目状态统计、总进度、当前问题）+ SPEC 详情页（任务清单、验证进度、bug 列表、失败截图缩略图、逐场景断言结果、运行中 Agent 的实时活动与 LLM 对话、历史运行记录）。
- 新增 **`/fenix-dashboard` skill** 与一键安装集成：在任意 Fenixd 项目内执行即可启动（或复用）Dashboard 服务并把当前项目注册进监控列表，输出可粘贴到浏览器的 URL。
- 保留现有终端 TUI 不动（`bin/fenix_dashboard.py` 增加 `--serve` 等子命令入口，默认进入 Web 模式；TUI 逻辑保留为 `--tui` 选项）。

## Capabilities

### New Capabilities
- `agent-run-artifacts`: 框架侧将 Agent 运行过程（LLM 对话、工具调用、心跳、最终结果）以结构化、可追加方式落盘到 `.fenix/runs/`，供 Dashboard 实时读取；覆盖 implementer / verifier / planner 全部 Agent 类型。
- `dashboard-server`: 独立 Web 服务器进程，负责多项目发现与注册、跨项目数据聚合 API、截图等静态资源服务、秒级刷新；仅监听 localhost。
- `dashboard-ui`: 浏览器前端，提供跨项目概览与逐 SPEC 详情视图，包含状态统计、任务进度、当前问题、bug 详情、失败截图、测试结果与运行中 Agent 实时活动/LLM 对话展示。
- `fenix-dashboard-skill`: 一键安装（install.sh 自动接入新 skill）+ `/fenix-dashboard` skill，启动当前项目的监控并输出 URL。

### Modified Capabilities
<!-- 无既有 spec，暂无修改 -->

## Impact

- **核心代码**：`core/agent_runner.py`（`_run_claude` 由阻塞改为流式落盘，需保证最终 result 解析与现有调用方兼容）、`core/logger.py`（可选：Agent 心跳事件）。
- **新增模块**：`core/dashboard/` 包（server / data / registry / 前端静态资源），`bin/fenix_dashboard.py` 改为统一入口（`--serve` / `--tui` / `--add-project` / `--port`）。
- **新增 skill**：`skills/fenix-dashboard/SKILL.md`（install.sh 已按 `skills/*/` 自动软链，无需额外改动）。
- **运行时目录**：每个项目新增 `.fenix/runs/`（Agent 运行产物，加入模板 gitignore）。
- **配置**：新增用户级 `~/.config/fenixd/dashboard.yaml`；`config.template.yaml` 增加可选 dashboard 端口配置。
- **依赖**：Web 服务用 Python 标准库 `http.server`，不引入新 pip 依赖（保持一键安装零额外依赖）；前端用无外部 CDN 的原生 HTML/CSS/JS。
- **兼容性**：不破坏现有 STATE.md 格式与验证产物格式；Agent 最终 result 解析结果与现状等价（`num_turns` / 退出码行为不变）。
