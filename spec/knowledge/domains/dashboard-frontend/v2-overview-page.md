<!-- knowledge: capability=v2-overview-page rev=1 sources=spec/archive/2026-09-05-v2-overview-page -->

# v2 概览页

v2 的项目总览：统计块 + 项目卡片网格，项目级生命周期操作与 SSE 定向重拉。

## 现行规则

- 概览页渲染 5 个统计块（字段按 behavior.md §1，经 adaptOverview 数字化）与项目卡片网格（名称、状态、SPEC 计数等，经 adaptProjects）。
- 每张项目卡提供启动 / 停止 / 删除按钮：confirm 确认后调用既有生命周期端点（如 `POST /api/projects/<name>/start`），成功后 toast 并重拉 ov-projects。
- 项目卡片点击跳转项目页。
- ov-stats 监听 `sse:state` 与 `sse:refresh`，ov-projects 监听 `sse:state`；收到帧后按 componentId reload（节流由桥负责）：watcher 检测到项目 `.fenix` 数据变化产生 state 帧后，8 秒内 ov-stats / ov-projects 完成重拉。

## 溯源

- 史前复原 — v2 概览页统计块 + 项目卡片 + 启停删操作 + SSE 重拉骨架；项目卡片点击跳转项目页
- [2026-09-05 v2-overview-page](spec/archive/2026-09-05-v2-overview-page/) — 落地统计块 / 卡片数据适配（adaptOverview / adaptProjects）、生命周期操作 confirm 闭环与 sse:state / sse:refresh 定向重拉
