# 提案：fix-env-exemption-exit-reachability

## Why

env 豁免握手（verdict-env-exemption-handshake）的转人工出口在它最该生效的场景里**结构性不可达**。2026-10-03 potplayer-base/android-station-port 事故实证：judge 裁决「全部失败归 env、无产品 bug」→ verified 被握手拦截 → 转 inconclusive 自动重验；但到达 B7 升级（inconclusive_loop SIGNAL 唤醒 Administrator）需要 `_inconclusive_attempts >= 3`，而每轮重验因报告 timestamp 翻新必烧 1 次 judge 生命周期派发（`_judge_rerun_count`，总预算 5、唯一清零点 = verified）。该 spec 握手命中时预算已被修复轮/场景修复消耗至 5/5，第 6 次 gate 直接触发 judge_rerun_cap 冻结——人工收到的不是「请授予 env 豁免或修环境」的裁决请求，而是一个需要自行反推 env 层的死锁告警。轮内节流（`_JUDGE_ROUND_MAX_REAL_DISPATCHES=2`）也因每次重执行换新判定上下文键（report timestamp）而结构性失效，全程零拦截。

两个互不知情的预算（inconclusive 重验上限 × judge 生命周期硬上限）赛跑，后者总是先到顶：这是框架级死循环，不是单 spec 偶发。

## What Changes

1. **级二握手首次命中即升级**：`_handle_verdict_env_exemption_inconclusive` 不再走「先自动重验 3 次」——级二命中发生在 judge 已裁决全 env 之后，重验在环境不变时不产生新信息。首次命中即写 inconclusive_loop SIGNAL（复用既有 signal_type，保住握手守卫 `latest_resolved_disposition` 查询锚点不变）**并**经 `escalation_notifier` 发带 choices 的人工告警，spec 停在 implemented 暂停自动重验，等人工裁决。
2. **级一保留自愈重试 + 失败签名提前升级**：`_handle_env_blocked_inconclusive`（全 blocked-env 级联，面向瞬时环境抖动）保留自动重验，但上限 3→2；本轮失败签名（归一化）与 fail_history 上一轮完全一致 → 视为无新信息，跳过剩余重验直接升级。
3. **judge 预算隔离（防御纵深）**：握手进入 inconclusive 时置 STATE 旗标 `_in_inconclusive_reverify`；`_judge_dispatch_gate` 看到旗标把派发计入独立计数器 `_judge_inconclusive_dispatches`（自有上限 = `inconclusive_max_attempts`，可观测）而非 `_judge_rerun_count`；judge 申报非全 env 结论时清旗标恢复正计；verified 落定时与 `_judge_rerun_count` 一并清零。
4. **choices 三选接线（alert-resolve 闭环）**：注册 `inconclusive_loop` 裁决选项集——`grant_env_exemption`（新增动作：写 DISPOSITION 放行记录 + 重置验证，下轮 verified 合法生效带豁免回链）/ `manual_fixed_reverify`（人工已修环境·重置重验，复用既有动作）/ `abandon`（复用）。`execute_adjudication_choice` 补 `grant_env_exemption` 执行器。

## Capabilities

- `env-exemption-exit-reachability`：env 豁免握手/环境性失联的升级时序、judge 预算隔离与人工裁决选项闭环。

## Impact

- **改动面**：`core/pm_engine/verification/escalation.py`（两处 inconclusive 处理器 + 握手）、`core/pm_engine/verification/judge_gate.py`（gate 计数分流）、`core/pm_engine/verification/verdict_evidence.py`（verified 清零点扩展）、`core/dashboard/data/adjudication_choices.py`（注册表）、`core/dashboard/data/admin_actions.py`（执行器）、`core/state_machine.py`（字段常量）+ 单元测试。
- **不做什么**：不改握手守卫 fail-closed 语义（无放行记录绝不落 verified）；不动级一瞬态自愈设计本意；不给 judge 硬上限放水（预算隔离是分账，不是提额）；不改 `_env_exempt_disposition_is_stale` 时效锚点。
- **风险**：级二提前升级会让「env 或许可自愈」的 spec 少两次自动重试——由 choices 的 `manual_fixed_reverify`（人工修环境后重置重验）承接，且失败签名一致时重验本就无意义；新增 STATE 字段为增量，无迁移。
