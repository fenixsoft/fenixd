# Design: refactor-core-packages

## Context

core/ 的 pm_engine.py（4879 行）与 agent_runner.py（3068 行）是两个混杂 8 类职责的巨文件，占 core 总量 51.5%。完整问题分析与设计已定稿于 `docs/superpowers/specs/2026-08-31-core-refactor-design.md`（commit 05396da），本文件是其工程化落地。

关键事实：
- 外部 API 面极小：`fenixd.py` 用 `PMEngine`/`AgentRunner`，`core/dashboard/data.py` 用 `clean_old_runs`，27 个测试文件另用 `AgentRunResult`/`AdminDisposition` 及 40+ 私有方法。
- `core/verify_engine/` 已是"包内拆分 + 主类导出"的 repo 内先例。
- 测试基线：912 passed + 1 个环境性失败（`test_v2_dev_server.py::test_seq_offsets_within_range`，daemon V2 服务器占用 19001-19005 端口所致，与代码无关）。
- daemon 正在运行，驱动其他 spec 开发，重构期间不得重启。

## Goals / Non-Goals

**Goals:**
- 两巨文件拆为按职责组织的包，单文件回到 300-800 行量级
- 外部 API 接口零变化；现有测试文件零修改、全量通过（不引入新失败）
- 新功能此后有明确归属边界
- 每阶段独立 commit，可单独回滚

**Non-Goals:**
- 不重排方法体内部逻辑、不优化、不修复发现的 bug（只记录清单）
- 不重写巨方法内部结构（`_execute_agent` 370 行等保持原样整体搬移或留门面）
- 不做测试迁移清理（列为可选第二轮，`engine._xxx` → 组件直调）
- worktree_manager/admin_monitor 不拆包（职责已内聚），仅明显坏味道时轻梳理

## Decisions

### D1: 组合提取 + 门面（而非 Mixin 物理拆分）

评估过三案：A（Mixin 物理拆分）、B（组合提取+门面）、C（先 A 后 B）。选 B：A 只做物理分散，self 状态共享与归属问题依旧；B 给出真实组件边界，组件可独立测试，且与"测试分两步走"决策匹配（第一轮门面委托即保测试零修改）。verify_engine 先例证明 repo 内此模式可行。

### D2: 包结构

```
core/pm_engine/
  __init__.py         # 导出 PMEngine
  engine.py           # PMEngine 门面：组装组件、事件回调编排（_on_spec_*）、handle_event
  dispatch.py         # Dispatcher：队列/优先级/老化/退避/_process_queue/_run_agent_worker
  family.py           # FamilyGovernor：fix 家族治理/sibling repair/爆炸信号/waiver
  budget.py           # ImplBudget：run 预算/豁免/告警/对账
  verification.py     # VerificationPipeline：三阶段+legacy 验证/冻结/合同/verdict/交付物门
  recovery.py         # RecoveryWatch：恢复观察注册/复查/持久化
  reporting.py        # ReportBuilder：项目报告/日报/pushable specs

core/agent_runner/
  __init__.py         # 导出 AgentRunner, AgentRunResult, AdminDisposition, clean_old_runs
  runner.py           # AgentRunner 门面：_execute_agent/_run_claude 留此
  prompt_builder.py   # PromptBuilder：_build_prompt + 各 section（准纯函数）
  provider_circuit.py # ProviderCircuit：熔断/冷却/探针/4xx 记录
  liveness.py         # LivenessSupervisor：存活检测/判活/超时监督/wait_for_running_agents
  token_budget.py     # TokenAccountant：用量累计/预算检查/告警
  v2_server.py        # V2ServerManager：per-run 隔离测试服务器
  session.py          # SessionTracker：resumable session id 提取（体量过小可并入 runner.py）
  run_files.py        # 模块级函数：append_run_line/append_run_error/clean_old_runs
```

### D3: 状态归属与拆分规则（行为等价的关键）

