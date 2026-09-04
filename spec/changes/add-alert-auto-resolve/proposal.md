# Proposal: add-alert-auto-resolve

## Why

`.fenix/admin_alerts.json` 的告警只增不减：升级类告警（verify_fail_escalation、blocked_stuck 等）在底层问题实际解决后（spec 冻结后恢复、验证通过、到达终态）仍永久保持 `handled: False`，管理员视图被历史噪音淹没。2026-08-29 无人值守托管期间产生了 6 条此类已过时告警，需要人工比对 STATE.md 才能确认「不需要介入」——告警系统失去了「待办清单」的核心价值。

## What Changes

- 新增告警自动闭环机制：当告警的触发条件解除时（判定规则见 design），自动将关联告警标记为已解决（`handled: True` + `handled_at` 时间戳 + 解决原因标注），不伪造人工处理记录
- 告警写入时记录触发条件描述（结构化字段），供闭环判定复用
- 存量告警收尾：daemon 启动时对 `handled: False` 的历史告警执行一次回填判定，条件已解除的自动闭环，无法判定的保持原样并保留「历史遗留」语义
- 管理员视图（Dashboard admin 页）告警列表区分「待处理 / 已自动解决 / 已人工处理」，避免噪音上浮

## Capabilities

### New Capabilities
- `alert-lifecycle`: 告警生命周期闭环——告警与底层触发条件的状态联动（条件解除自动闭环、存量回填、视图分组）

### Modified Capabilities

（无——升级告警的产生逻辑散落在 improve-verify-adjudication / add-admin-activity-view 的实现中，无独立能力 spec 需要修改；本变更只增加闭环层，不改变告警的产生条件与格式）
