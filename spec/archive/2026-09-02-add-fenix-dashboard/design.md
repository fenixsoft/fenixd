## Context

Fenixd 已有一个**单项目终端 TUI**（`bin/fenix_dashboard.py`），通过轮询 `STATE.md`、`spec/changes/<spec>/tasks.md`、`.fenix/verify-progress/*.json`、`.fenix/logs/fenixd*.log` 展示 SPEC 状态、任务进度与最近事件。痛点：

1. **过程不可见**：`core/agent_runner.py` 的 `_run_claude` 用 `subprocess.run(capture_output=True)` **阻塞**等待 Agent 结束，运行期间没有任何输出落盘，只有结束后的 stdout（且仅把末 500 字摘要写进日志）。一个跑了很久的测试，用户只能看到「正在 running」事件，看不到内部在干什么。
2. **细节分散**：bug 内容（`verification-report.md`）、失败截图（`.fenix/verify-progress/<spec>/screenshots/*.png`）、逐场景断言（`.fenix/verify-progress/<spec>/report.json`）散落多处，无统一视图。
3. **单项目**：无法同时监控多个 Fenixd 项目。

目标能力（来自 proposal）：`agent-run-artifacts`、`dashboard-server`、`dashboard-ui`、`fenix-dashboard-skill`。

## Goals / Non-Goals

**Goals:**
- 独立进程的 Web Dashboard，仅监听 localhost，秒级刷新（2s 轮询）。
- 跨项目监控：中心配置（`~/.config/fenixd/dashboard.yaml`）+ 目录扫描自动发现。
- 展示 Agent **运行过程**（LLM 对话、工具调用、心跳），解决「长跑无结果不知在干什么」。
- 每个 SPEC 可下钻到完整细节：任务、验证进度、bug 列表、失败截图、逐场景断言、运行记录与 LLM 对话。
- 一键安装（install.sh 自动接入）+ `/fenix-dashboard` skill 输出可访问 URL。
- 保持现有 TUI、验证产物格式、Agent 最终 result 解析**完全兼容**。

**Non-Goals:**
- 不修改 fenixd 核心调度逻辑（PMEngine / EventBus / StateMachine 语义）。
- 不做实时推送（WebSocket/SSE）：文件轮询 2s 延迟已满足秒级要求；`runs/*.jsonl` 追加写本身可被轮询读取，近似实时。
- 不做远程/鉴权访问：仅 localhost。
- 不引入新 pip 依赖、不引入 CDN 前端框架（离线可用）。
- 不做 Agent 输出的**重放控制**（暂停/停止运行中的 Agent）——只读展示。

## Decisions

### D1. Agent 运行过程通过改造 `_run_claude` 流式落盘（`agent-run-artifacts`）

**决策**：`_run_claude` 从 `subprocess.run(capture_output=True)` 改为 `subprocess.Popen` + 逐行读取，给 claude 命令加 `--output-format stream-json`，把每一行事件原样追加写入 `.fenix/runs/<run_id>.jsonl`；结束时从最后一个 `result` 事件取回与现状等价的输出（含 `num_turns`），保证调用方（`AgentRunResult`、verifier 读 `.fenix-run-result.json`）行为不变。

**理由**：已确认 `claude -p --output-format stream-json` 会逐行输出结构化事件（`system` / `assistant` / `user` / `tool_use` / `tool_result` / `result`），这正是「运行中 Agent 在干什么、说了什么」的实时数据源。相比读 `~/.claude/projects/*.jsonl` 会话转录，本方案自包含于项目 `.fenix/runs/`、不依赖 Claude Code 内部布局、天然支持多项目。

**备选**：
- 读 `~/.claude/projects/<slug>/*.jsonl` 转录——零侵入，但需额外维护「run→session」映射、跨项目路径脆弱，弃用。
- 保持 `--output-format json` 只做原始输出流落盘——长跑期间无实时内容，无法满足需求，弃用。

**细节**：
- 用两条守护线程分别读 stdout / stderr（`readline` 阻塞），主线程 `join(timeout)` 处理超时与 kill，避免单线程 readline 卡死。
- 非 JSON 行（如 stderr 噪声）以 `{"type":"stderr","line":...}` 形式兜底写入，保证文件始终可解析。
- 异常/超时终止时，向 jsonl 追加 `{"type":"error","error":...}` 终态行，Dashboard 据此显示「异常终止」；半文件仍可读，便于诊断挂起 Agent。
- `.fenix/runs/` 仅保留最近 N（默认 20）个运行的产物，启动/轮询时清理旧文件，并加入模板 gitignore。

### D2. Dashboard 服务器用 Python 标准库 `http.server`，零新依赖

