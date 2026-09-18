# Design: scenario-defect-reroute-stoploss

## 背景与目标

fix-dashboard-read-path-performance（2026-09-16/17）事故：改道门按次数预算运行，改道后仍同批 test-defect 却未中途止损，3 次耗尽预算（深度 2→1→1）、spec 卡 testing 264 分钟触发 blocker。目标：改道无效（同批失败）时提前升级人工，止损于预算耗尽之前。

## 现状

改道门（core/pm_engine/verification/escalation.py:485-594 `_scenario_defect_reroute_gate`）：

- 失败全部 test-defect/flaky 且 product-bug=0 → 拒绝打回 implementer，改道重派 judge；
- `_repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS`（=2，pipeline.py:32）→ `_escalate_scenario_defect_reroute` 升级人工；
- 无失败集跨轮对比。

## 止损判据

改道重派 judge 后读取重跑失败场景集：

- 同批失败（失败集与改道前完全相同，或改道前失败集 ⊆ 重跑失败集）→ 判定改道无效 → 立即 `_escalate_scenario_defect_reroute`（升级人工 + human-escalation-alert scenario_defect_reroute_stoploss）；
- 失败集变化（任一失败场景被修复）→ 改道有效 → 继续既有预算通道。

## 跨轮失败集留存

改道前失败场景集在改道门触发时写入 .fenix/verify-progress/<spec>/scenario_reroute_stoploss.json（失败 id 列表 + 轮次），改道重跑后读取对比；读取缺失/损坏 → 保守放行（继续既有预算通道，不因本机制误停）。

## 边界

- 止损判定只看失败集归属（同批 vs 变化），不判定场景缺陷真伪（那仍由 judge/人工负责）；
- 失败集变化但总数不降（修好一个又新增一个）→ 视为有进展继续预算，最终仍由预算上限兜底；
- 本机制不触碰 impl_run_budget 与 _repair_depth 语义（仅提前触发升级路径）。

## 回归测试

tests/test_scenario_reroute_stoploss.py：

1. 同批失败 → 提前止损升级人工（断言未等 _SCENARIO_REPAIR_MAX_ROUNDS 耗尽）；
2. 失败集变化 → 继续预算通道；
3. 失败集留存文件缺失 → 放行不误停；
4. 既有预算耗尽升级路径回归（不破坏）。