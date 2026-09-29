<!-- knowledge: capability=v2-alerts-activities rev=1 sources=spec/archive/2026-09-05-v2-alerts-activities -->

# v2 告警横幅与运维记录页

v2 壳层的告警聚合入口与 admin 活动时间线页。

## 现行规则

- header 的 alert-banner service 拉取 `/api/alerts`（跨项目聚合）：存在未处理告警时横幅可见并显示条数，无告警时横幅不显示。
- 横幅点击打开告警列表 Dialog：每行「标记已处理」POST `/api/alerts/<id>/handled` 后 reload；「全部清空」POST `/api/alerts/clear`；监听 `sse:alerts` 重拉。
- 运维记录页 `#/activities` 渲染 admin 活动时间线（Timeline）与跨项目页签；act-timeline 监听 `sse:admin_activities` 重拉。
- 单项目路由 `#/activities/:project` 以 `?project=` 参数过滤。
- 已处理后的列表保持展开；支持一键清理全部事件。

## 溯源

- 史前复原 — v2 壳级告警横幅与运维记录页骨架；已处理后列表保持展开、支持一键清理全部事件
- [2026-09-05 v2-alerts-activities](spec/archive/2026-09-05-v2-alerts-activities/) — 落地告警横幅聚合拉取与处置闭环（单条已处理 / 全部清空 / sse:alerts 重拉）及运维记录时间线、项目过滤与 sse:admin_activities 重拉
