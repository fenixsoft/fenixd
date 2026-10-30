## Deliverables

```yaml
- path: core/code_review.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/data/code_review.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/QualityTab.tsx
  kind: modify
- path: tests/test_code_review.py
  kind: modify
- path: tests/test_review_snapshot_resolution.py
  kind: new
```

## 1. 核销前对账

- [ ] 1.1 core/code_review.py：resolve_snapshot（:1076）入参由指纹集合扩展为观测记录集（file/category/title/新指纹），置 resolved 前对未命中的 open 条目做同 file+category 的归一化标题相似度对账（difflib.SequenceMatcher，缺省阈值 0.55）：命中则迁移存量条目指纹为新指纹、保持 open 并计 updated；未命中置 resolved 且 resolution='snapshot_closed'。对账须 1:1 领用：一条观测至多对账一条存量条目（相似度最高者优先，并列取 last_seen_at 更近者），被领用观测不得复用。迁移去重：本轮 upsert 已插入同新指纹的 open 孪生条目时合并——保留存量条目（item_id/first_seen_at 稳定）、以观测记录刷新其展示字段、删除孪生；孪生非 open 则放弃迁移按未命中处置。返回值由 int 改为 {'snapshot_closed': n, 'fixed': 0}（本函数不产生合回核销，fixed 占位对齐两计数口径）。
- [ ] 1.2 core/agent_runner/maintenance_runs.py：调用点（:2459）与观测集现算（:2445-2457）按新入参同口径传递观测记录（findings 即观测记录），覆盖门语义不变；run 收尾 CodeReviewResult 装配（:2612-2621）携带拆分后两计数。

## 2. 核销来源分列

- [ ] 2.1 core/code_review.py：快照核销统一写 resolution='snapshot_closed'（合回核销既有值 'code-fix-auto' 不动，:2329）；core/agent_runner/result_gate.py：CodeReviewResult（:367）新增 snapshot_closed/fixed 两计数字段；core/admin_monitor.py：审查完成行（:1918-1925）把 resolved 拆为 snapshot_closed 与 fixed 两个计数输出；存量 resolution=None 历史条目不回填。
- [ ] 2.2 core/code_fix.py 不改码（复核结论：链 rollup resolved 与进度 done 由 mark_resolved 命中累积，core/code_fix.py:5929/:7484/:7489，机制上不含快照核销）；以测试锁定该口径——snapshot_closed 核销不得改变 code_fix 进度 done 与 chain_rollup 计数（见 3.1）。
- [ ] 2.3 core/dashboard/data/code_review.py：台账投影确认 resolution 字段随行记录透传（rows 为完整记录 dict，新字段自动透出）；core/dashboard/static/src/pages/projects/components/QualityTab.tsx：resolved 条目按 resolution 展示来源徽标（code-fix-auto=已修复 / snapshot_closed=快照关闭 / None=存量按快照关闭口径解读），已修复统计按来源分列；存量 resolution=None 历史条目不回填。

## 3. 测试

- [ ] 3.1 tests/test_review_snapshot_resolution.py：覆盖同缺陷措辞漂移（相似度≥0.55）对账后保持 open 并迁移指纹不计 resolved、迁移去重（同指纹仅一条台账条目、first_seen_at 保留、孪生被删）、1:1 领用（两条未命中条目争同一观测只迁移一条）、孪生非 open 放弃迁移按未命中核销、真消失条目正常核销且带 snapshot_closed、相似度低于阈值不误保、完成行两计数分列（CodeReviewResult 字段与 admin_monitor 完成行格式）、snapshot_closed 核销不改变 code_fix 进度 done 与 chain_rollup 计数、dashboard 投影透出 resolution、存量 resolution=None 条目按 snapshot_closed 口径解读不回填。
- [ ] 3.2 tests/test_code_review.py：既有 resolve_snapshot 用例（:221-245，指纹集合入参）迁移至观测记录集新签名，语义断言保持等价。
