<!-- knowledge: capability=activity-records-tabs rev=1 sources=spec/archive/2026-09-02-improve-dashboard-sections -->

# 活动记录页签

跨项目运维记录视图（`activities/`）以页签按项目组织记录，并保证处置记录多行内容可读。

## 现行规则

- 跨项目视图页签栏包含「全部」页签与每个有运维记录的项目名页签（按项目名排序）；默认激活「全部」，其内容仍按项目分段聚合展示全部记录。
- 点击项目页签仅展示该项目的运维记录；页签切换为纯前端状态（不改变 URL hash），当前选择在页面内刷新/SSE 重绘后保持。
- 单项目模式（`activities/<project>`）保持不变：仅展示该项目记录，不显示页签栏。
- 处置记录按换行展示：数据层写入新处置记录时，`actions_taken`/`summary` 为列表结构则以换行符（`\n`）连接各条目（每条独立一行），不以分号连接。
- 前端活动卡片对 summary、action_taken（处置）、recommended_action（建议）及旧记录降级回退区均保留换行（`white-space: pre-wrap` 与 `word-break: break-word`）。
- 历史已写入的单行/分号分隔记录按原样展示，不以分号强行拆分（避免误拆叙述性分号）。

## 溯源

- 2026-09-02 improve-dashboard-sections（spec/archive/2026-09-02-improve-dashboard-sections） — 建立跨项目运维记录按项目页签组织（「全部」聚合页签、纯前端选中态、单项目路由不变）与处置记录换行落盘/换行展示契约
