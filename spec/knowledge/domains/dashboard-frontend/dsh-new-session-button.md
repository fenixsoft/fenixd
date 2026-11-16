# dsh 侧栏同款「新会话」按钮

<!-- knowledge: capability=dsh-new-session-button rev=2
     sources=spec/knowledge/_inbox/done/dsh-sidebar-new-session-button-spec.md,spec/knowledge/_inbox/done/2026-11-16-spec-list-icon-buttons-and-settings-deeplink.md -->

dashboard SPEC 列表页与详情页右上角的「新会话」按钮：38×38 方形图标钮（仅图标无文字），外观壳单点由 DshIconButton 承载，仅 dsh web 嵌入态渲染，点击经宿主桥请求宿主新建 dsh 会话。

## 规则

- **外观壳单点委托**：按钮为 38×38 方形图标钮，壳规格（描边/圆角/白底/尺寸/伪类态）全部由 `DshIconButton` 图标钮壳单点承载，本组件不重复定义壳样式（壳规则见 dsh-icon-button 页）；组件自身只保留图标 path 数据与按钮语义。
- **图标内联不依赖宿主运行时**：图标为 dsh 图标注册表 new-chat-outline（viewBox 0 0 16 16、fill none、stroke currentColor、medium 权重 stroke-width 1.3），三条 path 数据内联进组件 `NEW_CHAT_PATHS` 常量，16 视窗渲染 16px（与壳 38×38 比例平衡）；不引入宿主图标运行时。
- **语义 title「新会话」**：经壳的 title 必填通道声明，同源兼作原生 tooltip 与 `aria-label`。
- **对外契约恒定**：组件 props 恒为 `{ onClick: () => void }`，SPEC 列表页与详情页两处消费方对壳的引入零感知。
- **仅 embed 态渲染**：按钮只在 dsh web 嵌入态（`isEmbedMode()`）渲染，经统一标题栏 filters 槽位落标题行右端（界面右上角）；standalone dashboard 无宿主、无法新建 dsh 会话，恒零渲染（filters 槽位空值零渲染）。挂载点仅 SPEC 列表页与 SPEC 详情页两处；详情页缺参数/加载/错误分支早退页不挂按钮。
- **点击行为与外观分离**：组件仅承载外观，点击由调用方走 `embedBridge.requestHostNewSession` postMessage 宿主桥（消息 kind 钉值 `fenix-dashboard:new-session`）——列表页传项目名（宿主以当前项目为工作区走原生新建会话，无工作区自动按项目目录建）；详情页附加「对于 <SPEC 英文名> SPEC：」前缀（SPEC 英文名是 canonical 标识，宿主经 uiWorkspace.startSession 预填新会话输入框首行）。fire-and-forget：非 embed/无宿主返回 false 且调用方无兜底 UI（按钮本就不该出现）；宿主执行结果不经通道回传，dsh 主面板视图切换本身即用户可见反馈。
- **测试钉行纪律**：钉 import 行时语义只锚定被测图标，incidental 图标不进钉串——无关图标进钉串会在任何无关重构时误报；换图标时同步改钉行并注释缘由。

## 代码锚点

- 主实现：`core/dashboard/static/src/components/DshNewSessionButton.tsx`（`NEW_CHAT_PATHS` 图标 path 内联、语义 title）
- 外观壳：`core/dashboard/static/src/components/DshIconButton.tsx`（壳规格单点，规则见 dsh-icon-button 页）
- 消费方：`core/dashboard/static/src/pages/projects/list.tsx`、`core/dashboard/static/src/pages/projects/detail.tsx`（filters 槽位 embed 条件挂载）、`core/dashboard/static/src/utils/embedBridge.ts`（`requestHostNewSession` 宿主桥）、`core/dashboard/static/src/utils/embedMount.ts`（`isEmbedMode` 渲染门）
- 守卫测试：`core/dashboard/static/tests/embedBridge.test.mjs`（消息 kind 钉值）、`core/dashboard/static/tests/specInfoIcon.test.mjs`（import 行钉定，钉行纪律先例）

## 溯源

- 2026-11-12 dsh-sidebar-new-session-button-spec（spec/knowledge/_inbox/done/dsh-sidebar-new-session-button-spec.md） — 折叠 dsh 侧栏「新会话」按钮规格取证与落点约定：外观单点规格、theme.ts 三常量配色单源、global.less 伪类态与压内联红线、仅 embed 态渲染面、requestHostNewSession 点击分离、getComputedStyle hover 实测纪律、测试钉行纪律
- 2026-11-16 2026-11-16-spec-list-icon-buttons-and-settings-deeplink（spec/knowledge/_inbox/done/2026-11-16-spec-list-icon-buttons-and-settings-deeplink.md） — 图标态改版整体重写：wide 档（图标 +「新会话」文字 span）退役，外观壳单点迁 DshIconButton（壳规格/伪类态/压内联红线/getComputedStyle 实测纪律随迁 dsh-icon-button 页），图标 14px→16px；仅 embed 渲染与宿主桥点击分离不变，对外契约与两处消费方不变
