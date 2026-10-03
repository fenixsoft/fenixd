## Deliverables

```yaml
- path: core/verdict_check.py
  kind: modify
- path: core/pm_engine/verification/verdict_evidence.py
  kind: modify
- path: tests/test_attribution_dedup_cascade_exempt.py
  kind: new
```

## 1. 同因级联组豁免

- [ ] 1.0 core/pm_engine/verification/verdict_evidence.py：_run_attribution_gate（:21-107，首轮/重试/重合成三处轮次共用的查重门统一入口）在调用查重前按 scenario_id 把引擎执行结果条目的 dependency_skipped/skipped_depends_on 合并进 report 场景条目（框架结构化透传；该标记现仅存在于引擎执行结果，全仓仅 core/verify_engine/engine.py:423-424 写入、零消费侧，不透传则豁免恒不命中；judge 自行申报的同名字段不作为豁免依据）。
- [ ] 1.1 core/verdict_check.py：_batch_attribution_dedup_common（:1280-1362）分组阶段（:1315）把 dependency_skipped=true 的场景从「归一化逐字同文 ≥3 即拒」判据单列豁免（锚点用引擎结构化标记而非文案比对）；阈值仅对非级联子集计数——混合组（含真实 failed 同文）仍照拒，pass 场景排除逻辑（:1309）不变。
- [ ] 1.2 core/verdict_check.py：豁免命中时返回结构新增豁免段（「同因级联组豁免（N 场景，dependency_skipped）」＋场景清单），由 core/pm_engine/verification/verdict_evidence.py 的 _run_attribution_gate 记 info 日志留痕，与既有违规 reason（:1324-1334）体系区分；豁免=无 violations，不触发拒绝收口链 _rejection_closure（:110-149 仅对 violations 非空执行），留痕不走该链。

## 2. 测试

- [ ] 2.1 tests/test_attribution_dedup_cascade_exempt.py（新建）：纯级联组（≥3 个 dependency_skipped 同文）不再判拒且留痕；混合组（3 个真实 failed 同文＋级联场景）仍拒且 reason 不变；judge 报告自标 dependency_skipped 但框架透传的引擎标记缺失/矛盾时仍判拒（防滥用，配合 1.0 透传语义）；D3「步骤/断言各异」既有豁免行为不回退。
- [ ] 2.2 运行 2026-09-17 fix-verdict-dedup-resynthesis 交付的既有查重用例（tests/test_verdict_credibility_gate.py：TestDedupNormalizationCascadeExemption / TestBatchAttributionDedup），将其中「无步骤无断言同文→仍拒」用例按新语义更新（纯级联组豁免、混合组保持拒绝）后全绿。
