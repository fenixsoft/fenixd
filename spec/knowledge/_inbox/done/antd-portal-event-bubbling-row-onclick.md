# antd Dropdown portal 弹层内点击会沿 React 组件树冒泡命中行级 onClick

## 背景

add-spec-name-copy-menu（SPEC 列表桌面表格名称列右键复制菜单）实现中，名称列单元格外包 antd Dropdown（`trigger={['contextMenu']}`）。设计前提「弹层经 portal 渲染于行命中面之外 → 菜单内点击天然不触发行级导航」被浏览器实测证伪：点击菜单项后页面跳进了该行 SPEC 详情页。

## 结论

- **React portal 只隔离 DOM 树，不隔离合成事件**：portal 内容里的 DOM 事件按 React 组件树（而非 DOM 祖先链）冒泡。antd Dropdown 在行内组件（TableCell/单元格组件）中渲染时，弹层 DOM 挂在 body 下，但菜单项 click 事件会沿 SpecNameCell → 单元格 → Table 行的组件链冒泡，命中 `Table onRow onClick`（整行点击进详情）触发导航。
- **行内 Dropdown/Popover 菜单项 onClick 必须 `domEvent.stopPropagation()`**，才能真正做到「菜单内点击不触发行级行为」。仓库既有同款习语：项目列表移动卡 ⋮ 菜单（`list.tsx` 菜单 onClick 内 `domEvent.stopPropagation()`）。
- 纯 DOM 层取证会漏掉这一形态：document 上的原生 click 监听只能看到 target=弹层内元素，看不到 React 合成层对行 onRow 的重放；判定须以 URL/路由实测为准。
- 「portal 于行命中面之外」不构成零导航保证；该保证只能由显式 stopPropagation（或行级 onRow 的事件目标守卫）给出。

## 证据

- 复现：SPEC 列表行内 `trigger={['contextMenu']}` Dropdown，点击菜单项 → `location.hash` 变为 `/projects/<p>/<spec>`；document capture 相 click 日志仅一条 `{tgt: "ant-dropdown-menu-title-content", isTrusted: true}`，无任何行/名称 span 的 click 记录。
- 修复后：菜单 onClick `({domEvent}) => { domEvent.stopPropagation(); … }`，右键与复制两步 hash 恒为列表路由（`#/projects/fenixd`）。
- 代码：`core/dashboard/static/src/pages/projects/list.tsx` SpecNameCell 菜单接线（修复提交 b73716af4）；测试钉死 `tests/specNameCopyMenu.test.mjs`「菜单项点击阻断行导航」断言。
