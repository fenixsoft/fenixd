# dsh 侧栏同款「新会话」按钮

<!-- knowledge: capability=dsh-new-session-button rev=1
     sources=spec/knowledge/_inbox/done/dsh-sidebar-new-session-button-spec.md -->

dashboard SPEC 列表页与详情页右上角的「新会话」按钮：外观逐项对齐 dsh web 左侧菜单同款按钮，仅 dsh web 嵌入态渲染，点击经宿主桥请求宿主新建 dsh 会话。

## 规则

- **外观单点承载**：`DshNewSessionButton` 组件是按钮外观的唯一载体，规格取证自 dsh web 左侧菜单 newSession 类（wide 展开态带文字形态）：高 38px、padding 8px 12px、描边 0.5px solid 黑 12% alpha、圆角 12px、白底、前景 alias-label-primary 色、flex 居中、内容 span gap 6px、字号 14px / 字重 500 / 行高 22px、label nowrap、图标 14px flex:none。同款按钮不自绘第二份，改样式只改组件与配套规则。
- **配色单源 theme.ts**：按钮颜色一律取 theme.ts 常量（dshAlignedTheme 浅色单源体系，不取 dsh 深色档 token 值）——`DSH_BORDER_L3`（黑 12% alpha，dsw alias-border-l3，补齐 l1/l2/l4 之间缺档）、`DSH_BG_ELEVATED`（#ffffff，alias-button-elevated-fill）、`DSH_BG_FLOATING_HOVER`（#f1f3f5，alias-button-floating-hover），三常量注释声明 DshNewSessionButton 单点消费。
- **伪类态落 global.less**：`:hover` / `:focus-visible` 伪类无法内联，落 `global.less` 的 `.dsh-new-session-button` 规则（注释含同源值出处）：hover 底换 DSH_BG_FLOATING_HOVER 同源值；焦点环 `outline: 2px solid DSH_LINK 同源值; outline-offset: -2px`——dsh 原按钮无独立 focus-visible 描边（依赖侧栏快捷键揭示机制），dashboard 移植版带独立焦点环保可达性。
- **图标内联不依赖宿主运行时**：图标为 dsh 图标注册表 new-chat-outline（viewBox 0 0 16 16、fill none、stroke currentColor、medium 权重 stroke-width 1.3），三条 path 数据内联进组件 `NEW_CHAT_PATHS` 常量，16 视窗渲染 14px；不引入宿主图标运行时。
- **移植范围限定按钮本体**：dsh 侧栏的 margin 与 `container-type:inline-size` 属侧栏布局/收窄机制，不属按钮本体，移植不带。
- **仅 embed 态渲染**：按钮只在 dsh web 嵌入态（`isEmbedMode()`）渲染，经 PageTitleBar filters 槽位落标题行右端（界面右上角）；standalone dashboard 无宿主、无法新建 dsh 会话，恒零渲染（filters 槽位空值零渲染）。挂载点仅 SPEC 列表页与 SPEC 详情页两处；详情页缺参数/加载/错误分支早退页不挂按钮。
- **点击行为与外观分离**：组件仅承载外观，点击由调用方走 `embedBridge.requestHostNewSession` postMessage 宿主桥（消息 kind 钉值 `fenix-dashboard:new-session`）——列表页传项目名（宿主以当前项目为工作区走原生新建会话，无工作区自动按项目目录建）；详情页附加「对于 <SPEC 英文名> SPEC：」前缀（SPEC 英文名是 canonical 标识，宿主经 uiWorkspace.startSession 预填新会话输入框首行）。fire-and-forget：非 embed/无宿主返回 false 且调用方无兜底 UI（按钮本就不该出现）；宿主执行结果不经通道回传，dsh 主面板视图切换本身即用户可见反馈。
- **压内联红线**：内联静态样式 + 样式表伪类状态的组合下，inline style 优先级高于一切样式表选择器——伪类规则必须 `!important` 压内联，否则 hover 被内联白底盖死且静默失效（与顶栏棘轮锁 min-width `!important` 同款先例）。
- **测试钉行纪律**：钉 import 行时语义只锚定被测图标，incidental 图标不进钉串——无关图标进钉串会在任何无关重构时误报；换图标时同步改钉行并注释缘由。

## 关键行为

- **hover/焦点验证必须实测计算值**：白底（#ffffff）与 hover 底（#f1f3f5）差异细微，截图目测难以发现 hover 失效；验证 MUST 用 `getComputedStyle` 取 hover 中的计算 background 值比对，不得只看截图。

## 代码锚点

- 主实现：`core/dashboard/static/src/components/DshNewSessionButton.tsx`（外观单点：规格内联样式、`NEW_CHAT_PATHS` 图标 path 内联）
- 配色单源：`core/dashboard/static/src/theme.ts`（`DSH_BORDER_L3` / `DSH_BG_ELEVATED` / `DSH_BG_FLOATING_HOVER` 三常量）
- 伪类态规则：`core/dashboard/static/src/global.less`（`.dsh-new-session-button` hover / focus-visible，`!important` 压内联）
- 消费方：`core/dashboard/static/src/pages/projects/list.tsx`、`core/dashboard/static/src/pages/projects/detail.tsx`（filters 槽位 embed 条件挂载）、`core/dashboard/static/src/utils/embedBridge.ts`（`requestHostNewSession` 宿主桥）、`core/dashboard/static/src/utils/embedMount.ts`（`isEmbedMode` 渲染门）
- 守卫测试：`core/dashboard/static/tests/embedBridge.test.mjs`（消息 kind 钉值）、`core/dashboard/static/tests/specInfoIcon.test.mjs`（import 行钉定不含 PlusOutlined——钉行纪律先例）

## 溯源

- 2026-11-12 dsh-sidebar-new-session-button-spec（spec/knowledge/_inbox/done/dsh-sidebar-new-session-button-spec.md） — 折叠 dsh 侧栏「新会话」按钮规格取证与落点约定：外观单点规格、theme.ts 三常量配色单源、global.less 伪类态与压内联红线、仅 embed 态渲染面、requestHostNewSession 点击分离、getComputedStyle hover 实测纪律、测试钉行纪律
