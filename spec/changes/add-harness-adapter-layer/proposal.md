## Why

fenixd 当前把 Claude Code 当作唯一 code agent harness（ADR-055：一切 LLM 借道 claude CLI），spawn 命令构造、事件流解析、进程识别、配置注入散落在 8+ 处且彼此复制。要让 DeepSeek Harness（dsh）按「能力等价映射」接入并最终成为主 harness（母设计：`docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md`），必须先把「进程边界协议」收拢为一个可插拔接缝——本 SPEC 是 4 SPEC 依赖链的第一环，交付 harness 抽象层并把 claude 现状平移进去，行为零变化。

## What Changes

- 新增 `core/agent_runner/harness/` 包：`HarnessAdapter` 协议（build_spawn_spec / normalize_event / classify_stderr / extract_result / process_patterns / capabilities）与 `SpawnRequest`/`SpawnSpec`/`HarnessCapabilities` 数据类。
- 新增 `claude_adapter`：`_run_claude`（runner.py:5607）的命令构造、隔离 settings（hooks/skills/plugins symlink/CLAUDE_CONFIG_DIR）、env 路由与清理整体平移，行为字节级不变；`_run_claude` 改名 `_run_agent` 并两段化（build_spawn_spec → 通用 Popen + 归一化事件循环），解除其「有意单体」注记。
- 新增 `run_one_shot(adapter, …)`：收编 5 个一次性 spawn 点（监督 judge、知识蒸馏、知识回填、架构图 autodraft、项目简介），各自 CLI 参数经 claude_adapter 保持不变。
- 告警叙事通道 `default_channel` 实现改走 adapter（经既有 `set_channel` 接缝，ADR-242/243）。
- 进程识别泛化：`proc_utils.py:47`、`event_bus.py:810`、`admin_monitor.py:868`、`bin/fenix_dashboard.py:151-154` 的硬编码 `claude` 进程名改由 `adapter.process_patterns()` 供给。
- 新增全局配置 `agent.harness: claude|dsh`（缺省 claude）：config.py 校验、Dashboard 设置页（SystemPanel + settings_routes）、热重载兼容；`dsh` 值在本 SPEC 阶段被健康检查 fail-fast（adapter 未部署，SPEC-3 交付）。
- 新增 ADR-271「LLM 能力经可插拔 agent harness 接入」取代 ADR-055；记录自由会话（dashboard session_manager）与 `CLAUDE_PID` watchdog 保持 claude 专用的豁免、run jsonl claude stream-json 形状为 canon、worktree 目录约定冻结三项决策。
- **BREAKING：无**（对既有行为零变化是本 SPEC 硬约束）。

## Capabilities

### New Capabilities
- `agent-harness-adapter`: HarnessAdapter 协议、claude 平移等价性、一次性 spawn 收编与进程识别泛化——「换 harness 只换 adapter」的接缝契约。
- `harness-config`: `agent.harness` 全局配置的校验、缺省、Dashboard 设置界面与热重载语义。

### Modified Capabilities

（无——行为零变化约束下无既有能力的需求级变更；agent-llm-isolation / provider-chain-config 等已归档能力实现细节被平移但需求不变。）

## Impact

- 受影响代码：`core/agent_runner/`（runner/maintenance_runs/liveness/prompt_builder 契约段不动）、`core/knowledge.py`、`core/knowledge_backfill.py`、`core/dashboard/routes/`（architecture/project/settings）、`core/dashboard/static/src/pages/settings/components/SystemPanel.tsx`、`core/proc_utils.py`、`core/event_bus.py`、`core/admin_monitor.py`、`bin/fenix_dashboard.py`、`core/config.py`。
- 不受影响（明确冻结）：run jsonl schema（8+ 读侧模块零改动）、Task 工具族成对契约、worktree 目录约定、provider 链配置模型、dashboard 自由会话。
- 后续依赖：SPEC-2（fenix-dsh Bundle）依赖本 SPEC 冻结的 `HarnessCapabilities` 接口；SPEC-3（DshAdapter）依赖本 SPEC 的协议与 `_run_agent` 两段结构。SPEC-3（DshAdapter）是依赖链中首个新采集链路里程碑，其任务与 Deliverables MUST 含可观测性交付项（输入事件 dump、管线逐级计数、坏事件分类统计至少其二，允许 dsh 等价替代形态），与功能交付同批验收。
- 风险：daemon 自举改派发核心——以快照测试（平移前后 argv/env/stdin 逐字节零差异）+ 既有回归网护航。
