# 场景缺陷改道止损
<!-- knowledge: capability=scenario-defect-reroute-stoploss rev=1 sources=spec/archive/2026-09-23-evo-scenario-defect-reroute-stoploss -->

改道未产生实际修复（重跑仍同批失败）时的提前止损判据：立即升级人工，不再消耗剩余改道预算。

## 现行规则

- 改道止损判据：改道重入轮（`_repair_depth >= 1` 且留存记录轮次与 `_repair_depth - 1` 匹配）的改道门触发入口，把重跑失败场景集与改道前失败场景集对比——改道前失败集为重跑失败集的子集（含相等，即无任一改道前失败场景被修复）→ 判定「改道无效」，提前止损升级人工（human-escalation-alert `scenario_defect_reroute_stoploss`），不继续消耗剩余 `_repair_depth` 预算、不再重派 judge。
- 有进展继续预算：存在改道前失败场景已不在重跑失败集中（有场景被修复）→ 覆盖留存后继续走既有改道预算通道（预算耗尽仍升级人工）。
- 链首不判定：链首触发（`_repair_depth == 0`）不做同批判定——只写留存、照常走既有改道通道，防止上一链条遗留的陈旧留存误停全新验证轮。
- 跨轮失败集留存：改道前失败场景集持久化到 `.fenix/verify-progress/<spec>/scenario_reroute_stoploss.json`（失败场景 id 列表、写入时的 `_repair_depth` 轮次、写入时间），供改道重入轮比对；读取缺失/损坏/结构不符/轮次不匹配时保守放行，不因本机制误停。

## 溯源

- [2026-09-23 evo-scenario-defect-reroute-stoploss](spec/archive/2026-09-23-evo-scenario-defect-reroute-stoploss/) — 新增改道重入轮的同批失败集比对与提前止损、跨轮失败集留存文件（此前改道只按次数预算与 judge 自报 verdict 收口，judge 申报修复而重跑同批失败时机制识别不出改道无效、继续空烧改道预算）
