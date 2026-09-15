# Design: refactor-agent-runner-module

## Context

`core/agent_runner/runner.py` 实测 **5087 行**、`AgentRunner` 单类 **4455 行 / 164 个方法**，另有 4 个结果类与若干模块级纯函数，混合 7 类职责。已有同项目包化先例 `refactor-core-packages`（`core/agent_runner.py` → `core/agent_runner/` 包），本次是把该包里剩下的巨型 `runner.py` 再拆一层。

**不可提取量的实测边界**（决定行数阈值，勿凭估算）：

| 块 | 实测行数 | 本变更是否可提取 |
|---|---|---|
| `AgentRunner._execute_agent_inner` | 907 | 否（只搬移不拆内部） |
| `cancel_run` / `run_dispute_judge` / `run_spec_review` / `_turn_limit_action` / `_wip_checkpoint_*` 等主链路 | ≈1100 | 否 |
| provider/v2/liveness **一行委托 + 转发属性**区 | ≈450 | 否（Requirement 2 要求保留可访问；转发属性见 D5） |
| `_run_claude` 及其同域辅助 | 517 | **否**——见 D1（保留在 runner.py） |
| 四个结果类 + `AgentGate` 异常类 | 169 | 是（未登记跨模块 patch，无缝隙风险） |
| 产物门族 `_check_*` 等 | 418 | 是 |
| 维护型 run（`run_administrator`/`run_self_review`/`run_evolution` 及配套） | 507 | 是 |
| 模块级延迟统计纯函数 | 119 | 是 |
| 转发属性三件套（8 组） | 91 | 是（删 setter/deleter） |

即：**本变更可提取约 1300 行**（较评审前估算的 1800 行更保守，因为 `_run_claude` 按 D1 不再迁移），`runner.py` 收敛目标为 **≤ 3800 行**。

约束：
- **零行为变化**，全量 pytest 不引入新失败；
- **导入路径与调用路径零改动**；例外仅限 D5 列举的测试缝 setter 赋值（11 个文件，已显式登记）；
- 有状态组件「状态与锁同迁」；
- 不得以绝对行号锚定任务/交付（后续 spec 会继续改本文件）。

## Goals / Non-Goals

**Goals**
- `runner.py` 从 5087 行收敛到 **≤ 3800 行**，职责边界清晰。
- 每类可独立职责成模块。
- 删除仅为测试缝存在的 8 组转发属性 setter/deleter。

**Non-Goals**
- 不改任何 run 的行为、超时语义、provider 选择逻辑。
- **不拆分 `_execute_agent_inner`（907 行）**——其内部拆分风险高，另立 spec。
- **不迁移 `_run_claude`**（见 D1）。
- 不消除 `AgentRunner` 与 PMEngine 的跨模块回引（保持现状）。

## Decisions

### D1：`_run_claude` **保留在 runner.py**（不迁移）
`_run_claude` 与 `runner.py` 模块全局 `subprocess` 名强耦合：两个既有测试文件用
`monkeypatch.setattr(rmod, "subprocess", SimpleNamespace(Popen=..., ...))` **整体重绑 runner 模块的 `subprocess` 名**
（`tests/test_fast_track_scale_precheck.py:459-470`、`tests/test_turn_limit_lifecycle.py:182-193,197-217`），
随后直接调 `runner._run_claude(...)`。`_run_claude` 内部以模块限定名调用 `subprocess.Popen` / `subprocess.TimeoutExpired`，
因此函数体一旦落到 `claude_cli.py`，名字解析改用 claude_cli 的全局，runner 侧的重绑对它不可见，补丁失效、
测试会真 spawn `claude` 进程。**`core/agent_runner/__init__.py` 的模块 docstring 明文承诺「`agent_runner_module.subprocess`
这类模块属性补丁缝隙保持可用」，与「测试零改动」同向。**

故本变更**不迁移 `_run_claude`，也不迁移 `_denoise_stderr` / `_parse_transient_backoff_schedule` / `_parse_event_timestamp`**
（三者虽为纯函数，但同为该补丁缝隙的邻近区域，且合计仅约 48 行，迁出收益不抵风险）。
`claude_cli.py` **不在本变更的交付集内**。

**替代方案（已评估并否决）**：(b) 把 2 个测试文件的 `_patch_popen` 目标改指 `claude_cli`——这违背「导入/调用路径零改动」的硬要求，且会削弱既有补丁缝隙承诺；(a) 改造 `_run_claude` 使其经参数接收 subprocess——会改动函数签名，破坏 `_run_claude(spec_name=..., agent_type=...)` 的既有调用点。

