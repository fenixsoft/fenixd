# Design: refactor-long-functions

## Context

前两条重构（`refactor-agent-runner-module` / `refactor-verification-module`）把 `runner.py`（5087 行）与 `verification.py`（6304 行）拆为子包，但两份 spec 都把最大的两个函数列为 **Non-Goal** 原样保留：

- `core/pm_engine/verification/pipeline.py` 的 `VerificationPipeline._run_three_stage_verification`（L563–1811，**1249 行**）——占该文件三分之二。
- `core/agent_runner/runner.py` 的 `AgentRunner._execute_agent_inner`（L1593–2499，**907 行**）。

两者均为 core 关键链路主流程。实测结构：

- pipeline 侧：**L678–1149 是一个 472 行的 `while True:` 重排循环**（阶段1 出题 + 阶段2 执行交替），循环后是线性门禁链。函数体局部赋值名去重后 57 个，最大结构嵌套 4 层，41 处 return、3 处 raise（均刻意触发外层 legacy 降级）、10 处 try。
- runner 侧：**L1630–2458 是 `for attempt in range(...)` 大循环**，内嵌 L1895–2313 的 `while True` 原地重试子循环（419 行）。局部赋值名 65 个，最大嵌套 **8 层**，14 处 return。没有单一「主返回载体」，而是十几个标量的隐式元组（`wt_path` 读 53 次、`provider_name` 读 39 次、`model` 读 20 次）。

两函数均无对外 API（类私有方法），唯一生产调用点是门面委托与自身递归。

## Goals / Non-Goals

**Goals:**

- 把两个函数的**线性段落**提取为私有方法，主函数收敛为编排骨架，使单函数长度较原长度**下降至少三分之一**（pipeline 约 1249 → ≤ 830 行；runner 约 907 → ≤ 600 行；D2 保留的循环体计入该长度）、新提取方法不超过 300 行。
- 保持可观测行为、控制流语义、异常传播路径**逐条等价**（等价搬移）。
- 用 characterization tests 锁定两个函数可观测行为，作为等价性证据。
- 显式改写挡路的两条既有契约测试断言（见 D5）。

**Non-Goals:**

- **不拆分 while 循环体的控制流重组**：`_run_three_stage_verification` 的 472 行 `while True` 与 `_execute_agent_inner` 的 419 行内层 `while True` 含密集 `continue`/`break`，跨方法提取须把控制流转成决策返回值——**风险高，本变更不强行拆循环体**，只拆循环体内可无副作用提取的独立段落（见 D2）。
- 不修改任何验证语义、派发语义、门禁阈值。
- 不顺手修 bug（只记疑点清单）。
- 不调整同一文件内其它方法。

## Decisions

### D1：分块契约以「无副作用段落优先」为序

按风险从低到高推进，先摘线性、低耦合、自成一体的段落（收益即 600+ 行），循环体留到最后且只做安全的部分提取。分组即交付契约，逐块落位见下表。

**`_run_three_stage_verification` 分块表（10 块，全覆盖）：**

