# 告警调查叙事生成链已退役（consolidate-alerts-to-ops-page）

## 背景

告警面曾有「机械文案落盘 + 后台 LLM 补叙四段式调查叙事」双层形态（upgrade-narrative-to-investigation 引入，侧车 `.fenix/admin_alerts_narrative/<alert_id>.json`）。 SPEC `consolidate-alerts-to-ops-page` 立项裁决：叙事是可拆的纯增强——告警机械字段（description/evidence/recommended_action/choices/trigger）本身已可支撑裁决，LLM 补叙的时延/失败/熔断复杂度不值的；概览告警横幅整体退役、告警能力收敛到运维页。

## 结论（当前事实）

- 调查叙事**零生成**：告警发射点（`pm_engine._send_human_escalation_alert` 咽喉、token_budget、mergeback 旁路）全部零后台派发、零 LLM 调用；模块 `core/adjudication_narrative.py` 已删除，任何 import 即 ModuleNotFoundError。
- 让位判定语义迁居 `core/pm_engine/family.py` 的 `yielded_to_arbiter`（链头派发判定：链可用 ∧ 非黑名单 → True；与叙事无关，历史因落在叙事模块而同生共死）。
- 侧车辅助函数（write/load/delete_narrative_sidecars、SIDECAR_DIRNAME）迁居 `core/admin_store.py`。
- 配置三键 `admin.narrative_enabled`/`narrative_timeout_seconds`/`narrative_model` 退役（六处受管键登记面同步移除）；存量 config 残留键按未知键忽略不报错。
- 读侧保留：历史侧车与 Arbiter 处置报告（model=arbiter，升级路径原位写入）仍按 alert_id 合并渲染，「查看调查报告」按钮承载；`narrative_pending` 派生标记与「调查生成中」占位已退役。
- 运维入口：概览页告警横幅退役，未处理告警计数以红点徽标挂在运维菜单项上（`useOpsAlertBadge` hook）；「清理所有事件」入口迁至运维页告警记录页签（桌面操作栏 + 移动端工具行两形态）。

## 证据

- 实现分支 `fenix/consolidate-alerts-to-ops-page-1794445489`，SPEC `spec/changes/consolidate-alerts-to-ops-page/`（proposal/design/tasks + 7 delta specs）。
- 零后台派发契约测试 `tests/test_alert_background_dispatch.py`（判定矩阵/判定异常 fail-open/旁路零 attach/新告警无 narrative 字段无侧车）。
- 读侧收缩测试 `tests/test_narrative_sidecar.py`（合并形态/级联删除/原子写，生成类用例已移除）。
