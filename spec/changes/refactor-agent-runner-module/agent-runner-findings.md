# 疑点清单：refactor-agent-runner-module

本文件登记拆分重构过程中**发现但不修复**的疑点（tasks 1.3 / 1.5 基线，
proposal「不顺手修 bug（只记疑点清单）」；spec「拆分零行为变化」）。
记录格式：`[<日期>] <模块>:<符号> — <疑点描述>（<影响评估>）`。

## 已登记疑点

- [2026-09-16] `core/agent_runner/runner.py`:`_run_claude` — `from core.config
  import ConfigLoader` 位于函数签名与 docstring 之间，`ast.get_docstring()` 返回
  None（docstring 非函数体首语句）。**本变更 task 5.1 已修复**：import 移至首段
  逻辑之后，`ast.get_docstring()` 返回非 None（阶段 4 契约测试锁定）。✓ 已解决

- [2026-09-16] `core/agent_runner/runner.py`:44-50 — liveness 导入出现两次
  （`from core.agent_runner.liveness import (...) LivenessSupervisor` 与
  `from core.agent_runner.liveness import LivenessSupervisor`），重复导入同一
  `LivenessSupervisor`。**阶段 4（5.2）已清理**：删除重复行，保留单次导入。✓ 已解决

- [2026-09-16] `tests/helpers.py` 等 11 个测试文件的 `make_runner` 赋值点 —
  `runner._daily_reset_date = None` 等 4 行经**转发 setter** 写组合对象。setter
  删除（阶段 3）后这些赋值点若不变更会抛 `AttributeError: property ... has no
  setter`。影响：任务书已显式登记（design D5 / tasks 4.2），**阶段 3 已按计划
  改写**为 `runner._provider_circuit.<名> = ...`。✓ 已解决

- [2026-09-16] `core/agent_runner/runner.py`:`_check_daily_limit` — 生产内部写点
  `self._daily_reset_date = today` 经转发 setter 写组合对象；setter 删除后
  主链路（`run_implementer` 派发路径）抛 `AttributeError`。**阶段 3（tasks 4.1）
  已按计划改为** `self._provider_circuit._daily_reset_date = today`，契约测试
  覆盖跨日重置分支。✓ 已解决

- [2026-09-16] `core/agent_runner/runner.py`:`_default_ts_parser` — 模块级
  函数体为 `return AgentRunner._parse_event_timestamp(entry)`——非纯函数而是
  类方法委托桩。若原样迁入 `latency.py` 会构成新模块对 `runner` 的回引（循环
  import / D4「MUST NOT 回引 runner」冲突）。影响：设计文档 D4 给出处理裁决
  （latency.py 自带等价实现 + runner 保留一行委托 + 契约测试锁定行为一致），
  **阶段 1 已按裁决执行**，`latency._default_ts_parser` 与
  `AgentRunner._parse_event_timestamp` 对同一样本逐字段一致。✓ 已解决

- [2026-09-16] `core/agent_runner/runner.py`:270 — `admin_disposition_path`
  是模块级函数（接收 `project_root` / `run_id`），但 `run_administrator` / 其它
  调用点未发现 runner 之外的 consumer 打 patch——随迁 `maintenance_runs.py`
  无补丁缝隙风险（与 D2 结论一致）。影响：无。**阶段 2 已随迁并 re-export**，
  `tests/test_admin.py:21` / `test_admin_disposition_failure_context.py:11`
  导入路径不变。✓ 已解决

## 最终汇报（tasks 6.1）

拆分重构全过程记录的疑点**全部按任务书计划处置完毕**（无一遗留未决）：
- 5.1 docstring 位置（task 显式修复项）→ 已修复；
- 重复 import / 转发 setter 赋值点 / `_check_daily_limit` 写点 / `_default_ts_parser`
  回引 / `admin_disposition_path` 随迁 → 均为任务书显式登记的处理项，已按 design
  裁决执行；未发现任务书之外的新疑点（拆分全程未顺手修 bug，行为零变化由
  `run_full_suite --baseline 02e950d7` → 存量 佐证）。

## 排除项（核实后不成立）

- 结果类（`AgentRunResult` 等 6 个类）模块级依赖集合为空 — 可以整类迁移
  （design D2 实测结论，已采纳）。
- `_entry_is_tool_result` 三处消费点（`latency_samples_from_events` /
  `_run_claude` 内联采样 / `_turn_traffic_active`）复用 `AgentRunner.
  _entry_is_tool_result` 静态委托入口，单一真源不破（tool-result-stream-detection
  design D1）。`runner.py` 的类静态入口保留为一行委托到 `latency` 模块函数。

## 使用说明

- 只记录、不修复；修复一律另立任务/SPEC。
- 本清单随重构推进持续更新：新增疑点追加，任务书显式修复项在完成时标注。
- 阶段 5（tasks 6.1）向用户汇报疑点清单最终态。