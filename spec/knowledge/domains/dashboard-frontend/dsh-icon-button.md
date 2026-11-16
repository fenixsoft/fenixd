# dsh 图标钮壳（DshIconButton）

<!-- knowledge: capability=dsh-icon-button rev=1
     sources=spec/knowledge/_inbox/done/2026-11-16-spec-list-icon-buttons-and-settings-deeplink.md -->

dashboard 标题栏方形图标按钮的统一外壳：38×38 仅图标无文字形态，外观规格单点承载，语义与点击行为由调用方声明。现役消费方为「新会话」与「配置」两钮。

## 规则

- **壳规格单点**：`DshIconButton` 是标题栏图标钮外观的唯一载体——38×38 方形（box-sizing border-box、padding 0）、0.5px `DSH_BORDER_L3` 描边、圆角 12px、`DSH_BG_ELEVATED` 白底、`DSH_TEXT` 前景、flex 居中、flex:none，`className="dsh-icon-button"` 供样式表伪类态挂靠。同款图标钮不自绘第二份，改样式只改壳组件与配套规则。
- **尺寸基准（dsh 同构读法）**：形态取证自 dsh 侧栏 newSession 类——wide 展开态提供描边/圆角/底色/高度基线；图标态为 dsh 侧栏窄档图标态（36px 方形、padding 0）的同构读法，保留描边与白底（dashboard 白底标题栏上需可见），尺寸取 38 与 wide 档同高。dsh 侧栏的 margin 与 `container-type:inline-size` 属侧栏布局/收窄机制，不属按钮本体，移植不带。
- **props 契约**：`onClick` 与 `title` 均必填、无缺省——图标钮无可见文字，无障碍名全靠 title，title 同源兼作原生 tooltip 与 `aria-label`。图标内容由调用方经 children 传入（内联 svg、antd 图标等），壳不感知图标体系与尺寸。
- **配色单源 theme.ts**：壳颜色一律取 theme.ts 常量（dshAlignedTheme 浅色单源体系，不取 dsh 深色档 token 值）——`DSH_BORDER_L3`、`DSH_BG_ELEVATED`、`DSH_TEXT`；伪类 hover 底取 `DSH_BG_FLOATING_HOVER` 同源值。
- **伪类态落 global.less**：`:hover` / `:focus-visible` 伪类无法内联，落 `global.less` 的 `.dsh-icon-button` 规则：hover 底 `#f1f3f5`（DSH_BG_FLOATING_HOVER 同源值）、必须 `!important`；焦点环 `outline: 2px solid #4176e6`（DSH_LINK 同源值）、offset -2px——dsh 原按钮无独立 focus-visible 描边（依赖侧栏快捷键揭示机制），dashboard 移植版带独立焦点环保可达性。
- **压内联红线**：内联静态样式 + 样式表伪类状态的组合下，inline style 优先级高于一切样式表选择器——伪类规则必须 `!important` 压内联，否则 hover 被内联白底盖死且静默失效（与顶栏棘轮锁 min-width `!important` 同款先例）。

## 关键行为

- **hover/焦点验证必须实测计算值**：白底（#ffffff）与 hover 底（#f1f3f5）差异细微，截图目测难以发现 hover 失效；验证 MUST 用 `getComputedStyle` 取 hover 中的计算 background 值比对，不得只看截图。

## 代码锚点

- 主实现：`core/dashboard/static/src/components/DshIconButton.tsx`（壳规格内联样式单点）
- 伪类态规则：`core/dashboard/static/src/global.less`（`.dsh-icon-button` hover / focus-visible，`!important` 压内联）
- 配色单源：`core/dashboard/static/src/theme.ts`（`DSH_BORDER_L3` / `DSH_BG_ELEVATED` / `DSH_TEXT` / `DSH_BG_FLOATING_HOVER` / `DSH_LINK`）
- 消费方：`core/dashboard/static/src/components/DshNewSessionButton.tsx`（「新会话」钮）、`core/dashboard/static/src/pages/projects/list.tsx`（「配置」钮）
- 守卫测试：`core/dashboard/static/tests/specListConfigButton.test.mjs`（壳规格、图标态无文字、伪类选择器迁移钉定）

## 溯源

- 2026-11-16 2026-11-16-spec-list-icon-buttons-and-settings-deeplink（spec/knowledge/_inbox/done/2026-11-16-spec-list-icon-buttons-and-settings-deeplink.md） — 新建页：标题栏图标钮壳单点抽出（38×38 规格、title 双源必填、dsh 窄档同构尺寸基准、theme.ts 配色单源）；伪类态选择器自 `.dsh-new-session-button` 迁 `.dsh-icon-button`，压内联红线与 getComputedStyle hover 实测纪律随壳迁移
