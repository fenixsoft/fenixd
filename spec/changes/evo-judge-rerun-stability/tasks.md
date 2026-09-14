# 任务

## Deliverables

```yaml
- path: core/verify_report.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: tests/test_verdict_stability.py
  kind: new
```

## 1. verdict_cache.json 读写与「两轮一致复用」判定

- [ ] 1.1 core/verify_report.py：新增 read/write_verdict_cache 与 is_verdict_stable 判定；复用判据为 spec 戳未变 && report.json mtime 未变 && 连续两轮 verdict 一致。

## 2. pm_engine verified 一次性放行门

- [ ] 2.1 core/pm_engine/verification.py：在裁决应用出口加 verified 门，verified 且场景集未变时拒绝被覆盖为 blocked/bug-found；写单元测试覆盖「verified 落盘后 legacy unknown-status 不得改判」。

## 3. judge 重跑计数与硬上限

- [ ] 3.1 core/pm_engine/family.py：单 spec judge run 计数（judge_rerun_count），连续两轮一致即停；总数超上限（5）转人工裁决；STATE.md 增量时间线记账。

## 4. 回归测试（implementer 残留 success 污染场景）

- [ ] 4.1 tests/test_verdict_stability.py：模拟主树共享 .fenix-run-result.json 被 implementer 残留 status=success 污染时，verified 门仍拒绝降级；judge 两轮一致不产生第三轮。
