# Proposal: redesign-chain-panel-ui

## Why

运维页处置链页签与 Dashboard 其他页的 bento 卡片视觉语言割裂；链在办/签名配额/人工队列/上升件全量四区用 antd 表格挤压数百字符的处置文本，造成大量换行与显示不全。链在办看不出处置的具体问题与进度；签名配额全部由 SPEC 出发导致 SPEC 标签无意义、全部显示「余量可用」，而实际存在大量处置失败上升到人工的件，配额区完全不可见。已经三轮浏览器原型批注定稿并经用户批准（界面原型/UI 真相源：`specs/redesign-chain-panel-ui/prototype/index.html`），确认后立项修改。

## What Changes

- **处置链页签整体重绘为 bento 卡片风格**（对齐 `.ov-bento` 既有语言：白底、1px #eef2f7 描边、12px 圆角、发丝行线、静态渲染），废除 4 个 antd 表格，改为行卡形态（不换行、2 行 clamp、链痕芯片行）。
- **新增 5 磁贴统计行**：链在办（Admin/Arbiter 分计）、待人工、上升件（含近 24h）、签名水位（含 Admin/Arbiter 顶格计数）、签名关联上升（占水位比例）。
- **链在办卡**：行卡展示 phase 标签、spec、signal、已耗时、问题描述（2 行 clamp）、静态链进度条（Admin n/N → Arbiter n/N → 人工）、run/入链时刻/chain_id；行可点击打开处置过程视图（复用 agent 运行记录窗 AdminRunModal 形态）。为此后端 `chain_overview` 在办件下发富化字段（问题描述摘要、Admin/Arbiter 已用计数、run_id 尽力下发）。
- **签名配额卡**：按 spec 分组列表，废除无意义的 SPEC 日常标签（SPEC 名升为组头，承载项目、last_spec_status、签名数/上升数/待人工数聚合）；签名行展示 Admin/Arbiter 配额双芯片（正常灰/顶格橙/耗尽红静态条）与链上结果标签（待人工红/已收口绿/顶格橙）；granularity≠spec 时才显示主体键/类型级标签；有上升件的信号名可点击，下钻到该签名最近上升件的处置过程。
- **人工队列卡置首**（在统计行之后、链在办/签名配额/上升件之前），无待人工件时整卡隐藏；每项内嵌裁决面板（选择裁决项 Select + 处置依据 Input + 执行按钮（destructive 项二次确认 Popconfirm）+ 标记已处理），复用 overview 告警页既有裁决交互与 alert-resolve 闭环端点。**BREAKING（纪律级）**：修改既有「处置链视图只读」纪律——人工裁决入口由「收敛于告警记录页签」改为「人工队列内嵌为主入口，告警记录页签入口保留」；上升件全量列表仍保持只读。
- **上升件全量卡**：行卡 + 全部/待人工/已收口分段筛选；行点击打开详情抽屉（描述、证据、链痕 Timeline、建议处置、裁决选项只读预览）。
- 宿主页 chrome（页头 Tabs、项目筛选、SSE 横幅行为、30s 轮询）不改动；数据保持单源（`admin_alerts.json` + arbiter ledger + 链状态文件），不引入平行真相源。
- 知识页 `spec/knowledge/domains/admin-ops/chain-observability.md` 的只读纪律条款随本变更同步修订。

## Capabilities

### New Capabilities

（无——本变更全部落在既有能力的需求修订上。）

### Modified Capabilities

- `chain-observability`：「Dashboard 自动化处置链视图」Requirement 重写——bento 视觉语言、行卡形态替代表格、链在办信息富化与处置过程弹窗、签名配额 spec 分组与信号名下钻、人工队列置首/空隐藏/内嵌裁决入口（只读纪律修订为分层只读）、上升件行卡与详情抽屉。

## Impact

- `core/dashboard/static/src/pages/activities/components/ChainPanel.tsx` — 视图主体重写。
- `core/dashboard/static/src/services/dashboard.ts` — ChainInFlightItem 等类型投影扩展。
- `core/dashboard/data/admin_alerts.py` — `chain_overview` 在办件富化字段下发。
- `spec/knowledge/domains/admin-ops/chain-observability.md` — 只读纪律条款修订。
- 无状态机/调度行为改动；不新增依赖；移动端既有形态不劣化。