**决策**：`core/dashboard/server.py` 基于 `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`，提供 REST JSON API 与静态资源服务；前端为无构建、无 CDN 的原生 HTML/CSS/JS。

**理由**：一键安装要保持零额外 pip 依赖（现有依赖仅 PyYAML）。本地 localhost 场景并发量低，stdlib 足够。

**备选**：Flask/FastAPI——引入依赖、违背零额外安装约束；前端 React/Vue——需构建链或 CDN，弃用。

### D3. 多项目发现 = 显式配置 + 目录扫描（`dashboard-server`）

**决策**：`~/.config/fenixd/dashboard.yaml`：
```yaml
port: 8787
projects:
  - name: <别名>
    path: /abs/path
scan_dirs:
  - /parent/dir
```
`registry.discover()` 合并两者：`scan_dirs` 递归浅扫，仅当目录同时存在 `STATE.md` 且 `.fenix/config.yaml` 才识别为 Fenixd 项目。`--add-project <path>` 把项目写入配置（去重），供 skill 调用。

**理由**：配置显式、可控；扫描兜底发现新项目。两者结合覆盖「手头项目 + 历史项目」两种使用方式。

### D4. 数据读取层与现有解析逻辑复用

**决策**：`core/dashboard/data.py` 聚合各数据源；把现有 `bin/fenix_dashboard.py` 中已验证的 `parse_state` / `parse_tasks` / `count_scenarios` / `get_recent_events` 解析逻辑提取为共享函数（放在 `core/dashboard/data.py`），TUI 与 Web 共用，避免两套解析漂移。`bin/fenix_dashboard.py` 改为统一入口：`--serve`（默认 Web）/ `--tui` / `--add-project` / `--port` / `--list-projects`。

### D5. 截图安全静态服务

**决策**：`GET /screenshots/<project>/<spec>/<file>` 由 server 将 URL 参数映射到 `项目/.fenix/verify-progress/<spec>/screenshots/`，用 `Path.resolve()` + `is_relative_to` 校验防路径穿越；`project` 必须存在于注册列表。

### D6. `/fenix-dashboard` skill 与安装集成

**决策**：新增 `skills/fenix-dashboard/SKILL.md`。流程：①探测 Dashboard 是否已运行（tmux session `fenix-dashboard` 或探测端口）→ ②未运行则在 tmux 中启动 `python3 <FENIX_DIR>/bin/fenix_dashboard.py --serve` → ③执行 `bin/fenix_dashboard.py --add-project <当前项目>` 注册 → ④输出 `http://localhost:<port>`。install.sh 已按 `skills/*/` 通配软链，新 skill 零额外改动自动接入。

### D7. 端口冲突处理

**决策**：默认 8787；启动时若端口被占用，自动向上探测空闲端口并输出实际 URL，同时提示可用 `--port` 固定。

## Risks / Trade-offs

- **[stream-json 破坏现有 result 解析]** → 从最终 `result` 事件还原与现状等价输出；`tests/test_core.py` 增加针对 `_run_claude` 解析的兼容性测试；先落地 `agent-run-artifacts` 并跑通既有验证流程再推进 Dashboard。
- **[Popen 流式读取引入超时/僵尸风险]** → stdout/stderr 双线程读取 + `join(timeout)` + 超时 kill；超时/异常写终态行并释放 Popen。
- **[runs 目录膨胀]** → 保留最近 N 个、启动清理、模板 gitignore 排除。
- **[扫描误检]** → 需 `STATE.md` 与 `.fenix/config.yaml` 同时存在；显式配置优先级高于扫描。
- **[截图路径穿越]** → `resolve()` + `is_relative_to` 双重校验，且仅允许注册项目路径。
- **[TUI 回归]** → 保留 `--tui` 分支与原渲染逻辑，`--serve` 为新增默认。

## Migration Plan

1. **阶段 A（agent-run-artifacts）**：改造 `_run_claude` 流式落盘 + 兼容性测试 + `.fenix/runs/` gitignore 与清理。
2. **阶段 B（dashboard-server）**：`registry.py` + `data.py` + `server.py` + CLI 入口改造。
3. **阶段 C（dashboard-ui）**：前端三页（概览 / SPEC 详情 / 运行日志），接入 API。
4. **阶段 D（fenix-dashboard-skill）**：新 skill + 安装/文档，端到端验证。

**回滚**：`agent_runner.py` 改动可独立 revert；Web 为新增模块，删除即回退；TUI 始终可用。

## Open Questions

- `.fenix/runs/` 保留数量是否需要可配置（先固定 20，后续可加配置项）。
- 是否在事件日志中额外增加「Agent 心跳」事件（当前 jsonl 已含逐条事件，先不加，避免日志噪声）。
