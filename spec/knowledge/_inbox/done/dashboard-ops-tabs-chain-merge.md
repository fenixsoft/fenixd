# 处置链并入运维页三页签（Dashboard 视图形态变更）

2026-11-05 用户指令：处置链独立菜单/路由页退役，并入运维页三页签。
admin-ops 域 `chain-observability` 页「Dashboard 处置链视图」段的形态
描述需随迁：视图不再是独立菜单页，而是运维页（`/activities`）页签之一。

变更要点（commit be6dc352ba）：

- 侧栏菜单删除「处置链」项；运维页 Radio.Group 双按钮改 antd Tabs 三页签：
  处置链 / 自动运维记录 / 告警记录；默认激活处置链（2026-11-05 用户定调）。
- 原 `/chain` 页迁为 `activities/components/ChainPanel`：只读纪律与 30s
  轮询保持；页签失活即卸载，轮询随卸载停止（原独立页为常驻轮询）。
- 路由 `/chain` 保留重定向 `/activities?tab=chain`（hash 路由 query 随
  hash 传递，activities 页 `initialTab` 读 `?tab=` 预选页签）；老深链落地
  处置链页签不 404。
- 单项目聚合 Select 从链观测页顶栏迁至运维页统一标题栏筛选槽（仅在处置
  链页签激活时渲染）；筛选 state 提升宿主页，跨页签切换保持。
- SSE 断流/加载失败横幅仅罩自动运维记录/告警记录两路数据；处置链页签
  数据不同源，保留自身 fail-soft 内联 Alert，不混报。

## 建议折叠去向

- admin-ops/chain-observability：Dashboard 处置链视图形态段随迁（独立页→
  运维页页签 + 重定向 + 默认页签）。
- dashboard-frontend 域导航：运维页条目（v3-activities-page 族）补三页签
  形态一句。

## 溯源

- 2026-11-05 用户指令，commit be6dc352ba（core/dashboard/static 路由/
  菜单/activities 页改造 + pages/chain 迁移）
