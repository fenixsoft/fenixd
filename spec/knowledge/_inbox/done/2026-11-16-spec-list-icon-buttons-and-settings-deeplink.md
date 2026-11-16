# SPEC 列表页标题栏按钮图标态改版 + 配置页深链预选（2026-11-16）

## 背景

用户需求（2026-11-16）：SPEC 列表页右上角新增「配置」按钮，进入配置页且作用域自动设定为该工程；与既有「新会话」按钮并排，两按钮都只显示图标不显示文字。已直接实现（不走 SPEC），本文为知识候选，供 distill 车道折叠进 dashboard-frontend 域。

## 结论（当前事实）

- **DshIconButton 壳单点**：`core/dashboard/static/src/components/DshIconButton.tsx` 为 38×38 方形图标钮壳（0.5px DSH_BORDER_L3 描边、radius 12、DSH_BG_ELEVATED 白底、flex 居中、`className="dsh-icon-button"`）；props `onClick` 与 `title` 均必填，title 同源兼作原生 tooltip 与 `aria-label`（图标钮无可见文字，无障碍名全靠它）。同构基准：dsh 侧栏窄档图标态（36px 方形、padding 0），尺寸取 38 与 wide 档同高。
- **DshNewSessionButton 图标态**：`core/dashboard/static/src/components/DshNewSessionButton.tsx` 已退役旧 wide 档（14px 图标 + 「新会话」文字 span），改经 DshIconButton 壳只渲染 16×16 new-chat-outline 内联 svg（viewBox 0 0 16 16、stroke-width 1.3，图标 14→16px 与壳比例平衡），title「新会话」。对外契约 `{ onClick: () => void }` 不变，list.tsx 与 detail.tsx 两处消费方零改动。
- **伪类随壳迁移**：`core/dashboard/static/src/global.less` 悬停/焦点规则选择器 `.dsh-new-session-button` → `.dsh-icon-button`（hover `#f1f3f5 !important`、focus-visible `outline: 2px solid #4176e6` offset -2px，值不变）。压内联红线沿用：壳内联白底优先级盖死伪类，hover 必须 `!important`。
- **列表页双钮**：`core/dashboard/static/src/pages/projects/list.tsx` filters 槽改 `<>` 片段——embed 条件渲染 DshNewSessionButton（语义不变）+ 恒渲染 `<DshIconButton title="配置">`（SettingOutlined 16px），配置钮恒居槽位最右：standalone 档独占顶栏右上角、embed 档落新会话按钮右侧，两态位置一致。
- **配置深链**：配置钮 `history.push(\`/settings?project=${encodeURIComponent(name)}\`)`——hash 路由下 query 位于 `location.hash` 的 `?` 之后（读法同 activities 页 initialTab 先例）。dashboard 内部导航不走宿主桥，故配置钮两态恒渲染（对比：新会话钮仅 embed 态渲染）。
- **配置页预选**：`core/dashboard/static/src/pages/settings/index.tsx` 新增 `initialScopeFromUrl()`（该参数唯一读侧）：`?project=` 非空即 `{scope:'project', project}`，空/缺省回落用户级。经 `useState(initialScopeFromUrl)` 惰性初始化单次取值，scope/project 两 state 共用同一 `initialScope`，仅首屏生效——此后作用域由受控 Select 驱动（切档丢弃确认弹窗不变），URL 不回写、不参与后续流转。
- **守卫测试**：`core/dashboard/static/tests/specListConfigButton.test.mjs`（10 用例）钉双钮接线、深链、图标态无文字、壳规格、读参预选、global.less 迁移；`tests/specInfoIcon.test.mjs` 钉行随 import 行更新（加 SettingOutlined）。

## 证据

- `npm test`：481/481 pass（tests/*.test.mjs 零依赖 node:test）。
- `npm run build`：exit 0，dist/ 产出（umi max 构建含 TS 类型检查）。
- 契约不变面：detail.tsx 新会话钮消费零改动；settings 保存/切档交互零改动；后端零改动。

## 更新目标页（distill 时）

`spec/knowledge/domains/dashboard-frontend/dsh-new-session-button.md`（rev=1，wide 档外观契约已过时——文字 span 退役、壳单点迁 DshIconButton、图标 16px、选择器迁 .dsh-icon-button）。
