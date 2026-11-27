# Proposal: consolidate-alerts-to-ops-page

## Why

告警信息当前主要呈现在概览页横幅（裁决类与知情类混排，「清理所有事件」专属入口），且每条裁决告警都会后台派 LLM 生成调查叙事，带来延迟、token 成本与「调查生成中」悬挂态。用户定调：告警归属运维域——人工裁决信息在运维页照旧显示，知情类只记录不计数，概览页回归纯数据概览，告警不再触发调查叙事生成。

## What Changes

- **概览页告警面整体退役**：移除 `<AlertBanner/>` 挂载与组件文件、概览页专属 SSE 告警刷新管线（告警事件合帧、降级轮询）及横幅样式；概览页回归统计卡 + 项目台账 + 错误告警。**BREAKING**（既有概览页展示面移除）。
- **调查叙事生成链彻底退役**：`_send_human_escalation_alert` 与旁路发射点（mergeback、token_budget）不再派 LLM 生成调查叙事；配置三键 `admin.narrative_enabled` / `narrative_timeout_seconds` / `narrative_model` 与设置页对应配置项退役；「调查生成中」占位与 `narrative_pending` 语义退役；按 signal_type 证据采集、四段结构生成、连续失败熔断器整体移除。**BREAKING**（生成行为与配置键移除）。历史侧车报告与 arbiter 车道写入 narrative 槽位的调查报告照常合并渲染（读侧合并、清理级联删除、「查看调查报告」入口保留）。arbiter 自主处置车道不受影响。
- **运维菜单红点数字徽标（新增）**：运维菜单项后显示红点+数字，计数口径=未处理且携带裁决 choices 的告警；知情类（无 choices）与已处理/失效告警不计入。
- **「清理所有事件」入口迁移**：按钮从概览横幅迁至运维页告警记录页签（桌面+移动端），确认弹窗文案与 `POST /api/alerts/clear` 语义不变。
- **指挥中心裁决收件箱响应定形收缩**：`narrative_pending` 字段退役（`narrative` 仅在历史侧车/arbiter 报告可得时携带）。

## Capabilities

### New Capabilities

- `ops-alert-badge`: 运维菜单红点数字徽标——计数口径（未处理且 choices 非空；知情类、已处理、已失效不计）、数据源与刷新（SSE 告警事件驱动 + 降级轮询 + 可见性门控）、零告警隐匿、embed 无菜单时自然豁免。

### Modified Capabilities

- `human-escalation-alerts`: 人工升级告警的用户可见消费面收敛——概览告警横幅退役；「清理所有事件」入口迁至运维页告警记录页签；展示唯一面=运维页（告警记录页签 + 菜单徽标）。
- `dashboard-overview`: 概览页展示面收缩——不再渲染告警信息面与告警操作入口，保留统计卡、项目台账与故障隔离降级。
- `adjudication-ui`: 裁决渲染面收缩——overview 横幅形态退役；裁决闭环保留于 spec 详情页告警区、运维页告警记录（移动端行内）、指挥中心收件箱。
- `adjudication-alert-narrative`: LLM 调查叙事生成链退役（生成派发/证据采集/熔断器/配置键/占位整体移除）；读侧侧车合并渲染保留（历史报告 + arbiter 报告）。
- `narrative-investigation-upgrade`: 升级版调查叙事四要求（证据采集/四段结构/异步补叙/连续失败熔断）随生成链整体 REMOVED；链头派发让位判定语义迁出叙事模块保留。
- `command-center-aggregation`: 裁决收件箱响应定形收缩——`narrative_pending` 字段退役。

## Impact

- **前端**：`core/dashboard/static/src/pages/overview/index.tsx`（拆横幅管线）、`pages/overview/components/AlertBanner.tsx`（删除）、`app.tsx`（菜单徽标）、`pages/activities/index.tsx`（清理按钮）、`components/alert-shared.tsx`（占位退役）、`services/dashboard.ts`（`narrative_pending` 字段退役）、`global.less`（横幅样式清理）。
- **后端**：`core/pm_engine/family.py`（发射点拆叙事，链头派发判定迁出 narrative 模块）、`core/worktree_manager/mergeback.py`、`core/agent_runner/token_budget.py`（旁路叙事拆除）、`core/adjudication_narrative.py`（模块退役）、`core/dashboard/data/admin_alerts.py`（读侧 pending 派生移除，侧车合并与级联删除保留）、`core/dashboard/data/command_center.py`（收件箱定形）、`core/config.py` + `.fenix/config.template.yaml`（三键退役）、设置页 SystemPanel。
- **测试**：`tests/test_adjudication_narrative.py`、`tests/test_narrative_sidecar.py`（生成类断言退役、读侧合并/级联保留）+ 新增徽标计数、横幅退役、叙事零派发断言。
- **文档/知识**：`docs/help/06-governance.md` 叙事段改写、knowledge `_inbox` 投递退役结论。
- **既有用户配置兼容**：已携带 `narrative_*` 键的 config 须被 loader 容忍（未知键忽略），不报错。
- **活跃变更重叠提示（advisory）**：`redesign-command-center-ledger`（proposal 阶段）与 `command-center-aggregation` delta 存在 scope 重叠风险，落地时以本文档定形为准。
