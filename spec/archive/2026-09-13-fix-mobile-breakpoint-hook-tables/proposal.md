## Why

v3 dashboard 的移动端适配存在一个 P0 级缺陷与一个断点空窗：HookManager 的三张 antd Table 无 `scroll.x` 兜底，390px 视口下表格内容 1055px 把整个页面撑到 1080px，全页横向滚动约 2.7 屏、同页其他正常内容全部压扁（spec 详情 Hook 页签与设置页项目作用域 Hook 面板两处中招）；同时 CSS 轨（`screen-xs`，<576px）与 JS 轨（`useIsMobile`，<768px）断点不一致，576–768px 区间「移动端内容 + PC 端排版」混杂（实测 600px 下页面留白仍 40px）。

## What Changes

- `core/dashboard/static/src/global.less`：全部 15 条移动端规则的选择器由 `#root .screen-xs X` 统一为 `#root :is(.screen-xs, .screen-sm) X`（有效边界 <768px，与 `hooks/useIsMobile.ts` 的 767.98 对齐），并更正 L133–135 的旧注释（实测证实 ProLayout 根节点在 576–767px 会挂 `screen-sm`，旧注释「screen-sm 命中不了」有误）。
- `core/dashboard/static/src/components/HookManager.tsx`：三张 Table（生效合并表 / Hook CRUD 表 / 最近执行审计表）各加 `scroll={{ x: 'max-content' }}`，溢出限制在表格容器内部横滚，杜绝整页横滚。
- `HookManager.tsx` 移动端卡片化：组件自持 `useIsMobile()`，三表按 `isMobile` 分支渲染为卡片 List（复用 `pages/projects/list.tsx` 的 SpecCardList 范式），字段与桌面列一一对应，交互（启停 Switch / 编辑 / 删除）绑定既有 handler；PC 端 Table 渲染路径零改动。
- `core/dashboard/static/src/global.less`：追加移动端全站 Modal 防御上限 `max-width: calc(100vw - 32px)`。

## Capabilities

### New Capabilities

- `mobile-breakpoint-unification`: 移动端 CSS 作用域统一覆盖 <768px（screen-xs ∪ screen-sm），消除 576–768px 适配空窗；含全站 Modal 移动端宽度上限。
- `hook-tables-mobile-adaptation`: HookManager 三张表格的移动端呈现——容器内横滚兜底（任何视口下整页不横滚）与移动端卡片化（字段完整、交互保留、只读形态）。

### Modified Capabilities

（无——dashboard 移动端适配此前未 SPEC 化，无既有能力的需求变更）

## Impact

- 受影响文件：`core/dashboard/static/src/global.less`（既有 15 条规则选择器替换 + 追加规则）、`core/dashboard/static/src/components/HookManager.tsx`（3 处 Table 加 scroll、新增 isMobile 分支卡片渲染）。
- 消费方：`pages/projects/detail.tsx`（Hook 页签）与 `pages/settings/components/HooksPanel.tsx` 仅经组件 props 传递，接口零改动。
- PC 端（≥768px）：所有改动限定于 `:is(.screen-xs,.screen-sm)` 作用域或 `isMobile` 分支，桌面渲染路径逐字节不变；1280 等窄 PC 窗口下现状本就溢出，容器内横滚属修复非回归。
- 无 API / 数据 / 依赖变更；不引入新依赖库。
