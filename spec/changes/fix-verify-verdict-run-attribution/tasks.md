## Deliverables

```yaml
- path: core/pm_engine/verification/legacy.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_verdict_run_attribution.py
  kind: new
- path: tests/test_verdict_contract_singularity.py
  kind: modify
```

## 1. 派发侧归属戳

- [ ] 1.1 `core/pm_engine/engine.py` verify 派发单点：派发前原子预写 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 为 `{"run_id", "role": "verifier", "spec", "status": "dispatched"}`（tmp+rename；OSError 仅 WARNING 不阻断派发）
- [ ] 1.2 单测（tests/test_verdict_run_attribution.py 新建）：派发后文件含本次 run_id 且旧残留（plan-ready 等）被覆盖；写入失败时派发照常

## 2. 消费侧归属校验

- [ ] 2.1 `core/pm_engine/verification/legacy.py` verdict 读取守卫：采信判据改为「role=verifier 且 run_id=当前消费 run 且 status 白名单内」；不满足时先将现文件归档为 `.fenix-run-result.json.stale-<ts>`，再走既有「本轮无裁决」fail-closed 通道（blocked + critical 告警），文案指明「本轮未产出机器可读裁决」；移除 run_id 不符时对当轮结果的「stale/foreign replayed」归因路径
- [ ] 2.2 单测三态：①跨 run 残留 → 归档 + fail-closed 且告警无「replayed」归因；②归属一致 + 合法 verdict → 正常采信；③归属一致 + 仍 dispatched → 「本轮未产出裁决」通道
- [ ] 2.3 in-chain planner plan-ready 写入共享文件的既有行为回归：模拟 planner 后写 plan-ready + verifier 未写 → 判「本轮无裁决」，不影响 planner 既有产物

## 3. 重派丢弃前成果保全

- [ ] 3.1 `_redispatch_fresh_verify` 状态复位前：检查 `report.json` 存在且 mtime（stat UTC）≥ 本轮 verify 派发时刻 → 重命名保全 `report-<run_id>.json`，WARNING + 升级告警文案附保全路径；不满足则跳过保全照常重派
- [ ] 3.2 单测：①新鲜 report + 触发重派 → 保全文件存在、告警含路径；②无 report / 陈旧 report → 无保全文件、重派照常

## 4. 回归

- [ ] 4.1 `tests/test_verdict_contract_singularity.py` 既有用例全绿（verdict 单点契约、role/spec 戳回退语义不回归）
