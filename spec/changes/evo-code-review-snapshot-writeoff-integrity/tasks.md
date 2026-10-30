## Deliverables

```yaml
- path: core/code_review.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: core/dashboard/data/code_review.py
  kind: modify
- path: tests/test_review_snapshot_resolution.py
  kind: new
```

## 1. 核销前对账

- [ ] 1.1 core/code_review.py：resolve_snapshot（:993）入参由指纹集合扩展为观测记录集（file/category/title/新指纹），置 resolved 前对未命中的 open 条目做同 file+category 的归一化标题相似度对账（difflib.SequenceMatcher，缺省阈值 0.55）：命中则迁移存量条目指纹为新指纹、保持 open 并计 updated；未命中置 resolved 且 resolution='snapshot_closed'。
- [ ] 1.2 core/agent_runner/maintenance_runs.py：调用点（:2115）与观测集现算（:2100-2113）按新入参同口径传递观测记录，覆盖门语义不变。

## 2. 核销来源分列

- [ ] 2.1 core/code_review.py：快照核销统一写 resolution='snapshot_closed'（合回核销既有值 'code-fix-auto' 不动，:2201-2203）；审查完成行把 resolved 拆为 snapshot_closed 与 fixed 两个计数输出；存量 resolution=None 历史条目不回填。
- [ ] 2.2 core/code_fix.py：code-fix rollup 与进度 done 累计只统计 resolution='code-fix-auto' 的核销，snapshot_closed 不入修复成果。
- [ ] 2.3 core/dashboard/data/code_review.py：台账投影透出 resolution 字段，修复/龄期统计按来源分列展示。

## 3. 测试

- [ ] 3.1 tests/test_review_snapshot_resolution.py：覆盖同缺陷措辞漂移（相似度≥0.55）对账后保持 open 并迁移指纹不计 resolved、真消失条目正常核销且带 snapshot_closed、相似度低于阈值不误保、完成行两计数分列、rollup 与 dashboard 只把 code-fix-auto 计为修复成果、存量 resolution=None 条目按 snapshot_closed 口径解读不回填。