### D2：结果数据结构与产物门提取到 `result_gate.py`
`AgentRunResult` / `AdminDisposition` / `SelfReviewResult` / `EvolutionResult` / `AgentArtifactGateError` / `RunCancelledError`
（合计约 169 行），以及 `_check_artifact_json_file` / `_check_agent_result_artifact` / `_check_impl_result_artifact` /
`_check_success_completion` / `_check_partial_consistency` / `_check_taskupdate_crosscheck` / `_format_gap_list` /
`_invalid_completed_ids` / `_read_init_tools` / `_append_crosscheck_skipped`（合计约 418 行），整体提取。保持
`AgentRunResult` 的构造签名与 `to_dict` 输出逐字段不变（外部与测试大量引用；`core/pm_engine/spec_review.py:21`、
`core/pm_engine/verification.py:4238` 直接 `from core.agent_runner.runner import AgentRunResult`，故 `runner.py` MUST 继续 re-export 这些名字）。

> **无补丁缝隙风险**：全仓带字符串路径的 patch 目标只有 `subprocess` 与 `commit_wip_checkpoint`（见 D6），结果类与产物门无 module-level name patch。实测补充：六个结果/异常类的模块级依赖集合为空（`AgentRunResult` / `AdminDisposition` / `SelfReviewResult` / `EvolutionResult` / `AgentArtifactGateError` / `RunCancelledError` 均不引用 `runner.py` 任何模块级名字），该结论成立。

### D2b：提取模块的依赖注入与常量同迁规则（评审补充，强制）

D2 / D3 / D4 只规定「搬哪些代码」，未规定「搬走后如何取得留在 `runner.py` 的依赖」。实测三块提取目标都引用了留在原地的模块级名字，照原样搬移会各自触发循环 import 或 `AttributeError`。统一规则如下：

1. **门面依赖以参数注入**：提取到新模块的函数 MUST 以 `runner`（`AgentRunner` 实例）作为显式参数接收门面依赖（如 `_run_claude` / `_build_prompt` / `_get_config` / `logger` / `project_root` / `_IMPL_RESULT_STATUSES`），MUST NOT 在模块级回引 `runner`。`AgentRunner` MUST 保留同名方法并一行委托，**签名（含 `spec_name` / `agent_type` / `max_turns` 等关键字参数）逐字不变**。
2. **内部调用点不得绕过委托**：`runner.py` 内部对提取方法的调用 MUST 继续写 `self.<方法名>(...)`（见 `runner.py:2803`、`:4345`、`:4493`、`:4502`、`:4639`），MUST NOT 改为直呼新模块函数。否则实例属性打桩会**静默失效**（补丁空转、真门生效）——`tests/test_worktree_reuse.py:194`、`tests/test_provider_circuit.py:50`、`tests/test_review_circuit_breaker.py:360`、`tests/test_run_lifecycle_hardening.py:742`、`tests/test_provider_failover.py:86` 均以 `runner._check_agent_result_artifact = MagicMock(...)` 在运行期替换该行为。
3. **常量/辅助名随消费者同迁**：被提取代码引用、且同时被 `runner.py` 其它代码引用的模块级名字 MUST 一并迁入对应的新模块并由 `runner.py` re-export（新模块 MUST NOT 回引 `runner`）。实测清单：`_ARTIFACT_FRESHNESS_GRACE_SECONDS`（`runner.py:34`，仅 `_check_artifact_json_file` 消费）与 `_PLANREADY_STATUSES`（`runner.py:41`，仅 `_check_agent_result_artifact` 消费）→ `result_gate.py`；`DEFAULT_GATEWAY_MODEL`（`runner.py:96`，`_get_admin_model` 消费，`runner.py:1022` / `:1107` / `:2746` 亦消费）与 `admin_disposition_path`（`runner.py:270`，`run_administrator` 消费）→ `maintenance_runs.py`。D4 对 `LATENCY_STALL_SECONDS` 的处理是本规则的一个实例，非特例。
4. **re-export 面**：`runner.py` MUST re-export 上述全部名字。既有外部导入点：`tests/test_run_latency_stats.py:22-29`（`LATENCY_STALL_SECONDS` 与四个 latency 函数）、`bin/analyze_run_latency.py:33-35`（`format_latency_summary` / `latency_samples_from_events` / `latency_stats`）、`tests/test_admin.py:21` 与 `tests/test_admin_disposition_failure_context.py:11`（`admin_disposition_path`）。

