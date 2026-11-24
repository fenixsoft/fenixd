# Proposal: SPEC 列表信息改状态旁悬浮图标

## Why

SPEC 列表当前以「行下信息子行」（expandedRowRender 子行 / 移动端 amber 软底信息行）承载 SPEC 的告警与提示信息（`error` 字段）。子行常驻展开使有信息的行占两行高度、打断台账单行节奏，纵向空间与扫读效率受损。改为状态标签旁的信息图标 + 悬浮提示，可在保留信息可及性的前提下恢复列表单行形态。

## What Changes

- **桌面表格**：`record.error` 非空时不再渲染行下信息子行（移除 `expandedRowRender` / `rowExpandable` 的 error 分支），改在状态列状态胶囊旁渲染信息图标（antd `InfoCircleOutlined`，warning 橙色，对齐原「信息」Tag 语义）；悬浮图标弹出 Popover 展示完整信息文本（可换行不截断），弹层内保留「清除」按钮（清除链路 `POST /api/spec-error-clear` 契约不变）。
- **移动端卡片**：amber 软底信息行退役，改在语义胶囊行状态胶囊旁渲染同一信息图标；触屏点按（click 触发）与桌面悬浮（hover 触发）双触发弹出同一 Popover（完整信息 + 清除）。
- **受控展开逻辑**：`expandedRowKeys` 不再服务 error 信息行，仅服务 fix-* 树形子级展开；首次全展开、增量合并、项目切换复位的闩锁语义对树形子级保持不变。
- **零改动面**：后端 API（含 `/api/spec-error-clear`）、error 字段语义、blocked 判定（error 子串命中 `SPEC_REVIEW_BLOCKED_MARKERS`）、名称 Why 悬浮提示、验证异常悬浮提示均不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `dashboard-spec-table`: 「SPEC 信息子行替换『错误』列」requirement 变更——行下信息子行退役，改为状态标签旁信息图标 + 悬浮 Popover 提示；「清除」按钮从子行行尾迁移至弹层内，清除契约不变。

## Impact

- `core/dashboard/static/src/pages/projects/list.tsx`：桌面状态列与 expandable 配置、移动端卡片胶囊行与信息行、受控展开注释、清除按钮迁移。
- `core/dashboard/static/dist/index.html`：前端生产 rebuild 锚点（reference）。
- 后端与 API：零改动。