1. **状态同迁**：组件持有自己领域的状态。`provider_circuits` 归 ProviderCircuit；`_run_queue`/`_active_runs`/`_active_priorities`/`_queue_lock` 整体归 Dispatcher——锁与被保护状态必须同迁，禁止两把锁或锁与状态分离。
2. **服务注入**：无状态依赖（config/state_machine/logger/project_root/worktree_manager）构造注入。
3. **回引跨域**：搬移的方法体内，调用留在门面的方法/状态时改写为 `self._pm.xxx`；组件内同迁方法/状态保持 `self.xxx`。只改写调用点，不重排语句、不改条件、不顺手优化。依赖方向只允许"组件 → 门面"单向回引，门面单向持有组件，禁止组件间互相引用。
4. **门面委托**：测试直接引用的 40+ 私有方法在门面保留一行委托，如 `def _process_queue(self): self._dispatcher.process_queue()`。
5. **巨方法不再细分**：类间拆分为限，方法内部结构不动。

### D4: 测试分两步走

本轮拆分测试文件零修改（门面委托保调用路径）；可选第二轮单独 commit 做测试迁移清理。拆分前先补 characterization tests（独立 commit），锁定将被搬移且无覆盖的方法行为。

### D5: 分阶段顺序——agent_runner 先行

| 阶段 | 内容 |
|---|---|
| 0 | coverage 分析 + 补 characterization tests |
| 1 | agent_runner → PromptBuilder（最纯、~730 行，验证拆分模式） |
| 2 | agent_runner → ProviderCircuit + TokenAccountant + V2ServerManager + run_files |
| 3 | agent_runner → LivenessSupervisor + SessionTracker；agent_runner 包成型，旧文件删除 |
| 4 | pm_engine → FamilyGovernor + ImplBudget |
| 5 | pm_engine → VerificationPipeline（~1900 行最大块） |
| 6 | pm_engine → Dispatcher + RecoveryWatch + ReportBuilder；pm_engine 包成型，旧文件删除 |
| 7 | worktree_manager/admin_monitor 轻梳理（仅明显坏味道） |
| 8 | 收尾：全量测试 + import 路径逐一验证 + daemon 重启冒烟（时机经用户确认） |
| 9（可选） | 测试迁移清理（单独 commit，第二轮） |

理由：agent_runner 的组件（PromptBuilder 准纯函数、ProviderCircuit 状态独立）比 pm_engine 的更易提取，先用它验证拆分模式再处理 pm_engine 的验证流水线与派发队列。每阶段 = 独立 commit + 全量 pytest 全绿（基线环境性失败除外），回滚粒度 = 阶段。

### D6: bug 纪律

拆分中发现的 bug/死代码/可疑逻辑只记录清单（自阶段 0 起持续维护，随各阶段追加，阶段结束统一汇报），代码保持行为等价，不顺手修。

## Risks / Trade-offs

- [Dispatcher 线程锁语义破坏] → 锁与状态整体同迁（D3 规则 1）；阶段 6 后跑 test_dispatch_aging/test_repair_redispatch 等并发测试。
- [VerificationPipeline 状态梳理遗漏（冻结轮次、verdict 文件路径等）] → 阶段 0 补 characterization test 先行锁定；阶段 5 后全量验证。
- [_build_prompt 隐式时序依赖（每次调用读 .fenix 文件）] → PromptBuilder 保持读取时机等价：不缓存、不提前读取。
- [组件间循环引用] → 只允许"组件 → 门面"单向回引（D3 规则 3）。
- [门面委托层的维护成本] → 委托为一行方法，清单明确；第二轮测试迁移后可逐步收缩。
- [环境性测试失败干扰判断] → 基线已记录（912+1），验收标准 = 不引入新失败。

## Migration Plan

按 D5 阶段表执行，每阶段 commit 后全量 pytest。旧文件在包成型阶段（3、6）删除，删除前确认 import 兼容（`python -c "from core.pm_engine import PMEngine"` 等逐一验证）。回滚：`git revert` 阶段 commit 即可，无数据迁移。daemon 重启仅在阶段 8 且经用户确认后执行（touch `.fenix/restart_request`）。

## Open Questions

无——设计已经用户逐节确认。
