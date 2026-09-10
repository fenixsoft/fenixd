# 运维记录页容量控制与结构简化（add-activities-pagination）

## Why

运维记录页无任何界面容量控制：`admin_alerts.json` 每项目最多 150 条（signal/escalation/disposition 共享池），页面把全部项目的记录一次性渲染成超长 Timeline，每条卡片 3 段 react-markdown，首屏渲染成本随记录数×项目数线性膨胀；按项目页签划分在"跨项目看最新动态"场景下增加点击与切换成本。另外已解决人工告警默认折叠在 Collapse 内，处置闭环情况需手动展开才能看到。

## What Changes

- **BREAKING**（页面布局）：取消按项目页签（含"全部"页签与各处条数 Badge），页面改为全局一份「自动运维 / 人工告警」Radio 切换，两个视图均不再按项目划分。
- 自动运维视图：跨项目合并的全局运维事件 Timeline（时间倒序，未处理升级置顶语义保留）；因不再有项目分组，每条卡片继续展示项目 Tag 标识来源。
- 新增分页：默认仅显示最新 15 条，其余翻页时再渲染（前端分页；数据仍全量拉取——存储层已有 150 条/项目硬上限，无传输压力）。
- 人工告警视图：展示全部项目的未处理与已解决告警（不再按项目过滤）；「已解决」Collapse 默认展开。
- 数据端接口无变更：`/api/admin-activities`、`/api/alerts` 响应结构保持不动，全部改动收在前端单页。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `v3-activities-page`：视图重组（取消项目页签 → 全局 Radio 切换）、运维事件 Timeline 分页（15 条/页）、人工告警合并为全局视图且已解决 Collapse 默认展开。

## Impact

- 前端页面：`core/dashboard/static/src/pages/activities/index.tsx`（改动集中于此单文件）。
- 构建产物：`core/dashboard/static/dist/` 必须重建并提交（dashboard 验证读主树 dist，旧产物会导致 UI 验证假阴性）。
- 后端接口与存储层（`core/dashboard/server.py`、`core/admin_store.py`）无变更。
- 既有 v3 回归面：overview 页横幅、项目页 SpecDocModal 内 admin-invoke-dialog（带 spec 过滤参数调用 getAdminActivities）不受本次改动影响，需回归确认未破坏。
