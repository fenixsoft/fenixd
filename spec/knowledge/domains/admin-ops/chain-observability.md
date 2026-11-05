# 处置链可观测与配置

<!-- knowledge: capability=chain-observability rev=2
     sources=spec/changes/add-escalation-chain-admin-arbiter,spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md -->

处置链的过程可见性面：SPEC 时间轴的全链节点、Dashboard 处置链视图（运维页三页签之一）与链配置（配额/复位窗/黑名单）设置界面。

## 规则

- SPEC 运行时间轴将处置链各角色记录作为一等节点：Admin 处置 run 节点之外，Admin 每次尝试的配额计数事件、Admin→Arbiter 转单事件（附 handoff_reason 摘要与去向 Arbiter 标识）、Arbiter 每次尝试（含拍板/复现计数）、复现事件、链终点上升件均在时间轴可见——配额轨迹可回放。
- arbiter 节点台账联查（`_arbiter_ledger_index`/`_arbiter_node_payload`）保留并扩展到链事件；联查 fail-open：文件缺失/条目损坏/未命中一律静默省略，不阻塞时间轴渲染。
- spec=null 信号（无归属 spec）不挂 SPEC 时间轴，按主体键落 Dashboard 处置链视图归组。
- Dashboard 处置链视图展示：链上在办件（Admin/Arbiter 当前 run 标识与已耗时）、等待队列深度、各签名配额水位（已用/上限）、近期上升件。
- 处置链视图不是独立菜单页，是运维页（`/activities`）三页签之一（antd Tabs：处置链 / 自动运维记录 / 告警记录），默认激活处置链页签；侧栏无「处置链」菜单项。
- 老路由 `/chain` 保留重定向至 `/activities?tab=chain`：hash 路由 query 随 hash 传递，运维页读 `?tab=` 预选页签（非法值回退处置链），老深链落地处置链页签不 404。
- 只读纪律与 30s 轮询保持；处置链页签失活即卸载面板，轮询随卸载停止（非常驻轮询）。
- 单项目聚合 Select 位于运维页统一标题栏筛选槽，仅在处置链页签激活时渲染；筛选 state 提升宿主页，跨页签切换保持。
- 失败面隔离：SSE 断流/加载失败横幅仅罩自动运维记录/告警记录两路数据，处置链页签激活时不展示；处置链数据不同源，保留自身 fail-soft 内联 Alert，不混报。
- 处置链视图只读：不提供链上人工干预入口，人工裁决入口收敛于上升件 choices。
- 视图数据单源：读 `admin_alerts.json`、arbiter ledger 与链状态文件，不引入平行真相源。
- 链配置四项——Admin 尝试配额、Arbiter 复现配额、复位窗天数、黑名单信号清单——在 Dashboard 设置页提供编辑界面，经既有配置热更新（30s mtime 检测）生效，无需重启；配置键归属 `core/config.py` 单源校验。

## 溯源

- 2026-11-03 add-escalation-chain-admin-arbiter（spec/changes/add-escalation-chain-admin-arbiter/） — 新增本页：时间轴全链节点（含 fail-open 台账联查扩展）、Dashboard 处置链视图（只读+数据单源）、链配置设置界面
- 2026-11-05 dashboard-ops-tabs-chain-merge（spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md） — 处置链视图随迁运维页三页签形态：独立菜单页退役（默认页签 + 老路由重定向 + 页签失活卸载停轮询 + 单项目筛选迁标题栏筛选槽 + SSE 横幅不罩处置链）
