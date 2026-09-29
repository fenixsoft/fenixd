# 场景写入结构门
<!-- knowledge: capability=scenario-write-schema-gate rev=1 sources=spec/archive/2026-09-15-fix-frozen-scenario-orphan-reservoir -->

场景三文件写入端的结构校验门：非法条目落盘即拒，替代「读端校验、错误在最远端爆炸」；补齐不再写必败占位条目。

## 现行规则

- 三文件写端结构校验门：场景相关三文件（`test_scenarios.json` / `scenarios.json` / `_scenarios_full.json`）的任何写入端必须执行与读端 `load_scenarios` 同源的结构校验，非法条目拒绝落盘。覆盖写入点：planner 产物收编写回（`_apply_scenario_freeze`）、无理由缺失补齐写回、`scenarios.json` 持久化写回（`save_scenario_set`）、`_scenarios_full.json` 备份更新——全部经过同一个校验函数，不存在绕过校验的写入路径。校验失败留痕（日志 + 验证报告场景集变更小节），验证流程不因拦截本身中断。
- 补齐占位改弃场景：无理由缺失场景补齐时，若备份 `_scenarios_full.json` 中不存在该场景的完整定义，不写入仅含 `id`/`description` 的最小占位条目——而是登记「定义不可恢复」、从本轮验证集剔除，并在日志与验证报告场景集变更小节留痕（剔除场景 id 清单）；备份存在完整定义时照常补回。
- 持久化集加载净化：`load_scenario_set` 读入 `scenarios.json` 时剔除缺少 `kind` 的孤儿条目（无 kind 无法路由到任何 Runner），输出 WARNING 留痕（含剔除条目 id 清单），净化不静默；净化只影响内存集合，不改写原文件（文件修正由写端门与清理任务负责）。

## 溯源

- [2026-09-15 fix-frozen-scenario-orphan-reservoir](spec/archive/2026-09-15-fix-frozen-scenario-orphan-reservoir/) — 新增三文件写端结构校验门、补齐占位改弃场景、持久化集加载净化（此前写端零校验，补齐路径自己写入结构性非法占位条目、持久化集成为孤儿跨轮复活的感染储库）
