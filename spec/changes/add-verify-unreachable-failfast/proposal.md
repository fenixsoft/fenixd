# Proposal: add-verify-unreachable-failfast

## Why

验证阶段2.5 应用可达性自愈失败（就绪探针 120s 超时、prepare 失败、契约缺失）后，本轮仍整轮执行全部场景再靠判定链末段兜底——`add-spec-approve-push-modal` 首轮 14 场景 6 通过/7 环境伪失败，连带 judge 50 turns 原地打回重新实现（69 turns），单 spec 全流程 $39.12 居窗口之首。根因：`_ensure_app_reachable` 的不可达结果只落日志被丢弃（`verification.py:1792-1796`），自愈失败未短路本轮。

## What Changes

- **可达性自愈失败即本轮 fail-fast**：验证阶段2.5 中 `_ensure_app_reachable` 返回 `reachable=False` 且 `not user_blocked` 时，框架 MUST NOT 进入场景执行（`engine.run`），也 MUST NOT 退回 plan 重排，直接复用既有升级通道 `_escalate_env_blocked`（落 blocked → 自动呼叫 Administrator → 连续 2 轮冻结转人工）并结束本轮——场景执行数=0，环境错误从「整轮空转 + 判定误拒」降为「1 次升级 + blocked 等 admin」。
- **证据保留下移**：升级 violation/evidence 使用 `reach_note`（已由 `add-verify-preflight-gate` D3 内嵌 boot.log 尾部），不产 verification-report.md（与消费期轻量自证短路 D2 同语义）。
- **保留 `user_blocked` 守卫**：短路条件含 `not user_blocked`；该预留位当前恒 `False`，将来「需用户参与（收验证码/登录）」场景实现判定位后不得被短路误杀。
- **顺带消除契约缺失子案的整轮空转**：契约缺失/解析失败子案当前同样跑完整轮（`_ensure_app_reachable` 内部已自写 `verify_contract_missing` 信号），短路只补 `_escalate_env_blocked` 落态、不重写信号，一处短路统一命中三分支。

## Capabilities

### New Capabilities

- `verify-unreachable-failfast`: 验证前置可达性短路门——`_ensure_app_reachable` 自愈失败（探针超时/prepare 失败/契约缺失）后本轮 fail-fast 升级 env blocked，不执行任何场景，场景执行数=0。

### Modified Capabilities

（无——归档中 `verify-environment-sanity-gate` 治理「场景结算后逐场景探针降级 blocked-env」，本能力治理「场景执行前自愈失败短路」，互补不重叠；`add-verify-preflight-gate` 已 pushed，其 D1/D2/D3 分别治理 spawn 前入口预检、消费期契约自证、boot.log 取证，均不短路本轮，本能力补其 Non-Goals 之外。）

## Impact

- 代码：`core/pm_engine/verification.py`（`_run_three_stage_verification` 阶段2.5 插入短路点，约 1796 行后；复用既有 `_escalate_env_blocked`，零新机制）
- 测试：`tests/test_pm_verification.py`（新增短路回归：自愈失败→0 场景+blocked+admin call、可达→行为逐字节不变、`user_blocked` 守卫放行）
- 交互边界：
  - `add-verify-preflight-gate`（pushed）：复用其 D3 boot.log 尾部证据（已在 `reach_note` 内），不改其语义。
  - `verify-environment-sanity-gate`（归档）：本能力在执行前短路，该归档能力在执行后逐场景降级，无重叠。
  - `add-blocked-reverify-lane`（pushed）：短路落 blocked 后，admin 处置收尾 → 重验路径不变，本能力只前置触发时机。
- 行为影响：健康轮行为逐字节不变（`reachable=True` 时短路点不触发）；自愈失败轮从「整轮场景空转 + 判定误拒 + 原地重新实现」降为「1 次 env blocked 升级」。无配置新增、无 schema 变更、无数据迁移。