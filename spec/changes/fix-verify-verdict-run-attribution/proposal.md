## Why

共享 verdict 文件 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 跨 run 复用且无归属标识：add-command-center 事故（2026-10-26）中该文件残留 in-chain planner 的 `{"status": "plan-ready"}`（mtime 17:23），两轮 verify 完成时守卫读到未知状态 + 陈旧 mtime，判「stale/foreign verifier result replayed」——**两轮各 39 分钟的真实验证（16/18 pass、发现 major 产品 Bug）被整体当作重放作废**，且丢弃时无成果保全。这是本轮事故中金额最大的单一浪费点。

## What Changes

- **派发侧归属戳**：verify 派发时在共享 verdict 文件预写归属戳 `{run_id, role: "verifier", spec, status: "dispatched"}`（原子写），旧残留随之被覆盖
- **消费侧归属校验**：verdict 消费守卫只采信「role=verifier 且 run_id=当前消费 run」的裁决；其余（无戳 / plan-ready / 陈 run_id / 仍为 dispatched）一律判「本轮无裁决」走既有 fail-closed 通道并归档残留（`.stale-<ts>` 备份），MUST NOT 沿用「stale/foreign 重放」语义把当轮 verify 成果判为他人重放
- **丢弃前成果保全**：stale/foreign 重派收敛点丢弃结果前，若本轮 `report.json` 新鲜存在 → 重命名保全 + WARNING + 升级告警附保全路径，杜绝静默扔验证成果

## Capabilities

### New Capabilities
- `verify-verdict-run-attribution`: verdict 文件 run 级归属戳与采信判据——跨 run 残留不得作为本轮 verdict 输入，当轮验证成果丢弃前必须保全留痕

### Modified Capabilities

## Impact

- `core/pm_engine/verification/legacy.py`：verdict 读取守卫与 stale/foreign 重派收敛点（`_redispatch_fresh_verify`）
- `core/pm_engine/engine.py`：verify 派发单点（「Dispatching verifier」处）预写归属戳
- `tests/test_verdict_contract_singularity.py` 既有契约回归；新增 `tests/test_verdict_run_attribution.py`
- in-chain planner 写 `plan-ready` 到同一共享文件是既有行为，不禁止，靠 role/run_id 判据天然隔离
