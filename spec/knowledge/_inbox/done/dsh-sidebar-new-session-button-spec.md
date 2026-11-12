# 投递：dsh web 侧栏「新会话」按钮规格取证（供 dashboard-frontend 域回填）

**来源任务**：2026-11-12 用户需求「SPEC 列表页、详情页右上角的新会话按钮，按钮样式、图标都与 dsh web 左侧菜单保持一致」。已实现：`core/dashboard/static/src/components/DshNewSessionButton.tsx`（外观单点）+ `theme.ts` 三常量 + `global.less` hover/focus 态。建议蒸馏进 `dashboard-frontend` 域（与 ui-theme / command-center-console-ui 的 theme.ts 配色单源条目相邻）。

## dsh 侧栏按钮规格（取证自 DSH 安装内 @deepseek-ai 包，2026-11-12 实测版本）

wide 展开态（带文字形态）`.hHd-Xa_newSession`（dsh-client-ui-sidebar/lib/client.js）：

- 几何：height 38px；padding 8px 12px；border **0.5px** solid alias-border-l3；border-radius alias-radius-md（浅色 12px）；display flex 居中；内容 span `.hHd-Xa_newSessionContent` gap 6px，icon 14px flex:none，label nowrap。
- 字排：font-size 14px / font-weight 500 / line-height 22px。
- 浅色 token 值（dsh-client-ui-theme/lib/client.js）：alias-border-l3=`#0000001f`；alias-button-elevated-fill=static-neutral-bluish-00=`#fff`；alias-button-floating-hover=static-neutral-bluish-75=`#f1f3f5`；alias-label-primary=neutral-bluish-1000=`#0f1115`。深色档不采用（dashboard 现架构仅浅色，theme.ts dshAlignedTheme 单源）。
- sidebar 的 margin 4px/10px 与 container-type:inline-size 是侧栏布局/收窄机制，不属按钮本体，移植时不带。
- 图标：web-frontend dist 图标注册表 **new-chat-outline**，viewBox 0 0 16 16，fill none，stroke currentColor，medium 权重 stroke-width **1.3**（Vp={regular:1, medium:1.3}）。三条 path 数据已内联进 DshNewSessionButton.tsx（NEW_CHAT_PATHS 常量），不再依赖宿主图标运行时。
- dsh 原按钮无独立 focus-visible 描边（依赖侧栏快捷键揭示机制）；dashboard 移植版补 `outline: 2px solid DSH_LINK; outline-offset: -2px` 保可达性。

## dashboard 侧落点约定（已生效）

- 配色单源：新增 `theme.ts` 常量 `DSH_BORDER_L3`（黑 12% alpha，即 dsw l3 档，补齐 l1/l2/l4 之间缺档）、`DSH_BG_ELEVATED`（#ffffff）、`DSH_BG_FLOATING_HOVER`（#f1f3f5），注释声明 DshNewSessionButton 单点消费。`:hover`/`:focus-visible` 伪类无法内联，落 `global.less` `.dsh-new-session-button` 规则（注释含同源值出处）。
- 渲染面：仅 embed 态（`?embed=1`，embedMount.isEmbedMode）渲染，经 PageTitleBar filters 槽位落标题行右端；standalone 恒零渲染（Playwright 实测 0 个）。点击走 embedBridge.requestHostNewSession postMessage，逻辑与外观分离。
- 测试耦合教训：`tests/specInfoIcon.test.mjs` 曾整行钉 `import { ..., PlusOutlined } from '@ant-design/icons'`——钉 import 行时语义应只锚定被测图标（InfoCircleOutlined）， incidental 图标进钉串会在无关重构时误报。已改为钉新行并注释缘由。
- hover 优先级教训：dsh 移植版 hover 规则首版落 global.less 无 `!important`，被组件内联 style 的白底盖死（inline style 优先级高于一切样式表选择器），hover 静默失效且**截图目测难以发现**（白与 #f1f3f5 差异细微）——内联静态样式 + 样式表伪类状态的组合，伪类规则必须 `!important` 压内联（同文件顶栏棘轮锁 min-width !important 同款先例），且 hover 验证 MUST 实测 `getComputedStyle` 在 hover 中的计算值，不得只看截图。
