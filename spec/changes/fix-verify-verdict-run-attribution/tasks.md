## Deliverables

```yaml
- path: core/pm_engine/verification/legacy.py
  kind: modify
- path: core/pm_engine/verification/report_gate.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: tests/test_verdict_run_attribution.py
  kind: new
- path: tests/test_verdict_contract_singularity.py
  kind: modify
```

## 1. 派发侧归属戳

- [x] 1.1 `core/pm_engine/dispatch/queue.py` verifier 出队分支（transition 成功后、worker 线程启动前）：原子预写 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 为 `{"role": "verifier", "spec", "status": "dispatched"}`（tmp+rename；OSError 仅 WARNING 不阻断派发；不含 run_id——attempt id 在 runner attempt 环内生成，派发点不可得）
- [x] 1.2 单测（tests/test_verdict_run_attribution.py 新建）：派发后文件为三键归属戳且旧残留（plan-ready 等）被覆盖；写入失败时派发照常

## 2. 消费侧归属校验

- [x] 2.1 `core/pm_engine/verification/report_gate.py` `_read_verdict` 消费守卫三分支：①白名单内正常裁决（含无 role 戳新鲜 primary）照既有口径采信，不把 role 门套到 primary；②文件仍为派发预写戳（dispatched）→「本轮未产出裁决」fail-closed（blocked + critical 告警）；③陈旧 mtime / 异 spec 戳残留 → 先归档 `.fenix-run-result.json.stale-<ts>` 再走同一 fail-closed，文案「本轮未产出机器可读裁决」；移除 stale/foreign 命中时对当轮结果的「replayed」归因与自动整轮重派。`core/pm_engine/verification/legacy.py` 消费分支同步：归因文案/处置改向对齐（`_redispatch_fresh_verify` 若无剩余调用点按死代码口径移除）
- [x] 2.2 单测三态：①文件为派发预写戳原样 → blocked「本轮未产出裁决」且告警无「replayed」归因；②agent 正常写出的无戳新鲜 verdict（白名单内）→ 正常采信（不回退 primary 豁免）；③陈旧异归属残留 → 归档 + fail-closed + 无「replayed」归因 + 不重派
- [x] 2.3 in-chain planner plan-ready 既有行为回归两态：新鲜 plan-ready（本轮写出）→ 既有「验证未完成」通道（保持 testing），产物不被归档覆盖；陈旧 plan-ready 残留 → 归档 + fail-closed

## 3. 重派丢弃前成果保全

- [x] 3.1 verdict 消费守卫判「残留 / 本轮未产出裁决」丢弃当轮成果进入 fail-closed 前：检查 `report.json` 存在且 mtime（stat UTC）≥ 本轮 verify 派发时刻（优先从 result.run_id 内嵌 epoch 解析，回退本轮 run 流启动时刻）→ 重命名保全 `report-<run_id>.json`，WARNING + 升级告警文案附保全路径；不满足则跳过保全照常 fail-closed。保全 MUST NOT 挂 `_redispatch_fresh_verify`（本 SPEC 改向后该点不可达）
- [x] 3.2 单测：①新鲜 report + 守卫判残留/未产出裁决 → 保全文件存在、告警含路径；②无 report / 陈旧 report → 无保全文件、fail-closed 照常

## 4. 回归

- [x] 4.1 `tests/test_verdict_contract_singularity.py` 既有用例全绿（verdict 单点契约、role/spec 戳回退语义不回归）
