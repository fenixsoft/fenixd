# Proposal: admin-orphan-effect-generation-aware

## Why

admin_monitor 的孤儿处置生效核查（core/admin_monitor.py `_orphan_group_effect_evidence`，≈L7561）采用 STATE 单源判定：处置组终态后核对 spec 当前状态，凡 frozen=True 一律判「处置未生效」并升级人工。该判法不识别「处置已实际生效、其后状态被新一轮验证合法前移再冻结」的代际关系。2026-11-11 web-browser-client 实证（fenixd.log）：18:05:47Z 直通道复位成功（blocked→testing）→ 18:06Z round B 重验实际发生 → 18:20:27Z verified 洗白门禁再冻结（新代际）→ 19:10:23Z 旧处置组被判 not effective 升级人工。假告警 40e8d6fd4292 直链触发 2 次仲裁调查（1794425770/1794428094，合计约 24.3 万 tokens、约 17 分钟），另一条假告警 43a51528ef70 至今 handled=false 污染人工告警面；同文案孤儿升级历史另有 4 例（2026-11-09 ×3、11-11 ×1）。缺口在 HEAD 与运行面均在（admin_monitor.py 事件后零改动，daemon 11-13 已重启加载）。

## What Changes

- 生效核查代际感知：`_orphan_group_effect_evidence` 在 STATE 短路（frozen 即未生效）之前，先核查处置组完成时刻之后是否出现过指向该 spec 的「合法推进轨迹」——复用既有 gate transition 日志家族（解冻族 Transition 留痕，含轮转备份，行含时间戳与 channel），辅以处置组 created 时间戳作代际锚点；命中则判「已生效、被新代际取代」，旧处置组转记已消解并回链新代际信号，不再升级人工。
- 新代际信号开立：判「被新代际取代」时为当前 frozen 状态开新信号条目并携带旧处置组引用与轨迹证据行，保持升级链可追溯。
- fail-closed 边界零变化：未命中推进轨迹、或日志窗口缺失（轮转丢失）时，维持现行 fail-closed 升级语义——不因证据缺失放大豁免面。

## Capabilities

### New Capabilities

- `admin-disposition-effect-check`: 孤儿处置生效核查的代际感知判定——处置后推进轨迹核查、新代际取代消解与回链、fail-closed 边界。

### Modified Capabilities

（无——改动收敛在 admin_monitor 单文件与新增测试）

## Impact

- 代码：core/admin_monitor.py（生效核查判定扩展）；tests/test_admin_monitor_orphan_effect.py（新建，三态用例）。
- 兼容性：真未生效路径与日志缺失路径行为零变化（仍升级人工）；仅「处置后存在合法推进轨迹」一类误判被消解。
- 风险面：推进轨迹误判可能漏报真失效处置——以「轨迹必须晚于处置组完成时刻且为合法 gate transition」收紧，日志缺失 fail-closed 兜底。