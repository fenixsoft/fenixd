<!-- knowledge: capability=v3-activities-page rev=3 sources=spec/archive/2026-09-08-add-v3-activities-page,spec/archive/2026-09-10-add-activities-pagination,spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md -->

# v3 运维记录页

v3 的跨项目运维页：处置链 / 自动运维记录 / 告警记录三页签，自动运维为全局合并时间线，容量受前端分页控制。

## 现行规则

- `/activities` 经 `GET /api/admin-activities` 全量拉取跨项目聚合数据（响应含 `projects` 分组数组），前端合并为单一全局运维事件时间线展示；不按项目分组、无项目页签、无条数徽标；每条记录卡片保留所属项目 Tag 保证来源可辨。
- 页面为 antd Tabs 三页签：处置链 / 自动运维记录 / 告警记录；首屏读 URL `?tab=` 预选（仅认 `auto`/`alert`，非法或缺省回退处置链），缺省激活处置链页签；页签切换在当前页内完成。页签内容按激活态条件渲染——失活页签即卸载（处置链 30s 轮询随卸载停止，自动运维/告警状态在宿主页、重挂零成本）。
- 老路由 `/chain` 重定向至 `/activities?tab=chain`，老深链落地处置链页签不 404。
- 统一标题栏声明 title「运维」、副标题「跨项目 Administrator 活动与处置链观测」罩三页签；处置链页签激活时筛选槽渲染单项目聚合 Select（「全部项目」），筛选 state 提升宿主页、跨页签切换保持，其余页签无过滤项。
- SSE 断流与加载失败横幅仅罩自动运维记录/告警记录两路数据，处置链页签激活时不展示（处置链数据不同源，有独立 fail-soft Alert）。
- 人工告警视图合并展示全部项目的未处理与已解决告警（不按项目过滤），每条保留严重度、时间、所属项目等元信息与「标记已处理」操作（乐观更新 + 后端确认）；「已解决」分组默认展开，处置闭环无需点击即可见。
- 处置记录时间线按时间倒序展示；未处理升级的记录置顶且视觉高亮。
- 时间线启用前端分页：每页 15 条，默认仅渲染最新 15 条，其余记录翻页时再渲染（数据仍全量拉取）。
- 数据为空时展示「暂无运维记录」空态而非空白；页面不出现「建设中」占位内容。

## 溯源

- 2026-09-08 add-v3-activities-page（spec/archive/2026-09-08-add-v3-activities-page） — 建立 /activities 跨项目聚合视图（初版：项目页签 + 条数徽标 + 分段展示）与处置记录时间线、未处理置顶语义
- 2026-09-10 add-activities-pagination（spec/archive/2026-09-10-add-activities-pagination） — 改为全局合并时间线（每卡保留项目 Tag），新增自动运维/人工告警 Radio 双视图与每页 15 条前端分页
- 2026-11-05 dashboard-ops-tabs-chain-merge（spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md） — Radio 双视图随处置链并入改版为三页签（处置链/自动运维记录/告警记录，默认处置链），新增 `?tab=` 预选与 `/chain` 重定向、标题栏筛选槽单项目聚合 Select、SSE 横幅两路罩面
- 已随 2026-09-10-add-activities-pagination 废除：项目维度页签切换（含「全部」页签与各处条数徽标）