### D3：维护型 run 提取到 `maintenance_runs.py`
`run_administrator` / `run_self_review` / `run_evolution` 及其配套（`_clear/_delete/_read_admin_disposition`、
`_clear/_delete/_read_self_review_out`、`_accumulate_self_review_tokens`、`_delete_evolution_out`、
`_accumulate_evolution_tokens`、`_get_admin_model`）自成一域，约 507 行。提取后这些方法在 `AgentRunner` 上**保留一行委托**（保持测试路径）。
`_get_admin_model` **并非无 `self` 状态依赖**（实测：调用 `self._get_config("admin.agent_model", None)`，并读取模块级常量 `DEFAULT_GATEWAY_MODEL`——`runner.py:1801-1806`），故按 D2b 规则 1 / 3 处理：以 `runner` 参数接收 `_get_config`，常量随迁 `maintenance_runs.py` 并由 `runner.py` re-export。

### D4：模块级延迟统计纯函数提取到 `latency.py`
`iter_events` / `_entry_is_tool_result` / `latency_samples_from_events` / `latency_stats` /
`_percentile` / `format_latency_summary`（合计约 116 行）为模块级纯函数，整体提取。

> **`_default_ts_parser` 例外（评审补充）**：其函数体是 `return AgentRunner._parse_event_timestamp(entry)`（`runner.py:504-506`）——不是纯函数，而是落在 `_parse_event_timestamp` 上的委托桩。若照原清单迁入 `latency.py`，`latency.py` 必须回引 `AgentRunner`，与本决策「MUST NOT 回引 `runner`」及 D1「`_parse_event_timestamp` 不迁移」**正面冲突**（两条 MUST 不可同时满足）。故：
> - `latency.py` MUST 自带 `_default_ts_parser` 的等价实现（数值 timestamp 直通；ISO 字符串按 `datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()` 解析；缺失/异常返回 `None`——与 `runner.py:3883-3897` 现行为一致），`latency_samples_from_events` 的缺省 `parser` 指向该实现；
> - `runner.py` MUST 保留模块级 `_default_ts_parser`（同名）并一行委托到 `latency` 的实现，`AgentRunner._parse_event_timestamp` MUST 留在原位（`runner.py:2345`、`:3538`、`liveness.py:392` 的调用点不变）；
> - 三者行为 MUST 逐字段一致，由契约测试锁定。
**MUST 一并迁移模块级常量 `LATENCY_STALL_SECONDS`（`runner.py:470`）**，否则 `latency_stats` 会在 `latency.py` 内回引 `runner` 造成循环 import；
`runner.py` MUST re-export `LATENCY_STALL_SECONDS` 以维持 `tests/test_run_latency_stats.py:22-29` 的既有导入路径。

### D5：测试缝转发属性的处置（**11 个测试文件必须改，已显式登记**）
`provider_circuits` / `_daily_provider_attempts` / `_daily_provider_warned` / `_daily_reset_date` /
`_v2_servers` / `_v2_used_ports` / `_v2_run_seq` / `_extension_baselines` 现以 property+setter+deleter 三件套
转发到组合对象（实测 8 组共 91 行）。改法：**删除 setter/deleter**，保留 getter（惰性初始化入口）。

因 `AgentRunner.__new__(AgentRunner)` 绕过 `__init__` 的测试无法依赖 `_provider_circuit` 组合对象已创建，
getter MUST 保持「缺失时惰性创建」语义，使下述赋值后的读取路径仍成立。

**必须改动的 11 个测试文件**（`runner.<转发名> = ...` → `runner._provider_circuit.<名> = ...` 或等价）：

| 文件 | 赋值点 |
|---|---|
| `tests/helpers.py` | 122-125（共享夹具，4 行） |
| `tests/test_agent_runner_gate.py` | 44-47 |
| `tests/test_planready_artifact_gate.py` | 37-40 |
| `tests/test_worktree_reuse.py` | 179-182 |
| `tests/test_verdict_contamination.py` | 452-455 |
| `tests/test_run_lifecycle_hardening.py` | 275（`_daily_reset_date`）、449（`provider_circuits` 真状态注入） |
| `tests/test_transient_backoff.py` | 429-432 |
| `tests/test_provider_failover.py` | 74-77 |
| `tests/test_retry_orphan_active_runs.py` | 37-40 |
| `tests/test_run_cancel.py` | 60-63 |
| `tests/test_verdict_dedup_resynthesis.py` | 515-518 |

