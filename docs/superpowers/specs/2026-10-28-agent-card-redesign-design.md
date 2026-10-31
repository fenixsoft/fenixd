# SPEC 指挥中心 Agent 卡片重设计（Agent Card Redesign）设计文档

日期：2026-10-28
状态：原型已获用户定稿（10-28 会话确认「按此定稿」），本文档为定稿记录

## 1. 背景与意图

指挥中心「组织总览」屏（`core/dashboard/static/src/pages/command-center/OrgGrid.tsx` 的 `LaneCard`）现有卡片过于简陋：纯文本行平铺（车道名 + 三个小字指标 + sparkline + 时间），无视觉层级、无「正在做什么」的可读位，与指挥中心大屏定位不匹配。

参照 Ability AI Trinity（https://www.ability.ai/trinity）的 Agent 卡片结构重设计。HTML 原型已交付并获用户逐轮确认（原型存档：`.history/agent-card-prototype.html`，截图 `.history/agent-card-proto-shot2.png`），定稿要点：字体 +1 号、卡宽 310px、@ant-design/icons 图标（用户明确否决 emoji 与新增图标库）。

Trinity 卡片灵魂 = 「实时活动行」；本项目数据面天然对应：working 车道的 `attributable.spec` 即「正在做什么」。

## 2. 目标 / 非目标 / 反目标

### 目标

1. 重构 `LaneCard` 为五段结构（详见 §3），对齐定稿原型。
2. 每车道固定图标徽章，用项目既有依赖 `@ant-design/icons`（6.3.2，`package.json` 已有），working 蓝色 / idle 灰色。
3. 保留现有全部交互语义：working 且 `attributable` 非空才可点击钻取 `/projects/:project/:spec`，不可得禁用点击。
4. 14 日 sparkline、最近活动时间等现有信息全部保留（只是换位置）。

### 非目标（本轮不做）

- 后端零改动：`/api/command-center/org` 现有字段（`lane/zone/status/runs_today/success_rate_7d/cost_7d/activity_14d/last_activity_ts/attributable`）完全够用，不加字段不加端点。
- 不改汇报线 `ReportingLines`、不改分区标题形态、不改其余三屏（PipelineBoard/ExecutionLedger/AdjudicationInbox）。
- 不做动画（见 §8 红线）。
- 移动端不做专项适配（`flex-wrap` 自然换行即可，与既有大屏口径一致）。

### 反目标（出现即算失败）

- 引入新图标库依赖（lucide/tabler/phosphor 等）或 emoji 图标——用户已明确否决。
- 指标 null 显示 0（「口径不可得」与 0 语义不同，既有红线）；反向：真实 0 显示成「—」同样错误。
- 卡片内出现 CSS animation/transition/SMIL。
- `shared.ts` 引入 react/antd import（该文件被 `tests/commandCenter.test.mjs` 以 node --test type-stripping 直载，保持纯函数零依赖）。

## 3. 卡片结构规格（定稿）

自上而下五段，卡宽 310px（原 190px minWidth），圆角 10px，内边距 13px 14px 11px，段间距 10px，背景 `rgba(10,30,56,0.55)`、边框 `PANEL_BORDER`：

```
┌──────────────────────────────────────┐
│ [图标徽章38×38] 车道名15px/600  ●状态 │  ← 头行
│                lane id 等宽12px 灰    │
│ ▶ spec-name（绿底衬/accent等宽）       │  ← 活动行（灵魂）
│   18       92.3%      $18.02         │  ← 三格指标
│ 今日 run  7日成功率   成本·7日        │
│ ▁▃▅▂▁▃▄▆▃▂▄▅▃▂      最近活动 10-28 14:32│  ← 页脚
└──────────────────────────────────────┘
```

1. **头行**：图标徽章 38×38、圆角 10、内含 18px 图标，working 态 `accent(#40a9ff)` 图标 + 蓝渐变底 + 蓝细边；idle 态 `#7f9cba` 图标 + 灰渐变底 + 灰细边。右侧：车道中文名（`laneLabel`，15px/600）+ 状态徽标（working：绿点 +「运行中」`#52c41a`；idle：灰点 +「空闲」`#5b708c`，12px，纯静态无脉冲）；下行 lane id（等宽 12px `TEXT_SUB`）。
2. **活动行**（状态三分，纯函数可测）：
   - working + attributable：绿弱底（`rgba(82,196,26,0.12)`）圆角 6，内容 `▶ ` + spec 名（accent 等宽 12.5px，超长 ellipsis，`title` 悬停全名）；
   - working 无归属：同底色，内容 `▶ 执行中`；
   - idle：透明底 + 灰虚线边框（`rgba(91,112,140,0.35)`），内容「待命 · 等待信号」（`TEXT_SUB` 12px）。
