# Proposal: redesign-dashboard-v2-ui-mobile

## Why

v2 六页桌面原型已定稿立项（redesign-dashboard-v2-ui），移动端（<768px）需同步适配以覆盖窄屏使用场景。移动端原型确认环已完成：六页移动版经批注迭代（头部按钮三处移除等）后用户定稿。

## What Changes

- v2 六页（概览/项目详情/SPEC 详情/配置/帮助/运维）增加移动端布局形态：KPI 2×2、表格转卡片流、目录抽屉化、横向滑动胶囊菜单、告警堆叠卡
- 复用 redesign-dashboard-v2-ui 的 v2 主题单源与路由族（零新路由、零新 API）
- 移动端定稿原型（prototype/m-*.html + screenshots/）为移动形态 UI 真相源

## Capabilities

### v2-commercial-ui（MODIFIED）

- 移动端断点（<768px）布局形态适配六页

## Impact

- 修改范围限定 `src/pages/v2/` 既有六页组件 + theme.tsx（断点 token/工具类）；桌面形态零回归
