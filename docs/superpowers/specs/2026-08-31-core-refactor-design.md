# core/ 目录重构设计 — 组合提取 + 门面

日期：2026-08-31
状态：待用户审阅

## 1. 背景与问题

core/ 经多轮开发累计 18 个文件 15,407 行，其中两个巨文件占 51.5%：

- **pm_engine.py（4879 行，PMEngine ~100 个方法）** 混杂 8 类职责：
  事件回调、派发队列（优先级/老化/退避/并发）、恢复观察（recovery watch）、
  fix 家族治理（family governor）、impl run 预算、验证流水线（三阶段+legacy+
  scenario 冻结+interaction contract+verdict evidence+交付物门，约 1900 行）、
  报告生成、git 操作。
- **agent_runner.py（3068 行，AgentRunner ~80 个方法）** 混杂：
  prompt 构建（~730 行，准纯函数）、provider 熔断/冷却/探针（独立状态
  `provider_circuits`）、agent 子进程执行、存活监督（~500 行）、token 预算、
  V2 隔离测试服务器管理、session 管理、run 文件管理。

单文件巨类导致：新功能无明确归属、代码无法整文件理解、改动牵一发动全身、
AI/人工维护成本持续上升。worktree_manager（1386 行）与 admin_monitor（1003 行）
职责内聚、状态引用频度低，仅需轻梳理。

有利条件：`core/verify_engine/` 已是"包内拆分 + 主类导出"的 repo 内先例；
外部 API 面极小。

## 2. 目标与非目标

**目标**
1. 两个巨文件拆为按职责组织的包，单文件回到 300-800 行量级
2. 新功能此后有明确归属边界
3. 外部 API 接口零变化；现有测试文件零修改、全量通过
4. 每阶段独立 commit，可单独回滚

**非目标**
- 不重排任何方法体内部逻辑、不优化、不修复发现的 bug（只记录）
- 不重写巨方法内部结构（如 `_execute_agent` 370 行保持原样整体搬移或留门面）
- 不做测试迁移清理（列为可选的第二轮，阶段 9）

## 3. 约束（用户确认）

| 约束 | 决定 |
|---|---|
| 测试文件 | 分两步走：本轮拆分测试零修改；之后可选做一轮测试清理（单独 commit） |
| 范围 | 全 core 梳理：两个巨文件拆分，worktree_manager/admin_monitor 轻梳理 |
| bug 纪律 | 拆分中发现的 bug/死代码/可疑逻辑只记录清单，不顺手修 |
| 测试基线 | 912 passed + 1 个环境性失败（`test_v2_dev_server.py::test_seq_offsets_within_range`，daemon V2 服务器占用 19001-19005 端口所致，与代码无关） |
| daemon | 重构期间运行中的 daemon 不受影响（内存中是旧代码）；不 touch restart_request，直到收尾阶段用户确认时机 |

## 4. 方案：组合提取 + 门面（方案 B）

已评估三案：A（Mixin 物理拆分，零风险但不解决归属问题）、B（组合提取+门面）、
C（先 A 后 B 渐进）。选定 **B**：真实组件边界、组件可独立测试、新功能有归属，
且与"测试分两步走"的决策天然匹配（第一轮门面委托即可保测试零修改）。

### 4.1 包结构

**pm_engine.py → core/pm_engine/ 包**
```
core/pm_engine/
  __init__.py       # 导出 PMEngine（保持 from core.pm_engine import PMEngine）
  engine.py         # PMEngine 门面：组装组件、事件回调编排（_on_spec_*）、handle_event
  dispatch.py       # Dispatcher：队列/优先级/老化/退避/_process_queue/_run_agent_worker
  family.py         # FamilyGovernor：fix 家族治理/sibling repair/爆炸信号/waiver
  budget.py         # ImplBudget：run 预算/豁免/告警/对账
  verification.py   # VerificationPipeline：三阶段+legacy 验证/冻结/合同/verdict/交付物门
  recovery.py       # RecoveryWatch：恢复观察注册/复查/持久化
  reporting.py      # ReportBuilder：项目报告/日报/pushable specs
```

