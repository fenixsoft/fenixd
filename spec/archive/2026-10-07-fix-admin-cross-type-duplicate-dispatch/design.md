## Context

在飞 Administrator run 互斥（fix-recovery-path-blockers D2/D2b）现有两个守卫变体：

- **宽口径** `AdminMonitor._has_active_admin_run_for_spec(spec)` → 模块级 `_spec_has_active_admin_run`：按 spec 单键聚合（任意 signal_type），仅即时唤起路径（`_handle_signal`，admin_monitor.py:3061）在用；
- **窄口径** `AdminMonitor._has_active_admin_run_for(spec, signal_type, exclude_run_id=None)`：按 `(spec, signal_type)` 精确匹配，三处在用——
  1. 周期摄取循环（约 :2083，`_ingest` STORED_SIGNAL_TYPES 分支）；
  2. 到期重派（约 :3320，`_retry_due_dispatch_failures`）；
  3. 孤儿重派（约 :3555，`_recover_orphaned_dispositions`，传 `exclude_run_id=rid`）。

2026-10-02 事故：escalation `verify_env_blocked`（即时链路派 run1，处置类型 `manual-intervention`）与 SIGNAL `verify_contract_missing`（摄取链路 3 分钟后派 run2）并行；摄取守卫以 `(spec, verify_contract_missing)` 过滤，run1 的 `manual-intervention` pending 记录不命中 → 放行重复派发。归档需求 `recovery-path-liveness` 中「既有带 signal_type 的版本语义不变、调用点保持不动」条款是这一残留口径的来源。

归并本体 `_merge_admin_runs(records, spec, signal_type, exclude_run_id)` 本就支持任意过滤组合，宽口径缺的只是 `exclude_run_id` 透传形参。

## Goals / Non-Goals

**Goals:**

- 同一 SPEC 的**全部**派发路径（即时唤起/周期摄取/到期重派/孤儿重派）互斥判定统一为 spec 单键口径（任意 signal_type 覆盖）。
- 孤儿重派的 `exclude_run_id`（排除正被孤儿处理的中断 run 自身）语义逐字保留。
- 三路径跳过时的既有副作用全部不变（见 D2）。

**Non-Goals:**

- 不改告警沉淀/节流/冷却语义（跨类型告警仍各自落 store、各自可重武装）。
- 不合并两条派发链路本身（escalation 即时链路与 SIGNAL 周期摄取链路的架构保持）。
- 不动 event_bus 侧既有互斥调用点（其已用宽口径）。

## Decisions

**D1 宽口径统一 + exclude_run_id 透传。** `_spec_has_active_admin_run(store, spec, logger=None, exclude_run_id=None)` 增可选形参，透传 `_merge_admin_runs`（归并本体既有参数，缺省 None 零迁移）；`AdminMonitor` 增对应薄封装或直接调用点传参。三处窄口径调用点全换宽口径：摄取循环与到期重派不传 exclude；孤儿重派传 `exclude_run_id=rid`。窄口径方法 `_has_active_admin_run_for` 调用点清零后删除（含三处注释的口径描述更正——摄取处注释现写「同 spec 同 signal_type」，到期重派处注释已自知危害是「另一信号类型或人工通道」却仍按型判定）。

**D2 跳过路径副作用逐字不变。** 摄取循环：跳过时 MUST NOT `mark_escalated`（源记录保持未消费、写入即待唤起语义保留）、说明性 `result="skipped"` 留痕按记录 id memo 去重每源仅一次；到期重派：跳过不 bump retry_count、下轮到期重评；孤儿重派：跳过回落原终结逻辑（interrupted 终结/升级人工），reschedule 语义不变。三处的 spec=None 哨兵惯例保持（daemon 级记录 spec 为空时跳过守卫判定——宽口径 spec=None 时 `_merge_admin_runs` 过滤被禁用，调用点沿用 `if spec and ...` 既有形态）。

**D3 fail-open 口径不变。** 判定异常按「无在飞」放行并记 WARNING（与既有两变体一致）——跨类型守卫变严不以可靠性为代价。

## Risks / Trade-offs

- **重派被过度抑制的窗口**：跨类型在飞期间，第二信号不再并行派发，须等在飞 run 结束后的下一巡检周期重武装（摄取/到期重派/孤儿重派三处均已内置该重评机制）。这是本次修复的目的本身，非回归。
- **归并函数签名扩展的兼容面**：`exclude_run_id` 为关键字可选、缺省 None，既有两个调用方（宽口径封装、孤儿扫描）零迁移。
