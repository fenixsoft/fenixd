# SPEC 列表页标题栏按钮组

<!-- knowledge: capability=spec-list-titlebar-buttons rev=1
     sources=spec/knowledge/_inbox/done/2026-11-16-spec-list-icon-buttons-and-settings-deeplink.md -->

SPEC 列表页统一标题栏 filters 槽位（标题行右端）的按钮编排：「新会话」与「配置」双钮并排，均为 38×38 仅图标形态（壳规格见 dsh-icon-button 页）。

## 规则

- **filters 槽片段双钮**：列表页 filters 槽以 `<>` 片段承载双钮——「新会话」钮 embed 条件渲染（渲染门与宿主桥点击规则归 dsh-new-session-button 页单源，本页只管编排位）+「配置」钮恒渲染。
- **配置钮两态恒渲染**：「配置」钮为 dashboard 内部页面导航，不经宿主桥，embed 与 standalone 两态恒渲染（对比：「新会话」钮仅 embed 态渲染，standalone 无宿主恒零渲染）。
- **摆位恒居最右**：配置钮恒居 filters 槽位最右——standalone 档独占标题栏右上角，embed 档落新会话按钮右侧，两态位置一致。
- **配置钮外观**：DshIconButton 壳 + SettingOutlined 图标 fontSize 16，title「配置」。
- **点击深链预选**：点击 `history.push('/settings?project=<encodeURIComponent(项目名)>')` 进入配置页（hash 路由下 query 随 hash 传递）；配置页首屏按 URL 参数预选项目级作用域并选中该工程——读侧单点为配置页 `initialScopeFromUrl`，预选规则归 settings-page 页单源。

## 代码锚点

- 主实现：`core/dashboard/static/src/pages/projects/list.tsx`（PageTitleBar filters 槽双钮编排与深链 push）
- 深链读侧：`core/dashboard/static/src/pages/settings/index.tsx`（`initialScopeFromUrl` 唯一读侧）
- 守卫测试：`core/dashboard/static/tests/specListConfigButton.test.mjs`（双钮接线、深链、图标态无文字、读参预选）

## 溯源

- 2026-11-16 2026-11-16-spec-list-icon-buttons-and-settings-deeplink（spec/knowledge/_inbox/done/2026-11-16-spec-list-icon-buttons-and-settings-deeplink.md） — 新建页：SPEC 列表页标题栏双钮编排入库（embed 条件渲染新会话 + 恒渲染配置钮、配置钮恒居最右两态位置一致、SettingOutlined 16px 图标态、`/settings?project=` 深链接线）
