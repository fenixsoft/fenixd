# Design: scenario-defect-reroute-stoploss

## 背景与目标

fix-dashboard-read-path-performance（2026-09-16/17）事故：2 个场景（api-specs-structure-latency、api-specs-repeat-requests-stable）判 test-defect，改道重派 judge 修场景后重跑仍同批失败，5 小时内 3 次升级人工（09-16 19:43:13、19:50:58；09-17 00:21:01），spec 卡 testing 264 分钟触发 blocker。

日志复核（.fenix/logs/fenixd.log:16252 / 16304 / 16320 / 16406 / 16620 / 17826 / 17840）钉死两点事实，作为本 SPEC 的目标边界：

- **3 次升级均非预算耗尽触发**：改道门有两处收口——①预算收口（`_repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS`）、②改道后 judge 仍 bug-found 且仍纯场景缺陷的**立即收口**（escalation.py:634-645，不做预算比较）。事故 3 次升级全部走②，每轮只消耗 1 次改道重派。日志「预算耗尽（深度 2→1→1）」是 `_escalate_scenario_defect_reroute` 的固定文案（escalation.py:660-670，① ② 两调用点共用），不代表真的耗尽。
- **「改道无效仍同批失败 → 继续消耗预算」确有发生**：09-16 19:37:02 改道重派 judge 申报 scenario-repaired（深度 1），重入重跑失败集与改道前完全相同；19:39:31 改道门以深度 1 再次触发，深度 1 < 上限 2 → **又消耗一轮改道预算**（19:39:31→19:43:13 的 judge run）才由②收口。

目标：改道无效（重跑失败集与改道前同批）时，在**同一条改道链内**提前收口升级人工，不再消耗剩余改道预算。

**明确不解决**：本机制不减少升级次数本身——事故循环由外部重验再触发（daemon 重启/滞留恢复）+ 人工未响应驱动，非本 SPEC 作用面；存量「预算耗尽」文案在非耗尽调用点复用造成的日志误导属 escalation.py 既有缺陷，如需修正另立 SPEC。

## 现状

改道门（core/pm_engine/verification/escalation.py:485 `_scenario_defect_reroute_gate`）：

- 失败全部 test-defect/flaky 且 product-bug=0 → 拒绝打回 implementer，改道重派 judge；
- 预算收口：`_repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS`（=2，pipeline.py:32）→ 升级人工；
- 改道后收口（escalation.py:634-645）：重派 judge 仍 bug-found 且纯场景缺陷 → 升级人工；申报 scenario-repaired → 冻结记账后 `_run_three_stage_verification(_repair_depth + 1)` 重入重跑；
- **无失败集跨轮对比**：重入重跑失败集是否与改道前同批，无人判定。

同型判定的既有先例（语义直接复用）：fix-frozen-scenario-orphan-reservoir「错误清单与上轮相同或为上轮超集 → 判未消费反馈，不再重跑」（见 spec/archive/2026-09-15-fix-frozen-scenario-orphan-reservoir/design.md:48，实现于 pipeline.py `_replan_errors_unconsumed`）。该先例的 prev/cur 对比发生在**同一调用链内**（局部变量，不落盘）；本 SPEC 需跨「改道重派 → 重入重跑 → 下次门触发」保留，故改用 spec 级留存，并显式补链内作用域约束（见下）。

## 止损判据

**读取点**：改道重入轮的门触发入口（即重入重跑已产生新 report.json 后的那次 gate 调用）。MUST NOT 在同一次门调用内「重派 judge 前读一次」——那时重跑尚未发生，report.json 仍是改道前的旧产物，读到的必然是同批（假止损）。

**链内作用域（防陈旧留存误停）**：仅当本次门触发为改道重入轮（`_repair_depth >= 1`）且留存记录轮次与 `_repair_depth - 1` 匹配时才做同批判定；链首触发（`_repair_depth == 0`）只写入不判定。依据：`_repair_depth` 是调用链内参数，每次全新验证轮都从 0 起（pipeline.py:1349 默认值 0；engine.py:1543 不传该参），若不限定，上一链条遗留的留存会被新链条首个门触发读到并立即升级——既跳过 add-scenario-defect-triage-gate D2「定向重派 judge 一次」的既有语义，也使人工解冻/daemon 重启后的首个门触发即升级（事故中 19:48:18、00:18:52 两次门触发均为全新轮的深度 0，与上一链条失败集完全相同，正是该误停的实证形态）。

**同批判定**：改道前失败集 ⊆ 重跑失败集（含相等）→ 判「改道无效」→ 立即 `_escalate_scenario_defect_reroute`（升级人工 + human-escalation-alert scenario_defect_reroute_stoploss），不消耗剩余 `_repair_depth` 预算；存在任一改道前失败场景已不在重跑失败集中（有场景被修复）→ 判「改道有效」→ 覆盖留存后继续既有预算通道。口径与先例的超集判定一致（纯新增、无一修复 = 未消费 = 无效）。

## 跨轮失败集留存

路径 `.fenix/verify-progress/<spec>/scenario_reroute_stoploss.json`（与该目录既有 scenario_reroute_directive.json / triage_recheck.json 同级；已核 core/ 无任何代码 glob/iterdir 该目录，新增文件无消费方冲突）。结构：

```json
{"round": 0, "failed_ids": ["<scenario id>", "..."], "written_at": "<iso8601>"}
```

时序：门入口 → 读留存（缺失/损坏/结构不符 → 视为无留存，保守放行）→ 满足链内作用域且判同批 → 升级收口（不再重派）；否则 → 写当前 `dist["failed_ids"]` 覆盖留存（写失败仅告警，不阻断改道）→ 继续既有改道/预算通道。

## 边界

- 止损判定只看失败集归属（同批 vs 有修复），不判定场景缺陷真伪（那仍由 judge/人工负责）；
- 失败集变化但总数不降（修好一个又新增一个）→ 视为有进展继续预算，最终仍由预算上限兜底；纯新增（无一修复）→ 按同批止损；
- 本机制不触碰 impl_run_budget 与 _repair_depth 语义（仅提前触发升级路径）；
- 留存不因过期/跨链/损坏而误停：非改道重入轮、轮次不匹配、缺失/损坏一律放行。

## 回归测试

tests/test_scenario_reroute_stoploss.py：

1. 改道重入轮（深度 1）同批失败 → 提前止损升级人工（断言未等 _SCENARIO_REPAIR_MAX_ROUNDS 耗尽、run_planner 未被调用）；
2. 改道重入轮有场景修复 → 继续预算通道（仍重派 judge）；
3. 改道重入轮纯新增失败场景（无一修复）→ 判同批止损；
4. 链首触发（深度 0）+ 存在陈旧留存且失败集相同 → **不**止损，照常重派（防陈旧误停回归）；
5. 留存缺失/损坏/轮次不匹配 → 放行不误停；
6. 既有预算耗尽升级路径回归 + tests/test_scenario_reroute_gate.py 全量不破坏（既有用例每例独立 tmpdir，无留存即放行）。