| 块 | 符号锚点 | 内容 | 提取目标方法 | 可无副作用提取 |
|---|---|---|---|---|
| B0 | 函数头→入口守卫 | 入口状态判据（非 testing 即 return）+ `importlib.reload` 10 个 verify_engine 模块（`_verify_modules` 列表实测 10 项） | `_check_entry_status` / `_reload_verify_engine_modules` | **是** |
| B1 | 循环变量初始化 | 初始化 `replan_left` 等 7 个循环变量 + 冻结损坏升级 | `_load_frozen_or_escalate` | 是 |
| B2 | `while` 循环：出题侧 | 冻结复用分支 / planner plan 循环 / 契约静态检查 / 场景冻结 / 交互契约退回 | `_plan_scenarios_loop` | **否**（3 continue + 1 break + 10 return，留循环体内） |
| B3 | `while` 循环：阶段2 执行 | 契约轻量自证 / `load_scenarios` / 可达性自愈 / `asyncio.run(engine.run())` / env_error 重排 | `_execute_stage2` | 部分（引擎执行段可提，env_error 回写段留循环体） |
| B4 | 阶段2 门禁 | 汇总日志 / 不可达门禁 / 失联门禁 / 同因哨 / 全绿快道 | `_run_stage2_gates` | 是 |
| B5 | judge 派发与失败 | `_judge_dispatch_gate` / judge 失败三让位分支 / D6 二次状态核对 | `_dispatch_judge_or_reuse` | 是 |
| B6 | 裁决证据分类校验 | `_verify_verdict_evidence` 不 ok 时 7 个 cause 分支 | `_handle_verdict_evidence_rejection` | **是**（可每 cause 一方法） |
| B7 | verdict 读取 fail-closed | warning streak 升级 / `_read_verdict` / 状态核对 / 不可读重派→blocked | `_read_verdict_failclosed` | 是 |
| B8 | scenario-repaired 重入 | 修复预算 / 冻结记账 / 空集拒绝 / 递归调用 | `_handle_scenario_repaired` | 是（尾递归保持原样） |
| B9 | bug-found 应用 | 5 道门禁 → transition → spawn 抑制守卫 → infra 归因 → `on_spec_bug_found` | `_apply_bug_found` | 是（纯编排，门禁已是现成方法） |
| B10 | verified 应用 | 进度核对 / 报告闸门 / 洗白门 → transition（7 计数器归零）→ 采纳落盘 → `on_spec_verified` | `_apply_verified` | 是（纯编排） |

**`_execute_agent_inner` 分块表（10 块，全覆盖）：**

| 块 | 符号锚点 | 内容 | 提取目标方法 | 可无副作用提取 |
|---|---|---|---|---|
| R0 | 默认参数初始化 | 默认参数 + 14 个跨 attempt 状态变量 | （并入 D3 状态对象） | — |
| R1 | attempt 顶守卫 | frozen 终止 / 取消旗标（worktree 三型处置）/ 日限检查 | `_attempt_top_guards` | 部分（3 写回变量） |
| R2 | 候选链选择 | 模型分配 → 指针推进 → 全链耗尽/4xx 熔断拦截 → 记当日 attempt | `_resolve_provider_candidate` | 是（`chain_cursor` 回传） |
| R3 | worktree 复用/新建 | 路径校验 / create 失败重试让位 / `used_wts` 登记 / dev-server / provider_marker / 路由地图 | `_prepare_worktree` | 部分 |
| R4 | 子循环 try 体（L1904–2000） | `_build_prompt` / env 注入 / `_run_claude` / **结果文件 role/spec 戳拷回** / `_copyback_verify_progress` / 产物硬门 raise | `_copyback_run_result`（**仅结果文件戳拷回子段 L1963–1987**） | **部分**（拷回子段零粘合可提；try 体其余部分与末句 `break`（L2000，成功退出子循环）属跨边界控制流，留循环体内） |
| R5 | except 取消/产物门 | `RunCancelledError` 收口 / `ArtifactGateError` transient 记账 + superseded + WIP + 退避 + 让位 | `_handle_artifact_gate_retry` | 部分 |
| R6 | except 兜底 | shutdown 守卫 / 秒挂记账 / usage 留痕 / 4xx 熔断 / 瞬断分类与原地重试 / switch 冷却 / session 提取 / resume 死会话清理 | `_classify_and_maybe_retry` | **最难**（写点最多，先内提两小步） |
| R7 | 成功终态 | 半开探针闭合 / wt_dirty 取证 / 终态零提交门 / worktree 分型 / token 入账 | `_finalize_success` | 部分 |
| R8 | 失败终态 | 重试等待 vs 终态 keep 分型 | `_finalize_failure_keep` | 部分 |
| R9 | 循环后收口 | 全重试耗尽三型返回 + token 入账 | `_exhausted_result` | **是** |

**推荐拆分序**：pipeline 侧先摘 B0/B6/B7/B9/B10（线性、低耦合）；runner 侧先摘 `_copyback_run_result` 与 R9，再 R2/R7/R8，最后攻 R6。

### D2：循环体提取的边界

