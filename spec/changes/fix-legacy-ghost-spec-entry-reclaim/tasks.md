# Tasks: fix-legacy-ghost-spec-entry-reclaim

## 1. 幽灵指纹判定与对账组件

- [x] 1.1 `core/pm_engine/spec_integrity.py` 新增幽灵指纹判定函数：对非终态条目（`pushed` 豁免）执行 design D2 三条件 AND 判定（`spec_has_content` 为 False + `git -C project_root log --all -- spec/changes/<name>` 空输出 + created 距今 ≥ 30 分钟），返回命中清单（每项含三项证据）；`spec_has_content` 与 `_is_safe_spec_name` 复用既有实现，非法路径成分 spec 名不进命中清单、另入跳过清单待告警
- [x] 1.2 新鲜度窗为模块常量（30 分钟），命名与注释对齐既有常量惯例（参照 IMPL_RUN_BUDGET_USED_FIELD 家族的定义形态）
- [x] 1.3 清退动作函数：先收集全部命中再批量执行——逐条 `remove_spec` + 逐条台账留痕（kind=`ghost-entry-reclaimed`，含三项证据）；一轮至多一条聚合告警列出全部清退项，防重对齐 `check_spec_content_missing` 的 full_scan 未处理告警先例（spec_integrity.py:253）

## 2. 挂点接入

- [x] 2.1 daemon 启动回填期调用一次对账；full_scan 周期复扫（幂等：零命中零副作用、零日志噪音）
- [x] 2.2 配置开关 `gates.ghost_entry_reclaim`（默认 on）经 ConfigLoader 点号键读取，off 时对账入口直接返回

## 3. 单测（tests/test_spec_content_integrity.py 扩展）

- [x] 3.1 指纹真值表：三条件各自翻转即不命中；全中即命中；blocked+frozen 条目全中亦命中（冻结不豁免）
- [x] 3.2 新鲜度豁免（< 30 分钟不清退）与非法 spec 名跳过；物化过 proposal.md 的条目（arbiter 7f7ee45e2 范式最小成文）不命中
- [x] 3.3 清退断言：remove_spec 被调、STATE 条目消失、台账 kind 与证据字段、聚合告警单条含全清单
- [x] 3.4 幂等重放：第二轮对账零清退、告警不重复；`gates.ghost_entry_reclaim: off` 时全跳过

## 4. 验证

- [x] 4.1 `python3 -m pytest tests/test_spec_content_integrity.py -q` 通过
- [ ] 4.2 孪生条目判定验证（dry-run）：以主树 STATE 快照只读跑指纹判定，命中清单应恰含 `fix-planner-scenario-entry-schema-selfcheck`；本条目（已物化 proposal.md）不命中。实盘清退由 daemon 合并后首轮对账自动完成，不由实现 run 执行（以孪生 recorded 指纹形态重建只读 dry-run 替代验收：孪生条目已不在主树 STATE——proposal 落盘后经人工通道移除，admin_alerts 仅存 2026-10-31 升级记录；替代验证=重建 blocked+frozen/created 2026-10-31/目录缺失/git 零提交形态跑生产判定函数命中恰含孪生、本条目不命中，零提交条件另对真实主树 git 历史直接核实；证据 .fenix/verify-evidence/fix-legacy-ghost-spec-entry-reclaim/twin-dryrun-substitute.json）
- [x] 4.3 回归：`python3 -m pytest tests/test_pm_recovery.py tests/test_run_lifecycle_governance.py -q` 通过，正常流转条目零影响

## Deliverables

```yaml
- path: core/pm_engine/spec_integrity.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_spec_content_integrity.py
  kind: modify
```
