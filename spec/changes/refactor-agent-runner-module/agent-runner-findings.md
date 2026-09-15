# 疑点清单：refactor-agent-runner-module

本文件登记拆分重构过程中**发现但不修复**的疑点（tasks 1.3 / 1.5 基线，
proposal「不顺手修 bug（只记疑点清单）」；spec「拆分零行为变化」）。
记录格式：`[<日期>] <模块>:<符号> — <疑点描述>（<影响评估>）`。

## 已登记疑点

- [2026-09-16] `core/agent_runner/runner.py`:`_run_claude` — `from core.config
  import ConfigLoader` 位于函数签名与 docstring 之间，`ast.get_docstring()` 返回
  None（docstring 非函数体首语句）。**本变更 task 5.1 显式修复**（把 import 移至
  首段逻辑之后），此处仅作基线记录，不在拆分层修复。影响：docstring 工具的
  提取/文档生成失效。（待 5.1 修复后从本清单移除或标注已修复）

- [2026-09-16] `core/agent_runner/runner.py`:44-50 — liveness 导入出现两次
  （`from core.agent_runner.liveness import (...) LivenessSupervisor` 与
  `from core.agent_runner.liveness import LivenessSupervisor`），重复导入同一
  `LivenessSupervisor`。影响：纯冗余，无行为影响；5.2 清理残余 import 时可顺带
  归并（属整理，不属行为修复）。

- [2026-09-16] `tests/helpers.py` 等 11 个测试文件的 `make_runner` 赋值点 —
  `runner._daily_reset_date = None` 等 4 行经**转发 setter** 写组合对象。setter
  删除（阶段 3）后这些赋值点若不变更会抛 `AttributeError: property ... has no
  setter`。影响：任务书已显式登记（design D5 / tasks 4.2），非意外缺陷，按计划
  改写，此处仅作基线记录。

- [2026-09-16] `core/agent_runner/runner.py`:`_check_daily_limit` — 生产内部写点
  `self._daily_reset_date = today` 经转发 setter 写组合对象；setter 删除后
  主链路（`run_implementer` 派发路径）抛 `AttributeError`。影响：**任务书显式
  要求改**（tasks 4.1 / design D5 评审补充），非意外缺陷，按计划改为
  `self._provider_circuit._daily_reset_date = today`。

- [2026-09-16] `core/agent_runner/runner.py`:`_default_ts_parser` — 模块级
  函数体为 `return AgentRunner._parse_event_timestamp(entry)`——非纯函数而是
  类方法委托桩。若原样迁入 `latency.py` 会构成新模块对 `runner` 的回引（循环
  import / D4「MUST NOT 回引 runner」冲突）。影响：设计文档 D4 已给出处理裁决
  （latency.py 自带等价实现 + runner 保留一行委托 + 契约测试锁定行为一致），
  按裁决执行，此处仅记录现象。

- [2026-09-16] `core/agent_runner/runner.py`:270 — `admin_disposition_path`
  是模块级函数（接收 `project_root` / `run_id`），但 `run_administrator` / 其它
  调用点未发现 runner 之外的 consumer 打 patch——随迁 `maintenance_runs.py`
  无补丁缝隙风险（与 D2 结论一致）。影响：无。

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