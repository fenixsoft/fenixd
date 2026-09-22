## Why

手动唤起 Administrator 的通道（Dashboard「唤起」/ CLI）在 daemon 消费请求文件时把信号 `signal_type` 压平成 `manual-intervention`（`fenixd.py` `_check_admin_invoke_requests`），而处置收尾自动复位的判定门是 `sig_type ∈ DISPOSITION_AUTO_RESET_SIGNAL_TYPES`（env 阻塞族 + blocked_stuck，`core/admin_monitor.py`）。压平导致：人工唤起处置即使成功（result=resolved）也永不命中自动复位，spec 悬置 blocked 等二次人工（fix-verify-serving-disk-reclaim 事故 2026-09-18 实证：环境已修复但 spec 卡 blocked 18 分钟，处置记录点名该缺口）。

## What Changes

- daemon 消费 admin invoke 请求文件时，反查该 spec 最近一条未处置信号的 `signal_type`，以独立字段 `underlying_signal_type` 随信号透传；查不到时缺省 None
- 处置收尾自动复位判定门扩展：`signal_type` 或 `underlying_signal_type` 命中 `DISPOSITION_AUTO_RESET_SIGNAL_TYPES` 即可触发复位
- 信号顶层 `signal_type` 保持 `manual-intervention` 不变——store 记录、节流锚点、admin 活动区展示零回归

## Capabilities

### New Capabilities
- `manual-invoke-signal-passthrough`: 手动唤起信号透传底层 signal_type 与复位判定门扩展的行为契约

### Modified Capabilities

## Impact

- `fenixd.py`：`_check_admin_invoke_requests` 反查与透传
- `core/admin_monitor.py`：`_reset_env_blocked_after_disposition` 消费门扩展（含其调用点前置检查）
- `core/dashboard/` 与 CLI 唤起入口零改动（透传在 daemon 侧完成，无需前端带参）
