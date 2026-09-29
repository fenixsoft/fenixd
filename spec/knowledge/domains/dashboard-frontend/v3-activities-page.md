<!-- knowledge: capability=v3-activities-page rev=2 sources=spec/archive/2026-09-08-add-v3-activities-page,spec/archive/2026-09-10-add-activities-pagination -->

# v3 运维记录页

v3 的跨项目运维记录：全局合并时间线 + 自动运维/人工告警双视图，容量受前端分页控制。

## 现行规则

- `/activities` 经 `GET /api/admin-activities` 全量拉取跨项目聚合数据（响应含 `projects` 分组数组），前端合并为单一全局运维事件时间线展示；不按项目分组、无项目页签、无条数徽标；每条记录卡片保留所属项目 Tag 保证来源可辨。
- 页面提供全局一份 Radio 切换「自动运维 / 人工告警」，默认选中「自动运维」；切换在当前页内完成，不引入额外路由或页签。
- 人工告警视图合并展示全部项目的未处理与已解决告警（不按项目过滤），每条保留严重度、时间、所属项目等元信息与「标记已处理」操作（乐观更新 + 后端确认）；「已解决」分组默认展开，处置闭环无需点击即可见。
- 处置记录时间线按时间倒序展示；未处理升级的记录置顶且视觉高亮。
- 时间线启用前端分页：每页 15 条，默认仅渲染最新 15 条，其余记录翻页时再渲染（数据仍全量拉取）。
- 数据为空时展示「暂无运维记录」空态而非空白；页面不出现「建设中」占位内容。

## 溯源

- [2026-09-08 add-v3-activities-page](spec/archive/2026-09-08-add-v3-activities-page/) — 建立 /activities 跨项目聚合视图（初版：项目页签 + 条数徽标 + 分段展示）与处置记录时间线、未处理置顶语义
- [2026-09-10 add-activities-pagination](spec/archive/2026-09-10-add-activities-pagination/) — 改为全局合并时间线（每卡保留项目 Tag），新增自动运维/人工告警 Radio 双视图与每页 15 条前端分页
- 已随 2026-09-10-add-activities-pagination 废除：项目维度页签切换（含「全部」页签与各处条数徽标）
