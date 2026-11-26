# 设置页签合并：界面风格+界面语言 -> 界面（2026-11-26 用户指令）

## 背景
2026-11-26 用户指令：将 fenix 配置中「界面语言」和「界面风格」合并为「界面」，并且将「界面」移动到设置的第一项。

## 结论（当前事实）
- 设置页菜单第一项为「界面」页签：原「界面风格」「界面语言」两页签合并迁入；标签单源为 core/dashboard/static/src/pages/settings/pageLabels.ts 的 interface 键（'settings.tab.interface'），theme/locale 两键已移除。
- 「界面」页签渲染两面板堆叠（仲裁页签先例）：主题面板（浏览器 localStorage `fenix.theme`，三档 system/light/dark、缺省跟随系统；嵌入 dsh web 时跟随宿主并锁定） + 语言面板（localStorage `fenix.locale`，三档 system/zh-CN/en-US、缺省跟随系统；即时生效无需刷新，未翻译文案回退中文）。
- 菜单全集与顺序标签单源：pageLabels.ts PAGE_LABELS + index.tsx BASE_MENU_ITEMS（interface 首项）；activeKey 缺省选中仍为 'llm'（菜单顺序变化不改缺省选中页签）。
- 文案：zh-CN.ts 'settings.tab.interface': "界面"；en-US.ts "Interface"（en 与 zh 对称）。

## 证据
- core/dashboard/static/src/pages/settings/index.tsx：BASE_MENU_ITEMS 首项 `{ key: 'interface', ... }`；渲染分支 `activeKey === 'interface'` 内 `<ThemePanel />` + `<LocalePanel />` 两面板堆叠。
- docs/help/09-config.md：面板映射表「界面」合并行。
- 待回填知识页：spec/knowledge/domains/dashboard-frontend/settings-page.md（菜单全集行、theme/locale 两子项规则行、控件路径行需按现行代码改写）；ui-theme.md 与 locale-i18n.md 的「界面风格」/「界面语言」页签入口描述同样需按现行菜单收敛。
- 排查：SyncFromUserButton.tsx 仅按 PageKey 索引 PAGE_LABELS（theme/locale 无专用分支）；embedMount.ts 的 ?theme= / ?locale= 参数为面板参数、非页签键；tests/ 无页签键引用。
