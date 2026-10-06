# recovery-path-liveness 能力增量（fix-admin-cross-type-duplicate-dispatch）

> 「在飞 Administrator run 互斥」需求修订：互斥判定扩展到**全部**派发路径并统一为 spec 单键口径（任意 signal_type）；原「既有带 signal_type 的版本语义不变、调用点保持不动」条款废止。其余 Requirement 与原文各 Scenario 继续有效。

## MODIFIED Requirements

### Requirement: verifier 重验派发与在飞 Administrator run 互斥

`event_bus._recover_testing` 与 `admin_monitor` 孤儿复位路径派发 verifier（`handle_event("spec_implemented", ...)`）前，MUST 检查该 SPEC 是否存在在飞或待派发的 Administrator run；存在时 MUST 跳过本次重验派发并记日志，MUST NOT 起 verifier run。

判定 MUST 覆盖该 SPEC 的**任意** signal_type，且 MUST 覆盖该 SPEC 的**全部** Administrator 派发路径——即时唤起（`_handle_signal`）、周期摄取（STORED_SIGNAL_TYPES 摄取循环）、到期重派（`_retry_due_dispatch_failures`）、孤儿重派（`_recover_orphaned_dispositions`）——统一采用 spec 单键聚合口径（复用 `_merge_admin_runs` 单一归并本体：某 `admin_run_id` 组 `has_pending` 且无终结兄弟记录即在飞）。按 `(spec, signal_type)` 二元精确匹配的守卫口径 MUST NOT 用于任何派发路径：跨 signal_type 的在飞处置（如 `manual-intervention` 对 `verify_contract_missing`）正是 2026-10-02 cimbar-airgap-transfer 双重派发事故的直接缺口。孤儿重派的「排除正被孤儿处理的中断 run 自身」语义（`exclude_run_id`）MUST 保留——归并本体已支持，宽口径入口透传即可。窄口径守卫方法在调用点清零后 MUST 收敛删除（MUST NOT 留第二份口径并存漂移）。

互斥跳过时各路径的既有副作用 MUST 逐字保持：摄取循环不 `mark_escalated`（源记录保持未消费、写入即待唤起语义保留）、说明性 skipped 留痕每源记录仅一次；到期重派不 bump retry_count、下轮到期重评；孤儿重派回落原终结逻辑（interrupted 终结/升级人工）。daemon 级记录 spec 为空时跳过守卫判定的哨兵惯例保持。判定 MUST 采用 fail-open：admin 在飞判定本身异常时按「无在飞 admin」放行（与既有恢复路径容错语义一致），异常须记 WARNING。

#### Scenario: admin 处置在飞时跳过重验派发

- **WHEN** 某 testing SPEC 被判为无驱动（缺口 A 修复后），但同 SPEC 任一 signal_type 名下有 `has_pending` 且无终结兄弟记录的在飞 admin run（含 `orphaned_state` / `verify_env_blocked` / `manual-intervention` / `stuck`）
- **THEN** 恢复路径 MUST NOT 派发 verifier
- **AND** MUST 记 INFO/WARNING 日志说明「admin 处置在飞，跳过重验派发」

#### Scenario: admin 处置在飞时抑制重复唤起

- **WHEN** 某 SPEC 已有在飞 admin run，且该 SPEC 的新信号通过了既有节流判定（冷却窗已过期）
- **THEN** `_handle_signal` MUST NOT 唤起第二个 Administrator run
- **AND** MUST 记 INFO/WARNING 日志说明「已有在飞处置，跳过重复唤起」
- **AND** 该信号仍按既有沉淀/节流语义落 store（不丢痕）

#### Scenario: 周期摄取跨类型在飞时抑制重复派发

- **WHEN** 某 SPEC 已有 signal_type=`manual-intervention` 的在飞 admin run（pending 无终结兄弟），周期摄取循环捞到同 SPEC 未 escalated 的 SIGNAL `verify_contract_missing`
- **THEN** 摄取循环 MUST NOT 唤起第二个 Administrator run（按 spec 单键判定，跨类型命中）
- **AND** 源记录保持未消费（不 mark_escalated），在飞 run 结束后的下一巡检周期自然重评

#### Scenario: 到期重派跨类型在飞时抑制重派

- **WHEN** 某 SPEC 已有任意 signal_type 的在飞 admin run，一条到期重派记录（另一 signal_type）到达重派判定
- **THEN** 重派 MUST 跳过且 MUST NOT bump retry_count，下轮到期仍会重评

#### Scenario: 孤儿重派排除自身但命中跨类型在飞

- **WHEN** 孤儿扫描处理某中断 run（pending 记录自身）的重派，同 SPEC 另一 signal_type 存在在飞 admin run
- **THEN** 重派 MUST 被抑制（宽口径命中跨类型在飞；`exclude_run_id` 仅排除被处理的中断 run 自身，MUST NOT 排除其他在飞 run）
- **AND** WHEN 同 SPEC 无其他在飞 run 时，重派 MUST 照常执行（排除自身语义保持，中断 run 可被正常重派）

#### Scenario: admin 判定异常时 fail-open 放行

- **WHEN** admin 在飞判定抛出异常（如 store 不可读）
- **THEN** 恢复路径 MUST 记 WARNING 并继续派发 verifier（不因守卫故障阻断恢复）

#### Scenario: 无在飞 admin 时正常派发

- **WHEN** 该 SPEC 被判无驱动且无在飞 admin run
- **THEN** 恢复路径 MUST 照既有语义派发 verifier（`spec_implemented` → 入队）
