## Deliverables

```yaml
- path: tests/test_cancel_holdstate_recovery.py
  kind: modify
```

## 1. 定位函数与锚点表

- [ ] 1.1 在 `CancelFinalizeMarkerContract` 内新增 `_locate(rel, anchor, label)` 定位函数：以 `anchor in line` 检索文件，0 次命中抛「锚点串未命中（注释被改写/删除？）」、>1 次命中抛「锚点串命中 N 次，不唯一」，报错均含 rel + label + 锚点串原文
- [ ] 1.2 `WRITE_POINTS` 由 `(rel, line_no, label)` 改为 `(rel, anchor, label)`，按 design D1 锚点表填入六处锚点串（implementer / fast-track / repair / planner-plan / planner-judge / legacy-verifier）

## 2. 断言改造与注释清理

- [ ] 2.1 `test_six_holdstate_write_points_carry_marker` 改为：取 `_locate` 返回的锚点行起 `[anchor_line, anchor_line+25)` 窗口，断言窗口内同时出现 `"_cancelled_hold": True` 与 `"error": cancelled_err`
- [ ] 2.2 删除 `WRITE_POINTS` 块内三次重钉留下的绝对行号考古注释（981/1005/1055 等历史行号与 14380774/2e98e052/762b4aee 溯源），代以六条锚点串 + 每条一句语义说明

## 3. 双重对账与全量验证

- [ ] 3.1 对齐 `test_no_new_holdstate_write_point_missed` 全库扫描：命中的写点文件集合与六条锚点表条目一一对应（数量与文件集合一致），互为印证
- [ ] 3.2 全量跑 `tests/test_cancel_holdstate_recovery.py`：当前已红灯的 3 个 subtest（planner-plan / planner-judge / legacy-verifier）恢复绿，全部用例通过