3. **三格指标**（等分三列，列间 1px 竖分隔 `rgba(59,110,165,0.25)` + 12px 左间距）：数值 18px/600 `tabular-nums` + 标签 11.5px `TEXT_SUB`。「今日 run」（整数，`fmtMetric`）/「7 日成功率」（`fmtRate`）/「成本 · 7 日」（`fmtUsd`）。null 一律「—」，0 保留。
4. **页脚**：14 日 sparkline（复用 `sparklineHeights`，98×18，柱宽 5 间距 2，有值 `#40a9ff` 无值 `PANEL_BORDER`）左，最近活动 `fmtShortTs`（12px `TEXT_SUB`）右，底部对齐。
5. **可点击态**：`cursor:pointer` + hover 背景提亮（`rgba(16,42,78,0.65)`）+ 边框提亮（`rgba(94,150,210,0.7)`），无 transition；不可点击态维持默认。

## 4. 车道图标映射（@ant-design/icons 定稿表）

| lane | 图标组件 | lane | 图标组件 |
|---|---|---|---|
| planner | CompassOutlined | judge | FileDoneOutlined |
| spec-review | FileSearchOutlined | testing | ExperimentOutlined |
| implementer | CodeOutlined | administrator | SettingOutlined |
| code-fix | BugOutlined | self-review | EyeOutlined |
| code-review | AuditOutlined | scan | ScanOutlined |
| ocr | FileTextOutlined | | |

映射表放 `shared.ts`（lane → 组件引用的对象字面量）；未知 lane 回退一个安全图标（builder 裁量，如 `FileUnknownOutlined` 一类存在即可）。表中组件名均已核实存在于 node_modules 6.3.2。

## 5. 状态与交互（不变量）

- 钻取条件与目标完全不变：`status==='working' && attributable` → `history.push(/projects/:project/:spec)`。
- 状态徽标口径不变（working/idle 二值）。
- 数据读取不变：仍走 `commandCenterOrg()` + `useScreenResource`，轮询行为零改动。

## 6. 技术选型（我的裁量）

- 图标：`@ant-design/icons` 具名组件直接 import（项目既有依赖，与全站 antd 图标同源风格）。
- 实现：React inline style 对象（对齐 OrgGrid 现有零 CSS 文件风格），不新建 .css/.less。
- 活动行状态三分做成 `shared.ts` 纯函数（如 `activityLineState(card) → {kind:'spec'|'running'|'rest', spec?}`），配套 node --test 用例进 `tests/commandCenter.test.mjs`。
- 色值新增派生色（绿弱底/灰虚线/hover 提亮等）以常量形式进 `shared.ts`，与既有四色同源管理。

## 7. 约束（红线，违反任一即返工）

1. **静态渲染红线**：卡片内禁 CSS animation/transition/SMIL（specs「静态渲染红线」既有约定，hover 用纯色切换）。
2. **null 口径红线**：指标 null → 「—」，数值 0 原样显示。
3. **shared.ts 纯度红线**：禁 react/antd import（node --test type-stripping 直载约束）。
4. **零后端改动**：不碰 `/api/command-center/org` 与任何 core/ 代码。
5. 色系沿用大屏四色单源（BG/PANEL_BORDER/TEXT_MAIN/TEXT_SUB），新增派生色不得脱离该色系。

## 8. 验收 Scenario（数值/分支以本节为准）

- Scenario: working+attributable 卡渲染 — Given `status='working'`、`attributable={project:'fenixd',spec:'fix-admin-choice-payload'}` When 渲染 Then 活动行显示 `▶ fix-admin-choice-payload`（accent 等宽）、整卡可点击、hover 提亮、图标蓝色 CodeOutlined、状态徽标绿「运行中」。
- Scenario: working 无归属 — Given `status='working'`、`attributable=null` Then 活动行「▶ 执行中」、整卡不可点击（cursor 默认）、不跳转。
- Scenario: idle 卡 — Given `status='idle'`、`success_rate_7d=null`、`cost_7d=null` Then 图标灰色、活动行虚线框「待命 · 等待信号」、指标显示 `0`「—」「—」（今日 run 为 0 时显示 0）、状态徽标灰「空闲」。
- Scenario: 静态红线 — Then 卡片 DOM 内无 `animation`、`transition` 属性字样。
- Scenario: 未知 lane — Given `lane='new-lane'`（花名册外观测落「其他」分区）Then 卡片正常渲染、图标走回退、`laneLabel` 原样透出。

## 9. 留给 builder 的部分

- `LaneCard` JSX 具体写法与样式对象组织（对齐文件内现有 inline style 风格与中文注释密度）。
- 回退图标具体选型（存在性需自行核实 6.3.2）。
- `activityLineState` 函数签名微调与测试用例展开（覆盖 §8 全部 Scenario）。
- 里程碑拆分（单轮可实现，预估仅 OrgGrid.tsx + shared.ts + 测试三文件）。