`_run_three_stage_verification` 的 B2/B3 与 `_execute_agent_inner` 的 R4/R5/R6 **主体留在循环体内**，仅允许提取循环体内**不含 `continue`/`break` 跨越边界**的自洽子段：B3 的引擎执行段（不含 env_error 回写段）、R4 的结果文件戳拷回子段（`_copyback_run_result`，见 D1 表）、R6 的两处瞬断重试小步。跨方法提取会造成控制流语义重组，违反「等价搬移」——本变更不做。

> 实测边界（供实现对齐）：runner 内层 `while True`（L1895–2313）的 try 体末句为 `break`（L2000，成功退出子循环），三个 except 子句各含 `break`/`continue`（L2018 / L2110–2111 / L2138 / L2278 / L2313）——故 R4/R5/R6 **均不可整段提取**；`_copyback_run_result` 只覆盖 L1963–1987 的戳拷回段（无写点、无跨边界控制流、无 return）。

**替代方案（已否决）**：把 `while True` 改成状态机 / 决策返回值驱动。否决理由：472 行 + 419 行循环的重组属高风险语义改写，等价性无法用 characterization 测试充分覆盖，收益（进一步降行数）不足以抵风险。

### D3：`_execute_agent_inner` 引入 attempt 级状态对象

runner 侧没有单一返回载体，直接按块提取会产生 8+ 参数的方法签名。本变更 MUST 引入一个 attempt 级可变状态对象（如 `_AttemptState` dataclass），承载跨块标量：`wt_path` / `provider_name` / `model` / `chain_cursor` / `session_id` / `session_provider` / `transient_retries` / `resume_failures` / `kept_wt_path` / `cancelled_flag` / `cancel_reason` / `shutdown_interrupted` / `usage_info` 等。

**约束**：状态对象的引入 MUST 为纯搬运——原标量的读写点逐一映射为对象字段的同名读写，MUST NOT 改变读写顺序或作用域。这是本变更中风险最高的手法，MUST 有 characterization 测试先锁定行为。

**替代方案（已否决）**：多重返回值 / 把跨块变量提升为实例属性。前者造成元组解包噪音，后者跨 attempt 泄漏状态（原变量是每次 attempt 重初始化的局部量）。

### D4：pipeline 侧函数内 import 禁止上提

`_run_three_stage_verification` 内的局部 import（`asyncio` / `importlib` / `sys` / `VerifyEngine` / `load_scenarios` / `selfcheck_contract_light`）**必须在某个运行时函数体内**执行。测试靠 `patch("core.verify_engine.VerifyEngine")` 生效正因 import 在函数体内于调用时执行——提取方法时 MUST 把这些 import 保留在运行时函数体内，MUST NOT 上提为模块级，否则全部 FakeEngine patch 失效。

### D5：契约测试的处置（实测校正）

经逐条实测，两条契约测试的挡路情况不同，MUST 分别处置——**MUST NOT 为「放行」而改写本不挡路的断言**：

1. `tests/test_verification_modules_contract.py`：**无任何断言挡路**。L48–55 只断言 `hasattr(VerificationPipeline, "_run_three_stage_verification")`，L89–108 只断言 `def _run_three_stage_verification(` 仍在 `pipeline.py` 且未在其它子模块重复承载——函数内部拆为私有方法后三条全部仍成立。仅其模块 docstring 第 4 条「大函数仅搬移…（内部不动）」表述过时，MUST 同步改写为「函数仍在 pipeline.py，主函数收敛为编排骨架」；并 SHOULD 在 `TestThreeStageWholeMove` 中**新增**一条「主函数收敛」断言（**新增**，MUST NOT 替换、删除或削弱既有断言）。
2. `tests/test_agent_runner_modules_contract.py`：真正必须改的是 `test_runner_below_3800`（L170–173）——工作树实测 3803 行已破，MUST 按 D6 修订行数上限。L179–184 的 `inspect.getsource(_execute_agent_inner)` 断言（须含 `self._check_agent_result_artifact(`、不含 `result_gate.`）在 D1 R4 表的**修正后口径**下**不被破坏**：只提戳拷回子段时，产物门调用（L1993）仍留在主函数体内；仅当实现偏离该口径、把产物门一并移出时才 MUST 把该断言改锚到提取出的方法（等价强度），且 MUST NOT 删除。

