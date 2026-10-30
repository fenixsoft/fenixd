## Why

共享 verdict 文件 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 跨 run 复用且无归属标识：add-command-center 事故（2026-10-26）中该文件残留 in-chain planner 的 `{"status": "plan-ready"}`（mtime 17:23），两轮 verify 完成时守卫读到未知状态 + 陈旧 mtime，判「stale/foreign verifier result replayed」——**两轮各 39 分钟的真实验证（16/18 pass、发现 major 产品 Bug）被整体当作重放作废**，且丢弃时无成果保全。这是本轮事故中金额最大的单一浪费点。

## What Changes

- **派发侧归属戳**：verifier 派发单点（`core/pm_engine/dispatch/queue.py` verifier 出队分支，worker 线程启动前）在 per-spec primary verdict 文件 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 预写归属戳 `{role: "verifier", spec, status: "dispatched"}`（原子写），旧残留随之被覆盖。不含 run_id：run/attempt id 在 runner attempt 环内才生成（`<run>-a<n>[-r<m>]`）且逐 attempt 变化，派发点不可得
- **消费侧归属校验**：verdict 消费守卫（report_gate.py `_read_verdict` 单点）三分支：①文件仍为本次派发预写戳（role=verifier 且 status=dispatched）→ 判「本轮未产出裁决」走既有 fail-closed 通道（blocked + critical 告警）；②陈旧 mtime / 异 spec 戳残留 → 先归档 `.stale-<ts>` 备份再走同一 fail-closed 通道，MUST NOT 沿用「stale/foreign 重放」语义把当轮 verify 成果判为他人重放；③agent/judge 正常写出的新鲜裁决（含既有无 role 戳的 primary 直写形态）照既有 role/spec/白名单口径采信——MUST NOT 把 role 门套到 primary（report_gate 既有「primary 豁免 role 门」防线，防误杀当轮合法裁决）
- **丢弃前成果保全**：stale/foreign 重派收敛点丢弃结果前，若本轮 `report.json` 新鲜存在 → 重命名保全 + WARNING + 升级告警附保全路径，杜绝静默扔验证成果

## Capabilities

### New Capabilities
- `verify-verdict-run-attribution`: verdict 文件 run 级归属戳与采信判据——跨 run 残留不得作为本轮 verdict 输入，当轮验证成果丢弃前必须保全留痕

### Modified Capabilities

## Impact

- `core/pm_engine/verification/report_gate.py`：verdict 读取守卫单点（`_read_verdict` / `_verifier_stamp_gate` / stale 判定段实际位于此，legacy.py 与三阶段 judge 车道共用）
- `core/pm_engine/verification/legacy.py`：stale/foreign 消费处置段归因文案修正与成果保全（`_redispatch_fresh_verify` 随重派通道改向按死代码口径处理）
- `core/pm_engine/dispatch/queue.py`：verifier 出队派发分支预写归属戳（「Dispatching」日志点；engine.py 无 verify 派发单点）
- `tests/test_verdict_contract_singularity.py` 既有契约回归；新增 `tests/test_verdict_run_attribution.py`
- in-chain planner 写 `plan-ready` 到同一共享文件是既有行为，不禁止：新鲜 plan-ready 照既有「验证未完成」通道（保持 testing），陈旧 plan-ready 残留走归档 + fail-closed
