# Design: add-admin-activity-view

## Context

Administrator 自愈闭环已上线（`add-administrator-agent`）：AdminMonitor 检测困境 → 唤起 admin → 处置 → 落盘 `admin_alerts.json`。但 Dashboard 只有"未处理升级告警横幅"，人类无法回顾 Administrator 做过什么。本 change 让 admin 每次处置写人类可读的叙述总结，并在 Dashboard 提供独立的"运维记录"页面展示完整活动时间线。

## Goals / Non-Goals

**Goals**
- admin 处置后写 `summary` 叙述总结（时间/事项/结果/人工建议）
- Dashboard 独立"运维记录"页面展示全部 admin 活动
- 未处理升级置顶高亮，人工建议明确
- 面向人类可读、逻辑清晰

**Non-Goals**
- 不改变 AdminMonitor 检测/唤起逻辑（既有行为）
- 不改变 `admin_alerts.json` 的记录种类（signal/escalation/disposition），仅 disposition 记录新增可选 `summary` 字段
- 不做实时推送（页面轮询现有 `/api/alerts` 机制即可）

## Decisions

**D1: `summary` 作为 disposition 的可选顶层字段**
- admin 在 `.fenix/admin_disposition.json` 写 `summary`（叙述）；`_invoke_administrator` 落盘 disposition 记录时透传 `summary` 到 `admin_alerts.json`。
- 替代方案：单独文件存叙述。否决原因：与处置记录同源、同生命周期，合并存储避免同步问题。
- 向后兼容：旧记录无 `summary`，界面降级显示结构化字段。

**D2: 新 API `/api/admin-activities` 复用 AdminStore**
- 从 `admin_alerts.json` 过滤 `kind=disposition`，按时间倒序，未处理 escalation 关联记录置顶。
- 与现有 `/api/alerts`（横幅用）职责分离：alerts 返回未处理升级汇总，admin-activities 返回完整活动历史。

**D3: 独立页面走现有 dashboard 静态路由**
- 新增前端路由/侧边栏项"运维记录"，页面 JS 拉 `/api/admin-activities` 渲染时间线卡片。
- 复用现有 `esc()`/`statusPill`/severity 样式，不引入新前端框架。

**D4: admin prompt 增加 summary 撰写要求**
- 更新 `_build_prompt` 的 administrator 分支：`summary` 字段要求人类可读、含时间线/事项/结果/人工建议。

## Risks / Trade-offs

- [admin 忘记写 summary] → prompt 强调 + 界面对缺失 summary 降级显示结构化字段。
- [旧记录无 summary] → 界面容错（D1）。
- [页面数据量增长] → 时间线默认展示最近 N 条（如 100），超出折叠。

## Migration Plan

1. 无外部依赖，直接改代码。
2. 数据向后兼容：`summary` 为可选字段，旧记录无影响。
3. 回滚：git revert。

## Open Questions

- 是否需要导出/归档运维记录？（默认不做，时间线足够）
