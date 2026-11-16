## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: tests/test_repair_claim_fingerprint_gate.py
  kind: new
```

## 1. 随单附指纹

- [ ] 1.1 core/pm_engine/verification/pipeline.py `_apply_bug_found`：bug-found 派修复的上下文注入被修场景失败指纹（场景 id + 失败签名摘要，读裁决面既有指纹数据 verdict_cache/verdict_stability，不新造指纹体系）；无基线置 null 不阻断派发
- [ ] 1.2 core/pm_engine/verification/pipeline.py `_record_repair_claim`：派单指纹随受理记账留存，受理时可读取用于比对

## 2. 受理指纹门

- [ ] 2.1 core/pm_engine/verification/pipeline.py `_record_repair_claim` 受理路径：比对被修场景盘面最新指纹与派单指纹，未变化走拒收分支（error 留痕含「失败指纹未变化」与双方指纹值、spec 保持当前态、rejected 记账、不重入执行、返回消费信号不穿透守卫、拒收信息经既有重派上下文回传）
- [ ] 2.2 core/pm_engine/verification/pipeline.py：指纹已变化/无基线/场景已 pass 照常受理，修复预算上限、记账口径与耗尽持久态语义零变化

## 3. 实现者申报义务

- [ ] 3.1 agents/implementer.md 修复申报段追加：product 类修复申报前对被修场景做最小真机探针（单场景执行或 API 级探针复跑），申报附探针签名与派单指纹一致性标注，探针复现派单指纹不得申报 success；义务范围限被修场景、不含全量回归

## 4. 测试

- [ ] 4.1 tests/test_repair_claim_fingerprint_gate.py：覆盖指纹未变化拒收（含拒收信息与 rejected 记账断言）、指纹变化放行、无基线放行、申报缺探针标注拒收、拒收不穿透守卫、预算口径不变