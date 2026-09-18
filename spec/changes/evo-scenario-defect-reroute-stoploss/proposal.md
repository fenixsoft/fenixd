# Proposal: scenario-defect-reroute-stoploss

## Why

2026-09-16/17 fix-dashboard-read-path-performance 事故：2 个场景被判 test-defect（api-specs-structure-latency、api-specs-repeat-requests-stable），场景缺陷改道门（add-scenario-defect-triage-gate 建立）改道重派 judge 修场景，但改道重跑仍是同一批失败；5 小时内 3 次升级人工（09-16 19:43:13、19:50:58；09-17 00:21:01），spec 卡 testing 264 分钟越过阈值触发 blocker，下游 fix-robustness-edge-cases 每轮巡检被依赖拒绝。

日志复核（.fenix/logs/fenixd.log:16252 / 16304 / 16320 / 16406 / 16620 / 17826 / 17840）钉死两点事实——它们决定了本 SPEC 的真实作用面：

1. **3 次升级均非预算耗尽触发。** 改道门有两处收口：①预算收口（`_repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS`=2）；②**改道后立即收口**——改道重派 judge 仍申报 bug-found 且仍为纯场景缺陷时直接升级，不做预算比较（escalation.py:634-645）。事故 3 次升级**全部**走②，每轮只消耗 1 次改道重派（分别在 19:43:13、19:50:58、00:21:01 收口）。日志中的「改道预算耗尽（深度 2→1→1）」是 `_escalate_scenario_defect_reroute` 的固定文案（escalation.py:660-670，① ② 两调用点共用），**并非真的耗尽**。
2. **「改道无效仍同批失败 → 继续消耗改道预算」确有发生。** 09-16 19:37:02 改道重派 judge 申报 scenario-repaired（`[阶段3+] judge 场景原地修复采纳`，深度 1），重入重跑后失败集与改道前**完全相同**；19:39:31 改道门以深度 1 再次触发，深度 1 < 上限 2 → 框架**又消耗一轮改道预算**重派 judge（19:39:31 → 19:43:13，约 4 分钟），直到该轮 judge 自报 bug-found 才收口。

根因：改道门只按次数预算与 judge 自报 verdict 收口，**不比较「改道前失败集」与「改道重跑失败集」**——judge 申报 scenario-repaired 而重跑同批失败时，机制识别不出「改道无效」，只能继续烧改道预算直至深度上限（或等下一轮 judge 自报 bug-found 才收口）。

**目标边界（防目标漂移）**：本 SPEC 只消除「同批失败仍继续消耗改道预算」这一条浪费，不承诺减少升级次数本身——事故中的循环由外部重验再触发（daemon 重启 / 滞留恢复）与人工未响应驱动，不属本 SPEC 作用面；日志中「预算耗尽」文案在非耗尽调用点复用造成的误导，属 escalation.py 既有缺陷，亦不在本 SPEC 变更面内。

## What Changes

- **改道止损判据**：改道重入轮（`_repair_depth >= 1` 且留存轮次与 `_repair_depth - 1` 匹配）的门触发入口，把重跑失败场景集与改道前失败场景集对比；改道前失败集 ⊆ 重跑失败集（含相等，即无任一失败场景被修复）→ 判「改道无效」，立即升级人工，不消耗剩余改道预算；有场景被修复 → 覆盖留存后继续既有预算通道。链首触发（`_repair_depth == 0`）只写留存不判定（防上一链条的陈旧留存误停，保住既有「定向重派 judge 一次」语义）。
- **跨轮失败集留存**：改道前失败场景集（id 列表 + 写入轮次）写入 `.fenix/verify-progress/<spec>/scenario_reroute_stoploss.json`，供改道重入轮比对；读取点 MUST 是改道重入轮的门入口（重跑已完成），缺失/损坏/轮次不匹配 → 保守放行。

## Capabilities

### New Capabilities

- `scenario-defect-reroute-stoploss`: 场景缺陷改道的止损判据——改道未产生修复（重跑仍同批失败）时提前升级人工，不再消耗剩余改道预算。
