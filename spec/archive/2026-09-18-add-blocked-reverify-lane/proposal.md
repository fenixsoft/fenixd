# 提案：add-blocked-reverify-lane（BLOCKED 重验直通道 + env 阻塞生命周期累计）

## Why

add-proxy-tunnel 三分支三复跑事故（fenix-server 项目 2026-09-10，单 SPEC 累计真实成本 $34.91，其中纯浪费约 $18.5/53%）解剖出两个系统性缺口：

1. **根因 A — blocked→ready 复位后必然全量重实现**：`VALID_TRANSITIONS` 中 BLOCKED 唯一出路是 READY（core/state_machine.py:127），而 READY 的派发逻辑无条件入队 implementer（core/pm_engine/engine.py:238 `_on_spec_ready` → `_enqueue(spec_name, agent_type)`，不查 implementer_run/branch 是否已存在）。admin 处置提示词写着「处置完成后触发该 spec 重新验证」，但它唯一可用的杠杆（status=ready）触发的是完整实现轮。事故中 impl-2/impl-3 两轮（$2.37、合计 46 个 agent 轮次）进场即发现 tasks.md 全勾、零代码可写，只做「复跑核验 + 写 run-result」——空跑是状态机设计的必然，不是 agent 失误。而重验本身极便宜：同事故第 2/3 轮验证引擎各 14 秒，且有场景冻结复用与跨轮裁决缓存兜底。
2. **根因 D — `_env_block_rounds` 复位清零架空冻结门**：「连续 2 轮 env 阻塞→冻结转人工」限流（core/pm_engine/verification.py `_escalate_env_blocked`，阈值判定于 `frozen = rounds >= 2`）是连击（streak）语义：admin 处置复位 blocked→ready 时把 `_env_block_rounds` 清零（事故中 admin-1/admin-2 均如此），下一轮阻塞又从 1 起算——只要每次 admin 都「成功」复位，冻结转人工在 spec 生命周期内永不可达，烧钱循环无人叫停。用户已拍板：admin 复位不再清零，仅验证通过（verified 落定）或人工解冻清零；阈值维持 2 不动（第 2 次即冻结，admin 修复机会只有一次，重验很便宜、早冻结早止损）。

## What Changes

- **BLOCKED→TESTING 重验直通道（GATE_TRANSITIONS 逃生门模式复用）**：环境阻塞类冻结（`_escalate_env_blocked` 写入的 blocked）在实现分支已 merge（implementer_run/branch 存在且实现产物在主树）的前提下，admin 处置完成复位时直接回 testing 重新派发 verifier，不再经由 ready→implementing 全量重实现。转换以 `GATE_TRANSITIONS` 白名单扩展（BLOCKED: [TESTING]）+ 专用守卫方法落地，人工路径 `transition()` 仍受 `VALID_TRANSITIONS` 约束不得绕过。复位判定条件：spec 有 `tester_run` 历史（曾进入验证）或 branch 已 merge——两者皆无（实现阶段冻结）仍走既有 ready→implementing。
- **admin 处置上下文注入与复位动作收敛**：`verify_env_blocked` 自动呼叫 admin 的提示词明确「处置完成后由框架自动触发重验证（branch 已合并时），你只需要修复环境、不要手动 reset spec 状态」——把「复位」从 admin 的自由裁量收敛为框架在处置收尾（disposition result=resolved 消费点）的机械动作，admin 直接操作 StateMachine 的旁路写法失去必要性。
- **`_env_block_rounds` 生命周期累计语义**：admin 处置复位、daemon 恢复等中间转换不再清零；唯一清零点=验证通过（verified 落定，与 `_verify_fail_rounds` 的「PASS 唯一归零点」同语义对齐）与人工 `unfreeze_spec`。同时把该字段登记进 state_machine 的显式字段名单（IMPL_RUN_BUDGET_USED_FIELD 同款常量），消除漂移风险。

## Capabilities

### New Capabilities
- `blocked-reverify-gate`: BLOCKED→TESTING 重验直通道——env 阻塞冻结的 spec 在实现分支已合并前提下由框架自动门禁转换回 testing 重验，跳过全量重实现；实现阶段冻结（无 branch/未合并）保持既有 ready 通道。

### Modified Capabilities
<!-- 无归档能力 requirement 级修改：verify-environment-sanity-gate（环境健全性门，
     归档）的 env 判定与升级语义不变；本 SPEC 只改升级后的复位路径与计数清零点。
     add-verdict-credibility-gate 的 inconclusive 升级通道不受影响（其消费
     _inconclusive_attempts，与本 SPEC 的 _env_block_rounds 字段正交）。 -->

## Impact

- **代码**：`core/state_machine.py`（GATE_TRANSITIONS 扩展 + transition_gate 守卫复用 + 字段常量登记）、`core/pm_engine/verification.py`（`_escalate_env_blocked` 复位路径决策、verified 清零点对齐）、`core/admin_monitor.py`（处置收尾消费点接入重验直通道 + 提示词修订）、`core/event_bus.py`（`_recover_ready` 对 blocked-reverify 挂起态的感知）。
- **影响的行为**：env 阻塞后 admin 处置完成的 spec 流向（testing 直达 vs ready 重实现）；`_env_block_rounds` 在 spec 生命周期内的累计与清零时机；admin 提示词中的处置边界。
- **不受影响**：product-bug/bug-found 打回修复通道（testing→bug-found→implementing 既有语义）；实现阶段熔断（implementing→blocked→ready 重试）；inconclusive 暂停通道；fast-track 车道（无 verifier 车道，不经过本通道）。
- **风险**：重验直通道可能在环境未真正修复时快速再次阻塞——这正是 `_env_block_rounds` 生命周期累计的职责：第 2 次阻塞即冻结转人工，止损窗口比现状（无限 admin 循环）显著收窄。状态机白名单扩展需回归验证人工路径仍被拒（D7 既有测试模式可复用）。
