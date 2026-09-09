# Proposal: fix-frozen-scenario-orphan-reservoir

## Why

2026-09-08 `add-verify-contract-autodraft` 冻结场景验收失败三连发（本地 13:26/15:14/16:46），引发 3 次场景计划争议升级 + 5 个 admin 处置 run（2 次升级人工），spec 全程 20821s / $50.24 / impl 预算 6 轮用满。调查证实三层叠加缺口：①场景文件补齐路径自己写入结构性非法的占位条目（仅 id+description）；②持久化集 scenarios.json 是感染储库——写端零校验、admin 修复只清一个文件致孤儿跨轮复活（现存仍残留 7 条孤儿）；③场景重跑无反馈消费硬门，planner 坏产物原样复发、重复成本全数支付且每轮外溢为 admin/人工往返。

## What Changes

- **三文件写端 schema 门**：`test_scenarios.json` / `scenarios.json` / `_scenarios_full.json` 的任何写入端（planner 产物收编、冻结 diff 写回、补齐写回、备份更新）必须通过与 `load_scenarios` 同源的结构校验，非法条目落盘即拒，替代「读端校验、错误在最远端爆炸」的现状。
- **补齐占位改弃场景**：`_apply_scenario_freeze` 无理由缺场景补齐时，备份缺定义的条目不再写入 `{"id","description"}` 非法占位，改为登记「场景定义不可恢复」并从本轮验证集剔除（宁少验一个，不写必败文件）。
- **持久化集加载净化**：`load_scenario_set` 读入时对无 kind 的孤儿条目净化（剔除+告警留痕），斩断储库复活通道。
- **重跑消费硬门 + 分级升级**：场景验收失败重跑前，校验 planner 新产物对上轮错误清单的逐条处置（错误逐条消除）；未消费即拒绝派发，升级 admin 自动处置（admin 修复场景文件必须过同一 schema 门）；admin 处置后重验仍失败（第 2 轮）→ 结构化冻结 + 升级人工，人工裁决项为「是否删除冻结集重新出题」，告警附上轮 planner 实际成本供参考。
- **存量污染清理**：清理 `.fenix/verify-progress/add-verify-contract-autodraft/scenarios.json` 现存 7 条孤儿残留（运行时操作，非仓库交付物）。

## Capabilities

### New Capabilities
- `scenario-write-schema-gate`: 场景三文件（test_scenarios.json / scenarios.json / _scenarios_full.json）写端结构校验门、补齐占位改弃场景、持久化集加载净化。
- `scenario-replan-consumption-gate`: 场景验收失败重跑前的反馈消费硬门与分级升级通道（拒绝派发 → admin 自动处置 → 人工裁决重出题）。

### Modified Capabilities

（无——`verify-scenario-freeze` 已归档且本次未改变「冻结跨轮一致、变更须裁决」的需求语义，仅治理其执行路径缺陷；行为修订全部并入上述新能力。）

## Impact

- `core/pm_engine/verification.py`：`_apply_scenario_freeze` 补齐路径、场景验收失败 replan 分支、`_escalate_env_blocked` 升级通道。
- `core/verify_scenarios.py`：`diff_planner_output`（孤儿条目收编点）、`save_scenario_set`（写端校验挂点）、`load_scenario_set`（加载净化）。
- `core/verify_engine/scenarios.py`：`load_scenarios` 校验逻辑复用（提取可独立调用的结构检查函数）。
- admin 处置唤起 prompt（`core/agent_runner/prompt_builder.py`）：修复指令须声明过 schema 门与双文件一致性（test_scenarios.json 与 scenarios.json 同步）。
- `.fenix/verify-progress/*/` 运行时文件：写入行为变化，非仓库交付物。
