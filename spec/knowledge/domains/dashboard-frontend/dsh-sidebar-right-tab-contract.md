# dsh 右侧边栏页签注册契约与文件定位落点

<!-- knowledge: capability=dsh-sidebar-right-tab-contract rev=1
     sources=spec/knowledge/_inbox/done/dsh-sidebar-right-tab-contract-1111.md -->

dashboard-bridge 插件在 dsh web 对话界面右缘 dock（右侧边栏，`@deepseek-ai/dsh-client-ui-sidebar-right`）注册「Fenix 项目」页签的契约面：两段注册、params 深链消费、保活与发现入口，以及文件右键「定位」经该页签打开项目的运行时落点与降级序。

## 规则

- **「侧边栏」语义=右缘 dock**：dsh web 语境的「侧边栏」指对话界面右缘 dock（工作区文件/代码审查变更所在的面板列，发行包 `@deepseek-ai/dsh-client-ui-sidebar-right`），不是左侧 rail 菜单栏。dashboard 的「项目直达」落点是右缘页签；左侧 rail 无「Fenix 项目」直达条目，项目直达仅经右缘页签承载。
- **页签注册两段式，缺一段页签不可用**：① definition 注册——`ctx.sidebarRightTabs.register({id, kind, keepMounted?, priority?, title(address)=>string, guide?})→disposer`；② body seat——以 definition 的 id 为 key 往 keyed 插槽注册 body 组件 `ctx.slots.register({name:'sidebar.right.pane.tab', key:<id>}, Body)`。插件钉值：id=`fenix-dsh-dashboard-bridge`（包名，body seat key 与之一致）、kind=`fenix-dashboard`（openTab 按 kind 寻址，自定义 kind 零校验）、`keepMounted:true`、title 恒「Fenix 项目」。
- **body 经 useTabInfo 消费深链参数**：框架向 body 注入 `props.useTabInfo()` → `{tab, panel}`；深链参数读 `tab.navigation = {address, params, revision}`。`ctx.sidebarRight.openTab(kind, {params})` 对同 kind 页签 pane 内 reveal 并送达新 params（revision++），body 依 params 重算 iframe src 即完成深链导航——params 未变时 src 同值、React 不改 iframe src 属性（无重载纯 reveal）；同 params 重复导航不强制重载（页签已在目标视图）。
- **keepMounted:true 跨会话保活**：页签内容跨隐藏与跨会话切换保活，iframe 不重载、状态不丢——右键定位进入文件视图后切走再回来，视图不重置。
- **guide 条目是页签发现入口**：definition 的 guide 条目出现在右缘「New tab / Start」列表，与内置 Workspace files / Code review and changes / New terminal 并列；无 guide 条目的插件页签用户不可发现。本插件 guide「Fenix 项目」（order 40，折角文件夹线性图标）→ 项目总览 `#/projects`。
- **侧栏 params → dashboard hash 路由映射**：project 缺席/空串 → 项目总览单入口 `#/projects`；有 project → `#/projects/<enc>?tab=home&path=<enc-rel>`（path 缺席视为项目根，rel 空串退化为项目首页根路由）。
- **可右键的文件入口面**：文件右键菜单 chip 只存在于消息内容——可右键的文件入口=消息内文件 chip 与右缘 dock「Workspace files」页签的文件行（`[role=treeitem]`）；composer @-mention chip 无 context menu。
- **定位点击的运行时落点优先级**：菜单项「在 <项目名> 项目定位」点击后，右侧边栏页签 `openTab` 深链为首选落点（`typeof deps.openSidebarProjectTab === 'function'` 判定）；sidebarRight 服务缺席时回退 main keyed 面板（iframe src 携项目文件深链重注册）+ `selectPanel` 激活。该菜单项与原生提示消解器的共存守卫归属能力页 fenix-dash-bridge-workspace-nav，不在本页。
- **可选注入服务降级序**：dsh `inject` 缺包时 `ctx.<service>` 为 undefined——每个注册函数按「服务缺席 → 返回 no-op unregister」降级（sidebarRightTabs / slots / contextMenus / sessions 同一纪律），页签不注册、菜单不贡献、不产未处理异常；useTabInfo 注入面抛错按无 params 降级（落项目总览）不崩。
- **resolve 整单失败红线**：contextMenus.resolve 抛错会让菜单服务整单失败（菜单不弹出）——任何形状漂移一律降级为「不贡献菜单项」返回空数组，原生菜单零污染；run 内部错误 warn 后 rethrow，由 failureLabel 呈现可见失败反馈。

## 关键行为

- **playwright 合成事件触发不了原生菜单**：`el.dispatchEvent(new MouseEvent('contextmenu'))` 不触发原生 context menu；必须走真实输入——`mousemove` 移到元素坐标 + `mousedown` 右键 + `mouseup` 右键（playwright-cli）。
- **端到端验证链路**：菜单项点击 → 右缘 dock tablist 出现 `Files`（未选）与 `Fenix 项目`（选中）→ iframe src 变 `#/projects/<p>?tab=home&path=<rel>` → iframe 内 `project-home-fileview` 渲染 markdown 文件视图；页签 iframe 与 dsh web 同源，`contentDocument` 可直接断言。

## 代码锚点

主实现与守卫测试在宿主仓 dsh-plugins（跨仓，路径相对 dsh-plugins 仓根）：

- 主实现：`fenix-dsh-dashboard-bridge/src/client/rightTab.tsx`（两段注册装配 `registerFenixRightTab`、body 工厂 `createFenixProjectsBody`、路由映射 `routeForSidebarParams`、openTab 装配 `createSidebarProjectOpener`、定位菜单图标 slot 注册）、`fenix-dsh-dashboard-bridge/src/client/locate.ts`（定位菜单项 `registerFileContextMenu`、`resolveWorkspacePath` 路径解析、`locateProjectForFile` 最长前缀命中、深链 `homeFileRouteFor`）、`fenix-dsh-dashboard-bridge/src/client/index.ts`（注入服务清单与注册接线、降级序装配）
- 守卫测试：`fenix-dsh-dashboard-bridge/tests/rightTab.test.ts`（两段注册契约钉值、params 深链路由、服务缺席 no-op 降级、openTab 装配）、`fenix-dsh-dashboard-bridge/tests/locate.test.ts`（定位命中与回退序、resolve 空数组降级、深链路由形态）

## 溯源

- 2026-11-11 dsh-sidebar-right-tab-contract-1111（spec/knowledge/_inbox/done/dsh-sidebar-right-tab-contract-1111.md） — 折叠右缘页签注册契约与定位落点：两段注册契约、useTabInfo/params 深链消费、keepMounted 保活、guide 发现入口、「侧边栏」=右缘 dock 语义定调、文件右键可定位入口面、定位运行时落点优先级与可选注入服务降级序、playwright 真实输入验证配方
