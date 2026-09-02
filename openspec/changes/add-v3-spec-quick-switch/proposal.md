## Why

v3 Dashboard 的 SPEC 详情页目前只能通过返回项目列表页再点进另一个 SPEC 来查看其他 SPEC，路径长（两次跳转 + 列表页重新定位），在需要横向对照多个 SPEC 状态时效率低。在详情页 SPEC 名称旁提供下拉快速切换，可将操作缩短为一次点击。

## What Changes

- SPEC 详情页头部标题区的 SPEC 名称旁新增一个下拉箭头按钮，点击展开下拉面板。
- 下拉面板以表格形式列出当前项目下的其他 SPEC（排除当前 SPEC），每行显示 SPEC 名称与状态标签。
- 下拉数据来源于现有 `GET /api/specs?project=` 接口（`getSpecs`），不新增后端接口。
- 选中某个 SPEC 后收起下拉，路由跳转至该 SPEC 详情页（`/projects/:name/:spec`），页面数据随路由参数自动重载。
- 项目下只有当前一个 SPEC 时，下拉箭头不展示（无可切换项）。
- 拉取下拉列表失败时静默降级：箭头不展示或展开后显示加载失败提示，不影响详情页主体功能。

## Capabilities

### New Capabilities

- `spec-detail-quick-switch`: 在 SPEC 详情页头部提供 SPEC 下拉切换能力，覆盖下拉入口展示条件、下拉行内容、排除当前 SPEC、选中跳转与降级行为。

### Modified Capabilities

（无——现有能力均无 spec 级需求变更）

## Impact

- 前端：`core/dashboard/static/v3/src/pages/projects/detail.tsx`（头部标题区新增下拉）、`core/dashboard/static/v3/src/services/dashboard.ts`（复用现有 `getSpecs`，无接口改动）。
- 后端：无改动（`/api/specs` 已存在且 v3 列表页已在用）。
- 依赖：Ant Design `Dropdown`（已在依赖树内，无新增依赖）。
- 移动端：详情页头部在窄屏下需保持可用（下拉面板正常展开与选择）。