**agent_runner.py → core/agent_runner/ 包**
```
core/agent_runner/
  __init__.py       # 导出 AgentRunner, AgentRunResult, AdminDisposition, clean_old_runs
  runner.py         # AgentRunner 门面：_execute_agent/_run_claude 留此
  prompt_builder.py # PromptBuilder：_build_prompt + 各 section（准纯函数）
  provider_circuit.py # ProviderCircuit：熔断/冷却/探针/4xx 记录
  liveness.py       # LivenessSupervisor：存活检测/判活/超时监督/wait_for_running_agents
  token_budget.py   # TokenAccountant：用量累计/预算检查/告警
  v2_server.py      # V2ServerManager：per-run 隔离测试服务器
  session.py        # SessionTracker：resumable session id 提取（若体量过小可并入 runner.py）
  run_files.py      # 模块级函数：append_run_line/append_run_error/clean_old_runs
```

### 4.2 状态归属与拆分规则（行为等价的关键）

1. **状态同迁**：组件持有自己领域的状态。`provider_circuits` 归 ProviderCircuit；
   `_run_queue`/`_active_runs`/`_active_priorities`/`_queue_lock` 整体归 Dispatcher
   —— **锁与被保护状态必须同迁，禁止出现两把锁或锁与状态分离**。
2. **服务注入**：无状态依赖（config/state_machine/logger/project_root/
   worktree_manager）构造注入。
3. **回引跨域**：搬移的方法体内，调用留在门面的方法/状态时改写为
   `self._pm.xxx`；组件内同迁方法/状态保持 `self.xxx`。只改写调用点，
   不重排语句、不改条件、不顺手优化。
4. **门面委托**：测试直接引用的 40+ 私有方法（`engine._do_spec_bug_found`×34、
   `engine._process_queue`×29、`runner._record_provider_4xx`×33、
   `runner._build_prompt`×20 等）在门面保留一行委托，如
   `def _process_queue(self): self._dispatcher.process_queue()`。
5. **巨方法不再细分**：类间拆分为限，方法内部结构不动。

## 5. 分阶段执行计划

每阶段 = 独立 commit + 全量 pytest（允许基线环境性失败）。回滚粒度 = 阶段。

| 阶段 | 内容 | 规模 |
|---|---|---|
| 0 | coverage 分析：对将被搬移的方法识别无覆盖者，补 characterization test（独立 commit） | 小 |
| 1 | agent_runner → PromptBuilder（最纯、验证拆分模式） | 中 |
| 2 | agent_runner → ProviderCircuit + TokenAccountant + V2ServerManager + run_files | 中 |
| 3 | agent_runner → LivenessSupervisor + SessionTracker；agent_runner 包成型，旧文件删除 | 中 |
| 4 | pm_engine → FamilyGovernor + ImplBudget | 中 |
| 5 | pm_engine → VerificationPipeline（~1900 行最大块） | 大 |
| 6 | pm_engine → Dispatcher + RecoveryWatch + ReportBuilder；pm_engine 包成型，旧文件删除 | 大 |
| 7 | worktree_manager/admin_monitor 轻梳理：仅当明显坏味道才动，预期改动极小 | 小 |
| 8 | 收尾：全量测试 + import 路径逐一验证 + daemon 重启冒烟（时机征求用户确认） | 小 |
| 9（可选） | 测试迁移清理（engine._xxx → 组件直调），单独 commit，属第二轮 | 另议 |

## 6. 验证策略

- **每阶段**：全量 pytest 全绿（基线 1 个环境性失败除外）；import 兼容验证
  （`python -c "from core.pm_engine import PMEngine"` 等逐一确认）；
  fenixd.py 与 core/dashboard/data.py 的 import 语句不改。
- **bug/疑点清单**：自阶段 0 起持续维护，发现项随各阶段追加，阶段结束统一汇报，代码不动。
- **daemon 安全**：重构期间不触发重启；阶段 8 重启前征求用户确认。
- **执行方式**：当前会话直接执行（不走 fenix SPEC 派发），每阶段完成后汇报。

## 7. 风险

| 风险 | 缓解 |
|---|---|
| Dispatcher 线程锁语义破坏 | 锁与状态整体同迁（规则 1）；阶段 6 后跑 test_dispatch_aging / test_repair_redispatch 等并发测试 |
| VerificationPipeline 状态梳理遗漏（冻结轮次、verdict 文件路径等） | 阶段 0 补 characterization test 先行锁定；阶段 5 后全量验证 |
| `_build_prompt` 隐式时序依赖（每次调用读 .fenix 文件） | PromptBuilder 保持读取时机等价：不缓存、不提前读取 |
| 组件间循环引用 | 只允许"组件 → 门面"单向回引（`self._pm`）；门面单向持有组件 |
| 环境性测试失败干扰判断 | 基线已记录；验收标准 = 不引入新失败 |
