<!-- knowledge: capability=portal-event-bubbling-row-nav rev=1 sources=spec/knowledge/_inbox/done/antd-portal-event-bubbling-row-onclick.md -->

# 行内弹层点击与行级导航隔离

> 最后更新：2026-11-16 12:24 UTC+8

表格行内承载的 antd portal 弹层（Dropdown/Popover 形态的右键菜单、操作弹层）与行级点击导航（`Table onRow onClick`）之间的隔离契约：划定「弹层内点击不触发行级行为」这一保证的责任面与判定纪律。

## 规则

- React portal 只隔离 DOM 树，不隔离合成事件：弹层 DOM 虽经 portal 挂载到 body 之下，弹层内的 DOM 事件按 React 组件树（而非 DOM 祖先链）冒泡——弹层组件嵌在行内组件（单元格/TableCell）中渲染时，弹层内点击沿「弹层内容 → 单元格 → 表格行」的组件链冒进行级处理器，命中 `onRow onClick` 触发整行导航。
- 「弹层经 portal 渲染于行命中面之外」不构成零导航保证；零导航保证只能由显式 `domEvent.stopPropagation()`（弹层内可点项 onClick）或行级 onRow 事件目标守卫给出。
- 行内 Dropdown/Popover 承载可点击项时，每个可点项（菜单项/按钮）onClick 必须 `domEvent.stopPropagation()`。仓库同款习语：SPEC 名称列右键复制菜单、SPEC 信息图标触发器与「清除」按钮、项目列表移动卡 ⋮ 菜单与桌面操作列菜单。
- 判定纪律：纯 DOM 层取证会漏判——document 上的原生 click 监听只能看到 target 为弹层内元素，看不到 React 合成层对行 onRow 的重放；「弹层内点击是否触发行导航」以 URL/路由实测为准。

## 代码锚点

- 主实现与消费方：`core/dashboard/static/src/pages/projects/list.tsx` — 名称列右键复制菜单项 `domEvent.stopPropagation()` 接线；SpecInfoIcon 信息图标触发器与「清除」按钮各自 stopPropagation。
- 单源符号：`core/dashboard/static/src/pages/projects/specRowClick.ts` — `rowClickHitsExpandIcon` 行点击守卫（事件目标命中展开钮即短路行级导航）。
- 守卫测试：`core/dashboard/static/tests/specNameCopyMenu.test.mjs` — 「菜单项点击阻断行导航」断言钉死 stopPropagation 接线。

## 溯源

- 2026-11-16 antd-portal-event-bubbling-row-onclick（spec/knowledge/_inbox/done/antd-portal-event-bubbling-row-onclick.md） — 新建本页：portal 只隔离 DOM 不隔离合成事件、弹层内点击沿组件树冒泡命中行 onRow、行内弹层可点项显式 stopPropagation 习语与路由实测判定纪律
