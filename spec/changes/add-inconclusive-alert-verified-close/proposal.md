# 提案：inconclusive 告警验证翻绿自动消解

## Why

`inconclusive_loop`（env 豁免握手族）告警被刻意排除在一切自动闭环通道外（保守缺省：豁免不得自我批准），但当环境事后被修复、验证轮真翻绿后，「豁免三选一」已成伪命题，告警却以「过期待决」形态永久滞留人工队列——实证：add-integration-test-env 的升级件 9e0403d0ac94，spec 已 pushed 而告警至今未处理（2026-11-07 事故，四条排查记录在案）。人工零价值地消费这类过期告警是纯浪费。

## What Changes

- `core/alert_lifecycle.py` 新增 spec 附着条件 `spec_verified`：关联 spec 状态到达 `verified`（或其后终态 `done`/`pushed`）时，未处理的 `inconclusive_loop` 告警自动收口。
- `_SIGNAL_CONDITIONS` 登记 `inconclusive_loop → spec_verified`（废除其「永不自动闭环」排除），`_recognized` 收录新条件；未来产生的该族条目自动携带 trigger。
- `BACKFILL_SIGNAL_TYPES` 收录 `inconclusive_loop`：存量无 trigger 条目（含在案滞留件）随启动回填按新条件收口。
- 注记文案附翻绿依据与状态变更时刻；自愈（安静窗口）注册表**保持排除** `inconclusive_loop` 不变——本条件族的收口证据是验证引擎裁决，不是安静时长。
- 收口语义定调（设计宪章级）：收口 =「豁免问题的前提已消失」，证据是验证引擎的 verified 判定（洗白门禁背书），**不信任任何 agent 的自述**，不替代人工裁决——修不好环境就永远不 verified、告警永不收口，fail-closed 由结构自带。

## Capabilities

- `specs/inconclusive-verified-autoclose/spec.md` — ADDED：inconclusive_loop 告警验证翻绿自动消解条件族

## Impact

- **受影响模块**：`core/alert_lifecycle.py`（单模块：条件常量、映射、识别门、判定分支、注记文案、回填集）；消费方 `core/admin_monitor.py` 周期扫描经既有 `find_resolvable` 零改动。
- **回归锚**：16:19 auto 重派反例（spec 离开停车态但问题仍在）必须保持不收口——新条件比既有 `spec_terminal_or_unblocked` 严格一档，只认「真翻绿」不认「离开 blocked」。
- **无 UI、无数据迁移、无配置键**；既有 close_cause 三分审计口径不变（本族走条件族通道，无 close_cause）。
- 直接效果：在案滞留件（9e0403d0ac94 等）随 daemon 重启首轮存量回填自动收口，无需人工标记。
