# chain-observability Spec（增量）

> 界面原型（UI 真相源）：`specs/redesign-chain-panel-ui/prototype/index.html`（含 vendor.js 与定稿截图）。界面视觉、布局、交互细节以 prototype/ 为准；本 spec 约束行为与数据语义。

## MODIFIED Requirements

### Requirement: Dashboard 自动化处置链视图

Dashboard 自动化处置链视图 SHALL 以项目既有 bento 卡片语言重绘（对齐 overview 页 `.ov-bento` 视觉规范：白底、1px 描边、12px 圆角、发丝行线、静态渲染无动画），以行卡形态取代表格呈现四区信息，视图顶部 SHALL 提供 5 磁贴统计行（链在办、待人工、上升件及近 24h 计数、签名水位及 Admin/Arbiter 顶格计数、签名关联上升占比）。

**链在办区**：每件在办 SHALL 行卡展示 phase 标签、spec、signal、已耗时、问题描述（同签名最近上升件摘要，2 行截断）、静态链进度条（Admin 已用/上限 → Arbiter 已用/上限 → 人工）、run 标识/入链时刻/chain_id；字段不可得时 MUST 显示「—」（禁止伪 0）。`chain_overview` SHALL 为在办件下发富化字段（问题描述摘要、Admin/Arbiter 已用计数与上限、run_id 尽力下发），联查数据 MUST fail-open 且保持单源（`admin_alerts.json`/arbiter ledger/链状态文件）。在办行 SHALL 可点击打开处置过程视图：run_id 可得时复用 agent 运行记录窗（AdminRunModal 形态），否则降级打开该签名最近上升件的详情抽屉。

**签名配额区**：SHALL 按 spec 分组呈现（组头=spec 名、项目、last_spec_status、签名数/上升数/待人工数聚合；组序按待人工数、上升数、最近出现降序），废除以 SPEC 作为每行日常标签的呈现；签名行 SHALL 展示 Admin/Arbiter 配额双芯片（正常灰/顶格橙/耗尽红静态条）与链上结果标签（待人工红/已收口绿/Admin 或 Arbiter 顶格橙/无上升件灰字）；granularity≠spec 的签名 SHALL 追加主体键/类型级标签。有上升件的信号名 SHALL 可点击，下钻打开该签名最近上升件的处置过程（待人工优先，否则最新）。

**人工队列区**：SHALL 置于统计行之后、其余三区之前；无待人工件时整卡 SHALL 隐藏。每项 SHALL 内嵌裁决面板：选择裁决项 Select（options 含 label 与 desc）、处置依据 Input（可选）、执行按钮（destructive 项 MUST 二次确认 Popconfirm）、标记已处理按钮，复用告警记录页既有裁决交互与 alert-resolve 闭环端点，执行成功后 SHALL 刷新队列。**纪律修订**：人工裁决入口由「收敛于告警记录页签」改为「人工队列内嵌为主入口，告警记录页签入口保留」；上升件全量列表仍 MUST 只读。

**上升件全量区**：SHALL 以行卡呈现（severity/signal/spec·项目/终点短标签/状态/时间 + 描述 2 行截断 + 链痕芯片行），SHALL 提供全部/待人工/已收口分段筛选；行点击 SHALL 打开详情抽屉（描述、证据、链痕 Timeline、建议处置、裁决选项只读预览）。

宿主页 chrome（页头 Tabs、项目筛选、SSE 横幅作用域）不改动；30s 轮询与「页签失活即卸载、轮询随卸载停止」纪律保持。

#### Scenario: 在办与队列可见

- **WHEN** 链上有 1 件在 Arbiter 处置、2 件排队
- **THEN** 处置链视图显示在办件（run 标识/已耗时）与队列深度，人工队列不含这三件

#### Scenario: spec=null 信号归组

- **WHEN** 蒸馏重试欠账类无 spec 信号入链
- **THEN** 该件按主体键在处置链视图可见（不在任何 SPEC 时间轴）

#### Scenario: 链在办行展示问题与进度并可打开处置过程

- **WHEN** 链上有 1 件 Admin 在办（同签名此前有上升件）
- **THEN** 在办行展示问题描述摘要与 Admin/Arbiter 进度条，点击行打开处置过程视图（run_id 可得为运行记录窗，否则该签名最近上升件详情抽屉）；run_id 不可得时 run 标识显示「—」

#### Scenario: 签名配额分组与信号名下钻

- **WHEN** 某 spec 下有 3 个签名、其中 1 个签名关联待人工上升件
- **THEN** 该 spec 为一个分组（组头含项目与聚合计数），仅该签名行出现「待人工」红标签且信号名可点击下钻；无上升件的签名行无标签

#### Scenario: 人工队列空则整卡隐藏

- **WHEN** 所有上升件均已收口（无待人工件）
- **THEN** 人工队列卡不渲染（统计行的待人工计数为 0，其余区块正常）

#### Scenario: 人工队列内嵌裁决执行

- **WHEN** 用户在人工队列某项选择非 destructive 裁决项并点击执行
- **THEN** 走 alert-resolve 闭环端点处置成功，队列刷新该项移除；选择 destructive 项时执行按钮先弹出二次确认

#### Scenario: 上升件行卡与详情抽屉

- **WHEN** 存在 18 条上升件（1 条待人工、17 条已收口）
- **THEN** 全量区行卡无换行溢出，分段筛选三种计数正确；点击任一行打开详情抽屉且抽屉内无裁决执行入口（只读）

#### Scenario: bento 风格一致性

- **WHEN** 打开处置链页签与 overview 页对比
- **THEN** 磁贴描边/圆角/阴影/字号阶与 bento 语言一致，界面以 prototype/ 为准
