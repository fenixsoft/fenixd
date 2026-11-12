# Design: consolidate-alerts-to-ops-page

## Context

概览页横幅（`AlertBanner.tsx`，挂载于 `pages/overview/index.tsx:226`）是当前告警的主消费面：展示未处理告警、内嵌 choices 裁决闭环、「清理所有事件」专属入口，并由概览页专属 SSE 告警管线（告警事件合帧 500ms + 30s 降级轮询 + 可见性门控）供数。运维页告警记录页签已具备完整展示与处置面（移动端行内裁决闭环齐备；桌面行为列表 + 报告入口 +「标记已处理」，历史上有意把桌面裁决收敛在概览横幅）。裁决告警写盘后由 `core/adjudication_narrative.py` 驱动 LLM 生成调查叙事（侧车补写 + 熔断器 + 三配置键 + 「调查生成中」占位）。用户决策：告警收敛运维页、概览回归纯概览、知情类不计数、叙事生成链彻底退役；运维页展示面保持不动；arbiter 车道及其调查报告不受影响。

## Goals / Non-Goals

**Goals:**
- 概览页告警面整体退役（组件、样式、专属数据管线全拆）。
- 「清理所有事件」迁至运维页告警记录页签（桌面 + 移动端），确认弹窗与后端语义不变。
- 运维菜单红点数字徽标：计数 = 未处理且 choices 非空；知情类/已处理/失效不计。
- 叙事生成链彻底退役：写侧三发射点拆 attach、配置三键退役、「调查生成中」占位退役；读侧侧车合并与 arbiter 报告渲染保留。

**Non-Goals:**
- 不改动运维页告警记录页签的既有展示形态（用户明确「已经实现，不用改动」，含桌面行不补裁决控件）。
- 不改动告警写侧降噪分级、escalation chain、arbiter 车道与告警生命周期（handled/supersede/auto-close）。
- 不迁移/清理历史侧车文件（保留只读合并 + 清理级联删除）。
- 不触碰 `/v2` 界面轨道（见 Risks）。

## Decisions

**D1 徽标数据源：复用 `GET /api/alerts`，客户端计数（而非新增 `/api/alerts/badge` 端点）。**
该端点已具备跨项目聚合、夹具过滤、conditional-get 缓存签名；告警量受降噪治理约束规模小。客户端 `count = alerts.filter(a => Array.isArray(a.choices) && a.choices.length > 0).length`，与运维页列表天然同源，避免第二真相源。备选（独立轻量端点）被否：多一个后端面 + 缓存签名接入成本，且需重复实现过滤口径。新 hook `useOpsAlertBadge` 复刻既有刷新惯例：SSE `alerts`/`admin_activities` 事件合帧 500ms、SSE 失效降级 30s 轮询、visibilitychange 门控（恢复可见补拉一次）、卸载清理。挂载于壳级（`app.tsx` 菜单装配处），随 `menuDataRender` 的运维项 `name` 包 antd `Badge`（`size="small"`、超 99 显示 99+）；`embed=1` 无菜单时组件自然不渲染。

**D2 横幅退役 = 删除，不是隐藏。**
删除 `AlertBanner.tsx`、`global.less` 中横幅专属样式、概览页告警管线（SSE 告警订阅/合帧句柄/降级轮询标记与定时器）。`getOverview` 30s 心跳与可见性门控保留（服务统计卡与台账）。守卫：概览页不得残留 `getAlerts`/`clearAllAlerts` 引用。

**D3 清理入口迁移：复用既有通道，文案逐字保留。**
告警记录页签桌面态放 AlertPanel 顶部操作栏（根因筛选右侧，danger 按钮），移动端放 MobileAlertPane 工具行。`modal.confirm` 文案沿用横幅现文案（全部项目 N 条未处理、不可撤销、AdminMonitor 不会对同一告警重新升级，danger 确认键）；执行走既有 `clearAllAlerts()`（`POST /api/alerts/clear`）→ 成功 message + `load()` 刷新（徽标经 SSE/轮询自然归零）。