这 11 个文件 MUST 在 tasks.md 的 Deliverables 中以 `kind: modify` 显式登记。

**另有 1 处生产代码内部写点 MUST 同步改（评审补充）**：`runner.py:3917`（`_check_daily_limit` 内）执行 `self._daily_reset_date = today`，即**经本次要删除的转发 setter 写入**。setter 删除后该行会抛 `AttributeError: property '_daily_reset_date' ... has no setter`，而 `_check_daily_limit` 位于 `runner.py:2505` 的派发主链路（每日额度重置）。故 MUST 改写为与 getter 读路径一致的形式 `self._provider_circuit._daily_reset_date = today`，并登记为 tasks 4.1 的一部分。全仓实测：8 个转发名中仅此 1 处生产内部写点（其余写点全在测试与组合对象自身）。

### D6：必须保持可 patch 的模块级名字（补丁缝隙清单）
以下名字在拆分后 MUST 仍可从 `core.agent_runner.runner` 访问且被同一路径 patch 命中：

- **`subprocess`**（模块全局）：`tests/test_fast_track_scale_precheck.py`、`tests/test_turn_limit_lifecycle.py`、`tests/test_run_cancel.py` 三处整体重绑；因 D1 不迁移 `_run_claude` 与其同域函数，`runner` 侧的 `subprocess` 名 MUST NOT 被删除或改名（`_execute_agent_inner` 亦使用它）。
- **`commit_wip_checkpoint`**（模块级导入名）：`tests/test_fast_track_scale_precheck.py:380`、`tests/test_impl_wip_checkpoint.py:602-607` 做 name patch；本变更 MUST NOT 迁移它。
- **`LATENCY_STALL_SECONDS`** / **`_PLANNER_SEMAPHORE`** / **`_PLANNER_SEMAPHORE_LIMIT`**：既有测试导入/读写；MUST 经 `runner` 保持可用。
- **`AgentRunResult`** 等结果类：`core/pm_engine/spec_review.py` 与 `verification.py` 直接 import；MUST 经 `runner` re-export。
- **随迁常量/辅助名**（D2b 规则 3/4）：`_ARTIFACT_FRESHNESS_GRACE_SECONDS` / `_PLANREADY_STATUSES` / `DEFAULT_GATEWAY_MODEL` / `admin_disposition_path` 迁出后 MUST 经 `runner` re-export，以维持 `tests/test_admin.py:21`、`tests/test_admin_disposition_failure_context.py:11`（`admin_disposition_path`）、`tests/test_run_latency_stats.py:22-29` 与 `bin/analyze_run_latency.py:33-35`（latency 名）等既有导入路径。

### D7：不使用绝对行号锚点
任务与交付物一律以**函数名 / 模块名 / import 路径**锚定；本 design 中的行号仅为起草时定位参考，MUST NOT 作为验收依据。

## Risks / Trade-offs

- [转发属性删除破坏绕过 `__init__` 的测试] → getter 保持惰性创建；D5 的 11 个文件逐个改点并登记。
- [结果类字段漂移破坏外部契约] → `AgentRunResult` 等做字段级 characterization test。
- [拆 `_execute_agent_inner` 风险高] → 明确 Non-Goal，本变更只搬移不拆内部。
- [行数收敛不达预期] → 阈值按实测可达区间定为 ≤ 3800（可提取量约 1300 行）；MUST NOT 设为 1500（算术不可达）。
- [与其它在飞变更同文件冲突] → 本 SPEC 依赖链在其后（见 proposal Impact）。

## Migration Plan

分阶段（每阶段独立 commit + 全量 pytest）：
1. 阶段 0：characterization tests + 契约清单（含 D6 补丁缝隙清单）+ 疑点清单 + 基线失败集合。
2. 阶段 1：提取 `result_gate.py` + `latency.py`（含 `LATENCY_STALL_SECONDS` 同迁与 re-export）。
3. 阶段 2：提取 `maintenance_runs.py` + 门面一行委托。
4. 阶段 3：删除 8 组转发属性 setter/deleter + 改 D5 的 11 个测试文件。
5. 阶段 4：`runner.py` 收尾核对（行数 ≤ 3800、D6 清单逐条可用）。
6. 阶段 5：全量 pytest + 疑点清单汇报；daemon 重启经用户确认。

**回滚**：每阶段独立 commit。
