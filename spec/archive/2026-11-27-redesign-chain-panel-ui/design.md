# Design: redesign-chain-panel-ui

## Context

处置链页签现实现为 `core/dashboard/static/src/pages/activities/components/ChainPanel.tsx`（421 行，5 个普通 antd Card 统计 + 4 个表格：链在办/配额水位/人工队列/上升件全量），宿主 `activities/index.tsx` 持有三页签与项目筛选。数据链：`core/dashboard/data/admin_alerts.py:266 chain_overview` 聚合 `admin_alerts.json` + arbiter ledger + 链状态文件（`core/pm_engine/escalation_chain.py:139` 在办件仅 `{chain_id,signature,spec,phase,started_at}` 五字段），前端投影 `services/dashboard.ts:692-754`。

三轮浏览器原型批注已定稿并入库：`specs/redesign-chain-panel-ui/prototype/index.html`（UI 真相源）。用户批准：人工队列置首、空隐藏、内嵌裁决入口；链在办可点击看处置过程（复用 agent 运行记录窗）；配额按 spec 分组、信号名下钻；上升件行卡+抽屉。这推翻了知识页 `admin-ops/chain-observability.md` L19 的「视图只读」纪律（人工裁决入口收敛于告警记录页签），本变更同步修订该纪律为分层只读（人工队列可裁决、全量列表只读）。

## Goals / Non-Goals

**Goals:**
- 处置链页签视觉对齐 bento 语言（`.ov-bento`：白底/1px #eef2f7/12px 圆角/发丝行线/DSH token 字号阶 11-28/数值 tabular-nums/null 显「—」/禁 CSS 动画），消除表格换行灾难。
- 链在办富化：问题描述摘要 + Admin/Arbiter 进度 + 处置过程弹窗。
- 配额语义重表达：spec 分组 + 配额双芯片状态色（正常/顶格/耗尽）+ 链上结果标签 + 信号名下钻。
- 人工队列成为人工裁决主入口（复用既有 alert-resolve 闭环），空队列整卡隐藏。
- 知识纪律随变更修订，不留双源。

**Non-Goals:**
- 不改宿主 chrome（页头 Tabs/项目筛选/SSE 横幅作用域）、不改 30s 轮询机制、不做后端状态机/调度行为改动。
- 不改告警记录页签的既有裁决交互（保留为第二入口）。
- 不引入新依赖、不建平行真相源。

## Decisions

- **D1 行卡替代表格**：四区全部改为行卡（信息分三行：标识行/描述 clamp/链痕芯片行），描述与长文本 2 行 -webkit-line-clamp。理由：上升件 description 48-303 字符、处置链痕数百字符，表格单元格无法承载（现状换行灾难实证）；原型已验证行卡在 1600px 与移动宽度下无溢出。备选 antd Table + tooltip：被原型评审否决（信息仍不可扫读）。
- **D2 在办富化走后端下发**：`chain_overview` 组装 in_flight 时联查同签名最近上升件（problem 摘要=description 截断）与签名配额/escalation.chain（admin_attempts_used/arbiter_rulings/caps），run_id 从链上下文尽力提取，不可得置 null（前端显「—」）。理由：前端自行联查会造成 N×M 请求与双源风险；后端已有全部数据在手。备选仅前端联查：放弃（脆弱且违反单源纪律）。
- **D3 处置过程视图复用 AdminRunModal**：在办行点击→run_id 可得时复用 `AdminRunModal`（`activities/components/AdminRunModal.tsx`，80vw/72vh 流式转录窗）；run_id 不可得或该在办无 run 时降级打开该签名最近上升件的详情抽屉（链痕 Timeline 已可回答「发生了什么」）。理由：零新组件、与既有心智一致。
- **D4 裁决面板复用告警裁决件**：人工队列内嵌面板复用 `useAlertAdjudication`（choices 下拉+处置依据+执行/destructive Popconfirm+标记已处理）与 alert-resolve 端点；成功后走既有刷新链路。理由：同一闭环端点避免第二套裁决真相；原型中的静态演示面板仅为形态参考。
- **D5 配额分组与状态色**：spec 分组组序按待人工数→上升数→last_seen 降序；芯片填充色 #81858c 正常/#f59e0b 顶格/#ec1313 耗尽；链上结果标签待人工红/已收口绿/顶格橙。理由：把「处置失败上升到人工」从不可见变为第一视觉焦点（用户核心痛点）。
- **D6 纪律修订程序**：`spec/knowledge/domains/admin-ops/chain-observability.md` L16/L19/L25 随本变更修订（人工队列内嵌裁决为主入口、全量列表只读、来源注释补本变更），与代码同变更落地，杜绝文档-实现漂移。

## Risks / Trade-offs

- 链状态文件仅五字段，run_id 可能系统性不可得→进度条以 escalation 联查计数兜底，run 标识显「—」（不伪 0）。
- 内嵌裁决引入写路径到只读视图：以「人工队列区为唯一写入口」约束，全量列表与抽屉保持只读，评审时按此边界核验。
- 行卡在极窄移动端的信息密度：沿用现 ChainPanel isMobile 分支经验，行卡栅格降级单列（原型已含窄宽验证）。
- 后端富化增加 chain_overview 计算量（联查同签名 escalation）：数据量级为个位数在办×数十签名，30s 轮询下无压力；联查 fail-open，缺数据降级不阻断视图。
