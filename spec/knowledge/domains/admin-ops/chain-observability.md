# 处置链可观测与配置

<!-- knowledge: capability=chain-observability rev=4
     sources=spec/changes/add-escalation-chain-admin-arbiter,spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md,spec/changes/redesign-chain-panel-ui -->

处置链的过程可见性面：SPEC 时间轴的全链节点、Dashboard 处置链视图（运维页三页签之一、bento 行卡形态）与链配置（配额/复位窗/黑名单）设置界面。

## 规则

- SPEC 运行时间轴将处置链各角色记录作为一等节点：Admin 处置 run 节点之外，Admin 每次尝试的配额计数事件、Admin→Arbiter 转单事件（附 handoff_reason 摘要与去向 Arbiter 标识）、Arbiter 每次尝试（含拍板/复现计数）、复现事件、链终点上升件均在时间轴可见——配额轨迹可回放。
- arbiter 节点台账联查（`_arbiter_ledger_index`/`_arbiter_node_payload`）保留并扩展到链事件；联查 fail-open：文件缺失/条目损坏/未命中一律静默省略，不阻塞时间轴渲染。
- spec=null 信号（无归属 spec）不挂 SPEC 时间轴，按主体键落 Dashboard 处置链视图归组。
- 处置链视图以 bento 卡片语言呈现（对齐 overview 页 `.ov-bento` 视觉规范：白底、1px 描边、12px 圆角、发丝行线、静态渲染无动画），链在办/签名配额/人工队列/上升件全量四区一律行卡形态（标识行、描述 2 行截断、链痕芯片行三段式），不使用表格；界面视觉以 SPEC 原型目录为 UI 真相源。视图顶部为 5 磁贴统计行：链在办（Admin/Arbiter 分计）、待人工、上升件（含近 24h 计数）、签名水位（含 Admin/Arbiter 顶格计数）、签名关联上升占比。
- 链在办行卡展示 phase 标签、spec、signal、已耗时、问题描述（同签名最近上升件摘要）、静态链进度条（Admin 已用/上限 → Arbiter 已用/上限 → 人工）与 run 标识/入链时刻/chain_id；字段不可得显示「—」，禁止伪 0。在办行可点击打开处置过程视图：run_id 可得时复用 agent 运行记录窗（AdminRunModal 形态），否则降级打开该签名最近上升件的详情抽屉。
- 在办件富化数据由 `chain_overview` 后端单点组装下发：问题描述摘要、Admin/Arbiter 已用计数与上限、run_id（从链上下文尽力提取，不可得置 null）；联查 fail-open，缺数据降级不阻断视图，前端不做自行联查。
- 视图数据单源：读 `admin_alerts.json`、arbiter ledger 与链状态文件，不引入平行真相源。
- 签名配额区按 spec 分组呈现：组头为 spec 名、项目、last_spec_status 与签名数/上升数/待人工数聚合，组序按待人工数、上升数、最近出现降序；签名行展示 Admin/Arbiter 配额双芯片（正常灰/顶格橙/耗尽红静态条）与链上结果标签（待人工红/已收口绿/Admin 或 Arbiter 顶格橙/无上升件灰字）；granularity≠spec 的签名追加主体键/类型级标签。有上升件的信号名可点击，下钻打开该签名最近上升件的处置过程（待人工优先，否则最新）。
- 人工队列区置于统计行之后、其余三区之前；无待人工件时整卡隐藏（统计行待人工计数为 0，其余区块正常）。每项内嵌裁决面板：选择裁决项 Select（options 含 label 与 desc）、处置依据 Input（可选）、执行按钮（destructive 项二次确认 Popconfirm）、标记已处理；复用告警裁决交互与 alert-resolve 闭环端点，执行成功后刷新队列。
- 处置链视图分层只读：人工队列内嵌裁决面板是链视图唯一写面，也是人工裁决主入口；告警记录页签保留为第二入口；上升件全量列表与详情抽屉纯只读（裁决选项仅只读预览，无执行入口）。
- 上升件全量区行卡呈现（severity/signal/spec·项目/终点短标签/状态/时间 + 描述 2 行截断 + 链痕芯片行），提供全部/待人工/已收口分段筛选；行点击打开详情抽屉（描述、证据、链痕 Timeline、建议处置、裁决选项只读预览）。
- 处置链视图不是独立菜单页，是运维页（`/activities`）三页签之一（antd Tabs：处置链 / 自动运维记录 / 告警记录），默认激活处置链页签；侧栏无「处置链」菜单项。老路由 `/chain` 保留重定向至 `/activities?tab=chain`（hash 路由 query 随 hash 传递，非法 tab 值回退处置链）。30s 轮询保持；页签失活即卸载面板，轮询随卸载停止（非常驻轮询）。
- 单项目聚合 Select 位于运维页统一标题栏筛选槽，仅在处置链页签激活时渲染；筛选 state 提升宿主页，跨页签切换保持。
- 失败面隔离：SSE 断流/加载失败横幅仅罩自动运维记录/告警记录两路数据，处置链页签激活时不展示；处置链数据不同源，保留自身 fail-soft 内联 Alert，不混报。
- 链配置四项——Admin 尝试配额、Arbiter 复现配额、复位窗天数、黑名单信号清单——在 Dashboard 设置页提供编辑界面，经既有配置热更新（30s mtime 检测）生效，无需重启；配置键归属 `core/config.py` 单源校验。

## 代码锚点

- 视图主实现：`core/dashboard/static/src/pages/activities/components/ChainPanel.tsx`（四区行卡、5 磁贴统计行、人工队列内嵌裁决面板）
- 数据聚合单点：`core/dashboard/data/admin_alerts.py`（`chain_overview`：在办件富化字段与签名配额下发）
- 链状态源：`core/pm_engine/escalation_chain.py`
- 前端投影类型：`core/dashboard/static/src/services/dashboard.ts`
- 复用件：`core/dashboard/static/src/pages/activities/components/AdminRunModal.tsx`（处置过程运行记录窗）

## 溯源

- 2026-11-03 add-escalation-chain-admin-arbiter（spec/changes/add-escalation-chain-admin-arbiter/） — 新增本页：时间轴全链节点（含 fail-open 台账联查扩展）、Dashboard 处置链视图（只读+数据单源）、链配置设置界面
- 2026-11-05 dashboard-ops-tabs-chain-merge（spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md） — 处置链视图随迁运维页三页签形态：独立菜单页退役（默认页签 + 老路由重定向 + 页签失活卸载停轮询 + 单项目筛选迁标题栏筛选槽 + SSE 横幅不罩处置链）
- 2026-11-10 redesign-chain-panel-ui（spec/changes/redesign-chain-panel-ui/） — 处置链页签 bento 重绘：四区表格改行卡 + 5 磁贴统计行；只读纪律改分层只读（人工队列内嵌裁决=主入口与唯一写面，其余面纯只读）；在办件联查富化（问题摘要/配额计数/run 标识尽力提取）后端单点下发；签名配额改 spec 分组、配额双芯片与信号名下钻
