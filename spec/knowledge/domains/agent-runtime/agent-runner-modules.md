<!-- knowledge: capability=agent-runner-modules rev=1 sources=spec/archive/2026-09-21-refactor-agent-runner-module -->

# Agent Runner 模块化结构

`core/agent_runner/` 包的职责切分与兼容契约：模块边界、import 路径、打桩缝与状态归属的现行约束。

## 现行规则

- 四模块职责切分：
  - `runner.py`：run 编排与子进程调用。`_run_claude` 及其同域辅助（`_denoise_stderr` / `_parse_transient_backoff_schedule` / `_parse_event_timestamp`）保留原地，函数体以模块限定名调用 `subprocess`（monkeypatch 替身生效），docstring 为函数体首个语句（`ast.get_docstring()` 可取回）；`_execute_agent_inner` 整体保留原地不拆分；
  - `result_gate.py`：四个结果类（`AgentRunResult` / `AdminDisposition` / `SelfReviewResult` / `EvolutionResult`）、门面异常类与产物门族（`_check_artifact_json_file` / `_check_agent_result_artifact` / `_check_impl_result_artifact` / `_check_success_completion` / `_check_partial_consistency` / `_check_taskupdate_crosscheck` 等），不含 run 编排或子进程调用；
  - `maintenance_runs.py`：`run_administrator` / `run_self_review` / `run_evolution` 及其配套读写与 token 累计辅助；
  - `latency.py`：延迟统计纯函数（`iter_events` / `latency_samples_from_events` / `latency_stats` / `_percentile` / `format_latency_summary`）、常量 `LATENCY_STALL_SECONDS` 与缺省时间戳解析器 `_default_ts_parser` 的实现（不回引 runner）。
- 常量随消费者迁移并 re-export：`_ARTIFACT_FRESHNESS_GRACE_SECONDS` / `_PLANREADY_STATUSES` / `DEFAULT_GATEWAY_MODEL` / `admin_disposition_path` 由 `runner.py` re-export；新模块不在模块级 `import runner`（无循环 import）。
- 调用与 import 零改动：既有 `from core.agent_runner.runner import AgentRunner, AgentRunResult` 等路径保持可用，与从新模块导入的是同一对象；提取方法的调用签名（含 `spec_name` / `agent_type` / `max_turns` 关键字参数）不变；下游（`core/pm_engine/spec_review.py`、`core/pm_engine/verification.py`）无需修改。
- 打桩缝不变式：`runner.py` 内部对提取方法的调用保持 `self.<方法名>` 形式（不直呼新模块函数），实例属性打桩生效；`subprocess`、`commit_wip_checkpoint`、`LATENCY_STALL_SECONDS`、`_PLANNER_SEMAPHORE`（及 `_PLANNER_SEMAPHORE_LIMIT`）、四个结果类与 `AgentArtifactGateError` / `RunCancelledError` 可从 `core.agent_runner.runner` 访问且被同一路径 patch 命中。
- 测试缝收敛：`provider_circuits` / `_daily_provider_attempts` / `_daily_provider_warned` / `_daily_reset_date` / `_v2_servers` / `_v2_used_ports` / `_v2_run_seq` / `_extension_baselines` 八个转发属性删除 setter/deleter，getter 保留「组合对象缺失时惰性创建」语义（`AgentRunner.__new__` 绕过 `__init__` 的实例读写均成功）；测试以替换组合对象的方式赋值（如 `runner._provider_circuit.<名> = ...`），生产内部写点直写组合对象、不持第二份状态。
- 状态单一归属：provider 熔断、V2 服务器、活性监督三组状态仅存在于其组合对象，`AgentRunner` 不另持副本。
- 重构纪律：纯结构搬移、零行为变化（同一构造参数下 `AgentRunResult.to_dict()` 逐字段一致）、不改超时语义与 provider 选择逻辑；搬移中发现的缺陷只记疑点清单；任务与交付物以方法名/模块名锚定，不用绝对行号。

## 溯源

- 2026-09-21 refactor-agent-runner-module（spec/archive/2026-09-21-refactor-agent-runner-module） — 固化 runner/result_gate/maintenance_runs/latency 四模块职责边界、re-export 与打桩兼容契约、测试缝 setter/deleter 收敛、状态单一归属与零行为重构纪律
