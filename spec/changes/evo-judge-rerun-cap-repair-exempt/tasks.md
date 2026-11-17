## Deliverables

```yaml
- path: core/pm_engine/verification/judge_gate.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/verification/verdict_evidence.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: tests/test_judge_cap_repair_exempt.py
  kind: new
```

## 1. 豁免机制落地

- [x] 1.1 core/state_machine.py：新增 `_judge_cap_repair_exempt_avail`（bool）与 `_judge_cap_exempt_used`（int，封顶默认 3）字段定义；`unfreeze_spec` 清零集补两字段成对清除；防毒注释段同步豁免语义（旗标不接人工/复位通道）
- [x] 1.2 core/pm_engine/verification/pipeline.py：`_record_repair_claim` 修复申报受理的同一原子写中，当 `_judge_cap_exempt_used` 未达封顶时置 `_judge_cap_repair_exempt_avail=True`
- [x] 1.3 core/pm_engine/verification/judge_gate.py：派发门 bump 后判定段消费豁免——`count > _MAX_JUDGE_RERUNS` 且旗标在位时清旗标、豁免消费计数加一、放行本次派发，不进 `_judge_hard_cap_freeze`；主计数不回退（预算近满压缩分支 `count > base + _JUDGE_CONSERVE_REMAINING` 与常规分支两处冻结判定同接豁免；inconclusive 分流分支不涉及）
- [x] 1.4 core/pm_engine/verification/verdict_evidence.py：verified 落定清零分支补两字段
- [x] 1.5 core/dashboard/data/admin_actions.py：admin 手动清零点补两字段

## 2. 冻结告警附失败集轨迹

- [x] 2.1 core/pm_engine/verification/judge_gate.py：`_judge_hard_cap_freeze` evidence 拼装段追加 verdict_stability.json 轮内 failed_ids 序列（复用 core/verify_report.py 既有读取；侧车缺失时降级省略、不阻塞冻结；侧车仅保留最近两轮，verify_report.py:1813/1864，轨迹按至多两个轮次点口径）

## 3. 测试

- [x] 3.1 tests/test_judge_cap_repair_exempt.py：覆盖豁免放行路径（count 达 5 + 修复申报受理 → 放行、旗标消费、主计数照常累计）与封顶路径（消费 3 次后不再置旗标、超上限即冻结）；豁免放行路径含常规与预算近满压缩两分支各一例
- [x] 3.2 tests/test_judge_cap_repair_exempt.py：覆盖三处清零链（verified 落定 / unfreeze_spec / admin 清零）后两新字段归零的回归
- [x] 3.3 tests/test_judge_cap_repair_exempt.py：覆盖冻结 evidence 含 failed_ids 轨迹、侧车缺失时降级省略