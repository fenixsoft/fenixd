# dsh 右侧边栏页签注册契约（sidebar-right）与文件右键定位落点

日期：2026-11-11 · 来源：fenix-dsh-dashboard-bridge「Fenix 项目」页签实现（m02220 语义纠正后返工）

## 契约要点（dsh-client-ui-sidebar-right 0.2.2-rc.1，实测）

- **两段注册**：①`ctx.sidebarRightTabs.register({id, kind, keepMounted?, priority?, title(address)=>string, guide?[]})→disposer`（definition；guide 条目出现在右缘 dock 的「New tab / Start」列表）；②以 definition 的 **id** 为 key 往 keyed 插槽 `sidebar.right.pane.tab` 注册 body 组件（`ctx.slots.register({name:'sidebar.right.pane.tab', key: ID}, Body)`）。缺任一段页签不可用。
- **body 消费**：框架注入 `props.useTabInfo()` → `{tab, panel}`；深链参数走 `tab.navigation = {address, params, revision}`，`ctx.sidebarRight.openTab(kind, {params})` 同 kind 唤起既有页签并送达新 params。
- **keepMounted:true** 使 body 跨会话切换/隐藏保活（iframe 不重载；实测切会话后 iframe 原样存活）。
- **「Start」新页签页**：dock「New tab」按钮打开 Start 页，列出所有已注册 guide 条目（内置 Workspace files / Code review and changes / New terminal + 各插件条目）——插件页签的发现入口。

## 实战教训

- **「侧边栏」语义**（用户纠正 m02220）：dsh web 语境的 sidebar 指对话界面**右缘 dock**（工作区文件/代码审查变更所在面板列），不是左侧栏。为 dashboard 做「项目直达」时落点应是右缘页签，`sidebar.panellist` 左侧条目版本已移除。
- **文件右键菜单的 chip 只存在于消息内容**：composer @-mention chip 无 context menu；可右键的文件入口=消息内文件 chip 与右缘 dock「Workspace files」页签的文件行（`[role=treeitem]`，类名 `Lgz0XW_name`）。
- **playwright 合成事件不够**：`el.dispatchEvent(new MouseEvent('contextmenu'))` 不触发原生菜单；须 `mousemove` 到元素坐标 + `mousedown right` + `mouseup right`（playwright-cli 真实输入）。
- **可选注入服务的降级序**：`inject` 缺包时 `ctx.<service>` undefined——注册函数须按「服务缺席→no-op unregister」降级；运行时优先级（openTab 侧栏 → 回退主面板）用 `typeof deps.x === 'function'` 判定。
- 验证链路：菜单项点击 → dock tablist 出现 `Files(未选)/Fenix 项目(选中)` → iframe src 变 `#/projects/<p>?tab=home&path=<rel>` → iframe 内 `project-home-fileview` 渲染 markdown 文件视图（同源 iframe，`contentDocument` 可直接断言）。

关联：bridge README.zh.md「右侧边栏『Fenix 项目』页签」节；spec/knowledge/domains/harness-integration/。
