# agent-runner-modules

## ADDED Requirements

### Requirement: agent 执行器按职责分模块

`core/agent_runner/runner.py` MUST 把以下三类**可独立提取**的职责移出到新模块：

- `result_gate.py`：四个结果类（`AgentRunResult` / `AdminDisposition` / `SelfReviewResult` / `EvolutionResult`）与门面异常类，以及产物门族（`_check_artifact_json_file` / `_check_agent_result_artifact` / `_check_impl_result_artifact` / `_check_success_completion` / `_check_partial_consistency` / `_check_taskupdate_crosscheck` / `_format_gap_list` / `_invalid_completed_ids` / `_read_init_tools` / `_append_crosscheck_skipped`）；
- `maintenance_runs.py`：`run_administrator` / `run_self_review` / `run_evolution` 及其配套（`_clear/_delete/_read_admin_disposition`、`_clear/_delete/_read_self_review_out`、`_accumulate_self_review_tokens`、`_delete_evolution_out`、`_accumulate_evolution_tokens`、`_get_admin_model`）；
- `latency.py`：模块级延迟统计纯函数（`iter_events` / `_entry_is_tool_result` / `latency_samples_from_events` / `latency_stats` / `_percentile` / `format_latency_summary`）与常量 `LATENCY_STALL_SECONDS`；时间戳缺省解析器 `_default_ts_parser` 的实现 MUST 定义在 `latency.py` 内（MUST NOT 回引 `runner`），`runner.py` 保留同名模块级函数并一行委托。

被提取代码依赖的模块级常量/辅助名（`_ARTIFACT_FRESHNESS_GRACE_SECONDS` / `_PLANREADY_STATUSES` / `DEFAULT_GATEWAY_MODEL` / `admin_disposition_path`）MUST 随其消费者迁入对应新模块，并由 `runner.py` re-export；新模块 MUST NOT 在模块级 `import runner`。`runner.py` 内部对提取方法的调用 MUST 继续以 `self.<方法名>` 形式进行（MUST NOT 直呼新模块函数），以保证实例属性打桩仍然生效。

#### Scenario: 结果类与产物门独立成模块

- **WHEN** 检查 `core/agent_runner/result_gate.py`
- **THEN** 其内容为结果数据结构与产物门校验逻辑，不含 AgentRunner 的 run 编排或子进程调用

#### Scenario: 延迟统计独立成模块且无循环 import

- **WHEN** 检查 `core/agent_runner/latency.py`
- **THEN** 其中 `latency_stats` 读取的 `LATENCY_STALL_SECONDS` 与缺省时间戳解析器 `_default_ts_parser` 的实现均定义在本模块内（MUST NOT 回引 `runner`）

#### Scenario: 常量随消费者同迁且经 runner 可访问

- **WHEN** 分别执行 `from core.agent_runner.runner import DEFAULT_GATEWAY_MODEL, admin_disposition_path, _PLANREADY_STATUSES` 与 `import core.agent_runner.result_gate`
- **THEN** 导入均成功、与各自新模块中的对象同一，且单独导入新模块不触发循环 import

#### Scenario: runner 显著收敛

- **WHEN** 重构完成
- **THEN** `core/agent_runner/runner.py` 行数 MUST ≤ 3800（相对重构前 5087 行至少下降 1200 行）

> 阈值说明：`_execute_agent_inner`（907 行）、`_run_claude` 及其同域辅助（517 行）、主链路方法（约 1100 行）、provider/v2/liveness 委托区（约 450 行）按本 spec 的 Non-Goals / 决策 MUST 保留原处，本变更可提取量约 1300 行；故阈值取可达上界 3800，MUST NOT 设为 1500（算术上不可达）。

### Requirement: `_run_claude` 保留在 runner.py 且 docstring 有效

`_run_claude` 及其同域辅助（`_denoise_stderr` / `_parse_transient_backoff_schedule` / `_parse_event_timestamp`）MUST 保留在 `runner.py`，MUST NOT 迁移至其它模块；其函数体 MUST 保持以模块限定名调用 `subprocess`。同时 `_run_claude` 的 docstring MUST 成为函数体的首个语句，使 `ast.get_docstring()` 能取回其设计说明。

#### Scenario: 补丁缝隙不被破坏

- **WHEN** 以 `monkeypatch.setattr(core.agent_runner.runner, "subprocess", 替身)` 后调用 `runner._run_claude(...)`
- **THEN** 函数体使用该替身（MUST NOT 真 spawn 子进程）

#### Scenario: docstring 可被解析

- **WHEN** 对 `runner._run_claude` 调用 `ast.get_docstring()`
- **THEN** 返回非 None 的说明文本

### Requirement: 导入路径与调用路径零改动

`from core.agent_runner.runner import AgentRunner, AgentRunResult` 等既有 import MUST 保持可用；下游直接 import 结果类的模块（`core/pm_engine/spec_review.py`、`core/pm_engine/verification.py`）MUST NOT 需要修改。提取出的方法 MUST 保持可从 `AgentRunner` 实例以同名访问，且**调用签名（含关键字参数 `spec_name` / `agent_type` / `max_turns`）保持不变**。

