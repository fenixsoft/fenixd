# Proposal: fix-deferred-findings

## Why

前三条重构 spec（`refactor-agent-runner-module` / `refactor-dashboard-data-module` / `refactor-verification-module`）各自受「拆分零行为变化」约束，留了一份「只记录不修」的疑点清单。清单里既有**真 bug**，也有性能尖峰、代码整洁与架构倒置问题——它们已被前置 spec 显式推迟（"修复一律另立任务/SPEC"），现在是集中清算。

清单中仍未修复的遗留（经逐条回源码核实后的账目）：

- **真 bug**：`core/dashboard/data/timeline.py` 的 `_timeline_sort_key` 在无效时间戳分支执行 `datetime.max.replace(tzinfo=_tz)`，而 `_tz` 是 `timezone` **类**而非实例 → 该分支必抛 `TypeError`（已在当前代码复现）。事件 `time` 缺失/非法时时间轴重建崩溃。
- **性能尖峰**：`serving` 的 `_port_responds` 串行探测 51 个端口（**两处**调用点，每个 timeout=1.0），`legacy_hint` 存在时最坏 2×51s 量级。
- **代码整洁**：verification 子包内 3 处重复 late-import `import re as _re`（两文件顶部已有 `import re`，纯冗余）；`_run_legacy_verification` 与 `_read_verdict` 的共享文件 fallback 路径重复。
- **健壮性（补可观测性）**：`_ensure_serving_worktree` 中 `stop()` 的 except 仅 `pass`；`_record_verdict_adoption` 的 `_judge_token_baseline` JSON 解析失败静默 fallback；`_escalate_env_blocked` 的 evidence 截断无 `...` 标注。
- **架构**：`core/pm_engine/` 有 3 处反向 import `core.dashboard.data`（分层倒置）——其中 **非 `engine.py` 子项**在本变更处理，`engine.py` 那一行因落在在飞重构作业面而转移。

**范围澄清**：`refactor-agent-runner-module` 的疑点清单 6 条**全部标「✓ 已解决」零遗留**，本变更不涉。故实际待清算 = dashboard 4 条 + verification 10 条，其中 3 条建议「记录不修」、3 条因落在在飞重构作业面而**转移**（见 design D3）。

## What Changes

- 逐条修复上述无重叠遗留，**每条显式标注**是「零行为变化」还是「有意修复行为」：
  - 真 bug（timeline 排序键）：有意修复 → 修正 `_tz` 并用 `timezone.utc`；并按 design D2 一并处理 `_parse_iso_ts` 的 naive 结果（补 `tzinfo=utc`，显式标注有意行为变化），同步更新把错误行为锁死的 characterization 测试。
  - 性能（端口串行探测）：并发探测 + 超时收敛，**保持 `pre` 端口集合语义逐元素一致**。
  - 整洁类（重复 import、fallback 路径重复）：零行为变化。
  - 健壮性类（`stop()` except 补日志、JSON fallback 补告警、截断加标注）：有意（微）行为变化，仅增可观测性。
  - 架构倒置（CYC-1）：处理非 `engine.py` 子项；`engine.py` 子项与 pipeline.py 的两条（`_last_freeze_rejected*` 声明、陈旧 docstring）登记为**转移清单**给在飞重构 spec。
- 对确认为「记录不修」的观察项（`_should_overlay` 语义、`shell=True` 注入面、config 缓存键、位移降档公式）MUST 在 design 显式登记并给出理由，MUST NOT 静默丢弃。
- 修复 MUST 逐条独立可验证（每类至少一个测试用例或断言），**MUST NOT** 顺手引入清单之外的改动。
- 补齐缺失的 characterization 测试（对被修复行为先锁定再改）。
- 不使用绝对行号锚定。

## Capabilities

### New Capabilities

- `deferred-findings-fixes`: 前批重构遗留疑点的清算契约——每条疑点的目标状态、行为变化标记（零变化 / 有意修复）、测试要求、以及与在飞重构 spec 的源文件隔离约束。

### Modified Capabilities

（无——本变更不修改任何既有 spec 级行为要求）

## Impact

- **代码**：`core/dashboard/data/timeline.py`、`core/pm_engine/verification/`（serving / escalation / verdict_evidence / legacy / report_gate / infra_classify 子模块）、以及 CYC-1 非重叠子项涉及的中性模块与 `core/dashboard/data/` 门面。**MUST NOT 触及**在飞重构作业面：`core/worktree_manager.py`、`core/pm_engine/dispatch.py`、`core/dashboard/server.py`、`core/pm_engine/engine.py`、`core/pm_engine/verification/pipeline.py`、`core/agent_runner/runner.py`（落在其中的条目已登记为转移清单）。
- **API**：零变化（CYC-1 搬迁经门面 re-export 保持导入路径）。
- **测试**：被修复行为的 characterization 测试须同步更新；全量 `bin/run_full_suite.py` 不引入新失败。
- **并发**：本变更落点文件与 `refactor-giant-classes` / `refactor-long-functions` / `refactor-facade-delegation` 的作业面不相交，可与前两者**并行**。
- **运行时**：修复 timeline 排序键会改变无效时间戳事件的重建行为（从崩溃变为排到末尾）——属有意修复。