### D6：runner 侧行数契约与补丁缝隙双重约束

`tests/test_agent_runner_modules_contract.py` 断言 `runner.py ≤ 3800` 行。工作树已 3803（在飞改动已顶破）。本变更新增私有方法会进一步抬高行数——MUST 二选一并在 design 后确认：

- **(a)** 把新提取的方法放入 `runner.py` 内部（必然超行数上限），同步修订行数上限契约；
- **(b)** 把新提取的方法放入同级新模块，但会触发 `subprocess` / `time` / `json` 的模块级名 patch 缝隙失效（见 D7）。

**裁决**：采用 (a)——在同一文件内提取，显式修订行数上限；因为 (b) 会使 `test_turn_limit_lifecycle.py`（`setattr(rmod, "subprocess", ns)`）、`test_impl_wip_checkpoint.py`（`setattr(runner_mod, "commit_wip_checkpoint", _boom)`）等模块属性替换失效，违反「补丁缝隙保持」这一更硬的约束。行数上限契约本身是上一 spec 的产物，本变更有权修订。

### D7：模块级名字与 patch 语义保持（回归硬门）

`subprocess` / `time` / `json` / `datetime` / `commit_wip_checkpoint` 等模块级名 MUST 保持可从 `core.agent_runner.runner` 访问且 patch 语义有效。提取出的新方法 MUST 仍在 `runner.py` 内以模块全局名引用这些名字（D6 裁决 (a)）。pipeline 侧同理保持 `core.pm_engine.verification.subprocess` 等 D9 缝隙。

### D8：不使用绝对行号锚定

任务与交付物 MUST 以方法名 / 段落符号名锚定，MUST NOT 使用绝对行号（沿用 `fix-writepoint-anchor-drift` 修订口径）。本文档中的行号仅为现状描述，不进入 tasks.md。

## Risks / Trade-offs

- **[风险] 循环体提取破坏控制流** → 缓解：D2 明确循环体留原地，只提不含跨边界 continue/break 的段落；等价搬移由 characterization 测试佐证。
- **[风险] `_AttemptState` 引入改变读写时序** → 缓解：D3 要求逐字段映射、不改顺序；先补 characterization 测试锁定行为。
- **[风险] 函数内 import 上提致 FakeEngine patch 失效** → 缓解：D4 显式禁止，契约测试保留 `importlib.reload` reload 断言的运行时语义。
- **[风险] 契约测试断言被削弱以「放行」** → 缓解：D5 实测后收窄为「verification 契约测试只同步 docstring（新增断言而非替换）、runner 契约测试只改行数上限」，不触碰任何不挡路的断言。
- **[风险] 与 `refactor-facade-delegation` 冲突** → 缓解：facade spec `depends_on` 本变更与 `refactor-giant-classes`，本变更收口后其才启动。

## Migration Plan

1. 阶段 0：补 characterization tests（锁定两函数可观测行为）；记录全量基线失败集合；建立疑点清单。
2. 阶段 1：pipeline 侧按 D1 分块表提取线性段落（B0/B6/B7/B9/B10 优先）。
3. 阶段 2：pipeline 侧剩余可提段落（B4/B5/B8；B2/B3 只提安全子段）。
4. 阶段 3：runner 侧引入 `_AttemptState`（D3）并提取 `_copyback_run_result` / R9 / R2 / R7 / R8。
5. 阶段 4：runner 侧 R6 内提小步；按 D5 同步 `test_verification_modules_contract.py` 的过时 docstring 表述（并新增收敛断言）、修订 `runner.py` 行数上限（D6）。
6. 阶段 5：全量回归与基线比对；疑点清单汇报。

回滚：各阶段独立 commit，可逐阶段回退。

## Open Questions

- `_AttemptState` 是否用 `dataclass` 还是轻量 `SimpleNamespace`？（实现阶段决定，倾向 `dataclass` 以便字段可见）
- runner 侧行数上限修订为多少？（实现阶段按实际度量决定，MUST 在 tasks 中登记为显式契约修订项）
