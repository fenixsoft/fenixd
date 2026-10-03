## Deliverables

```yaml
- path: core/verdict_check.py
  kind: modify
- path: tests/test_attribution_dedup_cascade_exempt.py
  kind: new
```

## 1. 同因级联组豁免

- [ ] 1.1 core/verdict_check.py：_batch_attribution_dedup_common（:1280-1345）分组阶段（:1315）把 dependency_skipped=true 的场景从「归一化逐字同文 ≥3 即拒」判据单列豁免（锚点用引擎结构化标记而非文案比对）；阈值仅对非级联子集计数——混合组（含真实 failed 同文）仍照拒，pass 场景排除逻辑（:1309）不变。
- [ ] 1.2 core/verdict_check.py：豁免命中时 reason/日志记「同因级联组豁免（N 场景，dependency_skipped）」与场景清单，与既有违规 reason（:1323-1332）区分，经拒绝收口链（verdict_evidence.py:113-140）透传留痕。

## 2. 测试

- [ ] 2.1 tests/test_attribution_dedup_cascade_exempt.py（新建）：纯级联组（≥3 个 dependency_skipped 同文）不再判拒且留痕；混合组（3 个真实 failed 同文＋级联场景）仍拒且 reason 不变；judge 报告自标 dependency_skipped 但与引擎跳过链矛盾时仍判拒（防滥用）；D3「步骤/断言各异」既有豁免行为不回退。
- [ ] 2.2 运行 2026-09-17 fix-verdict-dedup-resynthesis 交付的既有查重用例，将其中「无步骤无断言同文→仍拒」用例按新语义更新（纯级联组豁免、混合组保持拒绝）后全绿。