**D4 叙事退役拆解：写侧拆除、判定迁移、读侧保留。**
- 发射点拆除：`family.py`（`_send_human_escalation_alert` 内后台补叙线程与 attach）、`mergeback.py`、`token_budget.py` 旁路 attach 全部移除；告警落盘路径零后台叙事线程。
- 让位判定迁移：现居 `adjudication_narrative.py`、由 `family.py:1688` 消费的「链头派发 vs 直达人工队列」判定迁至 escalation 链域（`escalation_chain` 模块或 family 就近），语义逐字保留（该判定与叙事无关，仅历史落在叙事模块）。
- 模块退役：`core/adjudication_narrative.py` 删除；读侧 `core/dashboard/data/admin_alerts.py` 保留侧车合并与清理级联删除，移除 `narrative_pending` 派生；`command_center.py` 收件箱定形去 `narrative_pending` 字段。
- 配置退役：三键自 config.template.yaml、config loader、设置页 SystemPanel 控件移除；loader 必须容忍存量用户 config 中的 narrative_* 残留键（未知键忽略，不报错）。
- 前端退役：`services/dashboard.ts` 的 `narrative_pending` 字段、`alert-shared.tsx` 的 `AlertNarrativePending` 占位及其渲染分支删除；`hasNarrativeReport`/`AlertReportButton`/narrative 渲染保留（服务历史侧车 + arbiter 报告）。

**D5 测试策略。**
生成链断言退役：`tests/test_adjudication_narrative.py` 生成/熔断/prompt/超时类用例删除；`tests/test_narrative_sidecar.py` 保留读侧合并与级联删除用例、删除生成类用例。新增断言：徽标计数口径（choices 非空 vs 知情类）、概览页无告警面、清理入口在告警页签可用、退役后写告警零 LLM 调用零新侧车。前端以既有 web 验证场景体系补徽标与清理入口场景。

**D6 文档与知识沉淀。**
`docs/help/06-governance.md` 叙事段改写为退役说明（历史报告可读）；退役结论 + 徽标能力投递 `spec/knowledge/_inbox/`。

## Risks / Trade-offs

- [活跃变更 redesign-dashboard-v2-ui 计划在 /v2/overview 重立告警横幅（内嵌裁决选择题）] → 本 SPEC 只约束既有 /overview 面；v2 轨道落地前须按本用户决策（告警收敛运维页）同步修订其 spec，否则两轨道语义漂移。advisory 记录，不阻塞本变更。
- [桌面裁决入口收窄：横幅退役后桌面可裁决面仅剩 spec 详情页 + 指挥中心收件箱] → 两者均既有入口；运维页桌面行按用户决策不改。若后续要求运维页桌面行补齐裁决控件，属独立增量。
- [徽标口径（choices 非空）与告警页签列表口径（全部未处理）不一致，可能被误读为 bug] → 有意区分（知情类不计数）；帮助文档写明。
- [存量 config 残留 narrative_* 键] → loader 未知键容忍（既有行为），模板注释删除即可；验收场景覆盖「残留键不报错」。
- [历史侧车残留 `.fenix/admin_alerts_narrative/`] → 读侧合并保留，历史报告继续可读；无迁移需求。
- [壳级 SSE 连接与页面级连接并存] → 现状 overview/activities 已并存多连接，服务端多客户端语义既有；壳级 hook 单连接复用既有 `STREAM_URL`。

## Migration Plan

单变更、无 schema/数据迁移；部署即生效，回滚 = revert 提交（历史侧车与 admin_alerts 数据双向兼容）。验收顺序：徽标计数口径 → 概览无告警面 → 清理入口迁移 → 叙事零派发与残留键容忍 → 既有告警/裁决/收件箱回归。

## Open Questions

无阻塞项。运维页桌面行是否补裁决控件已按用户指示定为不改（后续可选增量，不在本变更）。