#### Scenario: 结果类 import 可用

- **WHEN** 执行 `from core.agent_runner.runner import AgentRunResult`
- **THEN** 导入成功，且与 `from core.agent_runner.result_gate import AgentRunResult` 是同一对象

#### Scenario: 委托方法仍可访问

- **WHEN** 构造 `AgentRunner` 实例并访问 `run_self_review` / `_check_success_completion`
- **THEN** 均返回可调用对象，调用行为与拆分前一致

#### Scenario: 实例属性打桩不被绕过

- **WHEN** 以 `runner._check_agent_result_artifact = 替身` 替换实例属性后触发 runner 内部调用该门的路径（如 `_execute_agent_inner`）
- **THEN** 实际使用的是替身——`runner.py` 内部调用点 MUST 保持 `self.<方法名>` 形式，MUST NOT 直呼新模块函数

#### Scenario: 全量测试不引入新失败

- **WHEN** 重构完成后运行 `bin/run_full_suite.py`
- **THEN** 失败集合相对基线不新增失败

### Requirement: 模块级可补丁名字保持

重构后下列名字 MUST 仍可从 `core.agent_runner.runner` 访问，且被同一路径 patch 命中：`subprocess`、`commit_wip_checkpoint`、`LATENCY_STALL_SECONDS`、`_PLANNER_SEMAPHORE`、`_PLANNER_SEMAPHORE_LIMIT`、`AgentRunResult`、`AgentArtifactGateError`、`RunCancelledError`、`AdminDisposition`、`SelfReviewResult`、`EvolutionResult`。

#### Scenario: name patch 生效

- **WHEN** 以 `monkeypatch.setattr(runner_mod, "commit_wip_checkpoint", 替身)` 后触发调用该名字的路径
- **THEN** 实际使用的是替身（patch 非空转）

#### Scenario: 常量导入可用

- **WHEN** 执行 `from core.agent_runner.runner import LATENCY_STALL_SECONDS, _PLANNER_SEMAPHORE`
- **THEN** 导入成功

### Requirement: 测试缝转发属性收敛

`provider_circuits` / `_daily_provider_attempts` / `_daily_provider_warned` / `_daily_reset_date` / `_v2_servers` / `_v2_used_ports` / `_v2_run_seq` / `_extension_baselines` 的 **setter 与 deleter MUST 被删除**；getter MUST 保留且保持「组合对象缺失时惰性创建」语义。直接给这些属性赋值的测试 MUST 改为替换组合对象（如 `runner._provider_circuit.<名> = ...`），且这些测试文件 MUST 已列入 Deliverables 的 `modify` 集。

#### Scenario: setter/deleter 已删除

- **WHEN** 检查重构后的 `runner.py`
- **THEN** 上述 8 个名字下不再存在 setter/deleter 定义

#### Scenario: 绕过 `__init__` 的实例仍可用

- **WHEN** 以 `AgentRunner.__new__(AgentRunner)` 构造实例（未跑 `__init__`）后读写上述任一属性
- **THEN** getter 惰性创建组合对象，读写均成功

#### Scenario: 测试改点已登记

- **WHEN** 审阅 tasks.md 的 Deliverables
- **THEN** 11 个因该收敛而必须修改的测试文件均以 `kind: modify` 登记

#### Scenario: setter 删除后生产内部写点仍成立

- **WHEN** 删除 `_daily_reset_date` 的 setter 后触发 `_check_daily_limit`（跨日重置分支）
- **THEN** 该路径 MUST NOT 抛 `AttributeError`——`runner.py` 内的写点 MUST 已改为直接写组合对象（`self._provider_circuit._daily_reset_date`），且 `AgentRunner` MUST NOT 另行持有该状态的第二份

### Requirement: 有状态组件状态与锁同迁

结果类与产物门提取时 MUST NOT 引入新的状态共享；provider 熔断、V2 服务器、活性监督三组的状态归属 MUST 保持单一（仅存在于其组合对象），`AgentRunner` MUST NOT 另行持有第二份。

#### Scenario: 并发测试通过

- **WHEN** 运行 `tests/test_daemon_lifecycle_races.py`、`tests/test_provider_circuit.py`、`tests/test_provider_failover.py`
- **THEN** 全部通过，无因状态处理引入的竞态回归

### Requirement: 拆分零行为变化且不使用绝对行号锚定

重构 MUST 为纯结构性搬移，MUST NOT 改变 run 行为、超时语义或 provider 选择逻辑；MUST NOT 在本变更内拆分 `_execute_agent_inner`。搬移中发现的缺陷只记入疑点清单。任务与交付物 MUST 以方法名/模块名锚定，MUST NOT 使用绝对行号。

#### Scenario: 行为不变

- **WHEN** 对比重构前后同一构造参数下的 `AgentRunResult.to_dict()` 输出
- **THEN** 逐字段一致

#### Scenario: 大函数未被拆分

- **WHEN** 审阅 `_execute_agent_inner` 的迁移
- **THEN** 该函数仍整体存在于原地，内部逻辑未重组
