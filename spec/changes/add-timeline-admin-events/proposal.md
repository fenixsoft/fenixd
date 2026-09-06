# add-timeline-admin-events

## Why

SPEC 详情页的运行时间轴目前只有两类事件：状态转移（state）与 Agent 运行（run）。SPEC 执行期间 Administrator（admin agent）实际介入过运维（升级告警发生、处置完成）时，时间轴上完全不可见——用户必须在「运维记录」独立页面按 spec 过滤后人工比对时间，才能拼出「告警发生 → admin 处置」这段完整因果链。时间轴作为单一事实视图存在盲区，排查问题时容易漏掉运维介入这一关键环节。

## What Changes

- `get_spec_timeline` 数据源扩展：从 `.fenix/admin_alerts.json` 读取与当前 spec 关联的 `escalation`（升级告警）与 `disposition`（运维处置）记录，作为第三类时间轴节点 `kind="admin"` 下发。
- 节点归并：同 `admin_run_id` 的 disposition 若存在非 pending 的最终处置记录，pending（处置中）记录被最终记录替代（与运维记录页归并语义一致），避免时间轴出现「永久处置中」。
- 排序融合：admin 节点与 state/run 节点共用 `_timeline_sort_key` 按事件时间统一排序（同秒内 state 先于 admin、admin 先于 run 的次序并入现有 kind 次序规则）。
- 前端渲染：SPEC 详情时间轴（`detail.tsx`）为 `kind="admin"` 新增渲染分支——标题行（时间 + 「运维处置/升级告警」标签 + severity 着色 Tag + 处置结果/已处理状态 Tag）+ 一句话摘要（description，单行截断）。不渲染 summary markdown 四段全文（完整内容仍走运维记录页）。
- 兼容性：记录缺失 `spec` 字段（历史脏数据）跳过不下发；`admin_alerts.json` 缺失/损坏时 fail-open 返回空，时间轴照常渲染 state/run 两类节点。

## Capabilities

### New Capabilities
- `spec-timeline-admin-events`: SPEC 详情时间轴融合展示该 spec 关联的 admin 运维事件（升级告警 + 处置），按事件时间与既有节点统一排序。

### Modified Capabilities

（无——归档的 `admin-activity-view` 能力管独立运维记录页，本次不改变其任何需求；SPEC 时间轴为新增能力面。）

## Impact

- `core/dashboard/data.py`：`get_spec_timeline` 新增 admin 事件源读取与归并/排序融合；`_timeline_sort_key` kind 次序扩展。
- `core/dashboard/static/src/pages/projects/detail.tsx`：`renderTimeline` 新增 `kind="admin"` 渲染分支。
- API 契约：`GET /api/spec-detail` 响应的 `timeline[]` 数组新增 `kind="admin"` 元素（新增字段，向后兼容——旧前端遇到未知 kind 会走默认分支，无破坏）。
- 不触及状态机、派发、验证链核心逻辑；无数据迁移（直接读既有 `admin_alerts.json`）。
