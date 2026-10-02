## Why

2026-10-02 potplayer-base 项目 `cimbar-airgap-transfer` 实证一起双重派发：同一次验证环境阻塞（verify.yaml 纯模板致契约轻量自证失败）同时落了两条 store 记录——escalation `verify_env_blocked` 经即时链路秒级派发 Administrator（处置类型 `manual-intervention`），SIGNAL `verify_contract_missing` 被 5 分钟周期摄取链路在下个 tick 再次派发（处置类型 `verify_contract_missing`）——两个 Administrator run 并行处置同一 SPEC。根因：摄取/重派路径的在飞互斥守卫按 `(spec, signal_type)` 二元精确匹配（`_has_active_admin_run_for`），跨 signal_type 的在飞 run 识别不到；而 fix-recovery-path-blockers D2 为此专门加的宽口径 `_spec_has_active_admin_run`（spec 单键聚合）只有即时链路在用。

## What Changes

- `core/admin_monitor.py` 三处窄口径守卫调用点统一换宽口径：周期摄取循环（`_ingest` STORED_SIGNAL_TYPES 分支）、到期重派（`_retry_due_dispatch_failures`）、孤儿重派（`_recover_orphaned_dispositions`）。
- 宽口径模块级 `_spec_has_active_admin_run` 增加 `exclude_run_id` 可选形参（透传 `_merge_admin_runs` 既有本体，单实现不漂移），孤儿重派的「排除被处理的中断 run 自身」语义保持。
- 窄口径方法 `_has_active_admin_run_for` 在调用点清零后收敛删除（注释同步更正）。
- 跨 signal_type 互斥回归用例补齐（三路径各一）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `recovery-path-liveness`: 「在飞 Administrator run 互斥」需求修订——互斥判定 MUST 覆盖**全部**派发路径（即时唤起/周期摄取/到期重派/孤儿重派）且按 spec 单键聚合（任意 signal_type）；原「既有带 signal_type 的版本语义不变、调用点保持不动」条款废止（2026-10-02 事故证明该残留口径正是跨类型重复派发缺口）。

## Impact

- `core/admin_monitor.py`（守卫调用点与归并函数签名、方法删除）
- `tests/test_admin.py`（跨类型互斥用例）
- 行为面：守卫变严——跨类型场景下第二派发被跳过，源记录保持未消费、在飞 run 结束后下一巡检周期自然重评（三路径的既有重武装机制不变）；无接口变更、无数据迁移。
