# Design: unified-page-title-bar

## Context

dashboard 前端（umi + ProLayout mix 布局 + antd v6）现状：8 个常规页各自以 `PageContainer header={{ title, subTitle, extra }}` 在内容区顶部渲染标题行（56px 页头占位）；顶栏左侧为 `HeaderTitle` 品牌（`app.tsx:104`），右侧为 `actionsRender` 注入的全局面包屑 `HeaderCrumb`（`app.tsx:96/154`）；页级过滤控件散落两处形态（settings/chain 在 `header.extra`，指挥中心在 Tabs `tabBarExtraContent`）。embed=1（dsh web 面板桥）隐藏侧栏与顶栏，现靠 PageContainer 页头在嵌入态显示标题。

本变更经原型确认环定稿（2026-11-04 用户明示认可）：**界面原型（UI 真相源）= `prototype/`**（standalone.html + embed.html + 双整页截图，vendor 层真组件、具约束力）。

**设计约束以 DESIGN.md 为准**（界面设计宪法，当前摘录已注入原型生成）：页面标题 18px/700（字号阶 16-18 档）、字号阶 11/12/13/14/16/18/28、配色单源（theme.ts 宿主对齐覆盖表）、静态渲染红线（零动画）、数据墨水优先、移动端「改布局不改宽度」。本变更不偏离宪法任何条款；标题**载体**从内容区迁顶栏属现状变化，宪法「页面标题 18px/700」条款数值语义不变，宪法回写由用户定稿事件走修正案程序（本 SPEC 不直写宪法）。

## Goals / Non-Goals

**Goals**
- 统一标题栏控件（单组件）承载全站 8 个常规页的标题/副标题/返回箭头/过滤项，双壳位（顶栏 / 内容区首行）自动分流。
- standalone：标题进顶栏（品牌之后）、过滤项进顶栏右上角、内容区页头退役；面包屑全局退役。
- embed 与移动端：控件自动落内容区首行，dsh 侧零改造。
- 定高页偏移常数回校，不产生第二滚动条。

**Non-Goals**
- 不改 ProLayout 侧栏、菜单数据、路由配置。
- 不改 dashboard 后端 API 与 dsh web（dsh-plugins 仓）任何代码。
- 不动 SPEC 协作拓扑大屏（`layout:false` 脱壳页）。
- 不做暗色主题适配（theme.ts 已预留，非本变更范围）。

## Decisions

**D1 统一控件 = 单组件 + 壳位内聚**：新建 `src/components/PageTitleBar.tsx`，props 仅四槽位（`title` ReactNode、`subtitle?` ReactNode、`back?` 回调、`filters?` ReactNode）。壳位判定（`isEmbedMode() || 视口 <768` → 行壳位；否则顶栏壳位）收敛在控件内部。*备选*：每页自渲染两种形态（否——正是用户点名禁止的「每页画一个相类似的 div」）；全局路由表配标题（否——过滤项/富标题是页内状态，路由表装不下）。

**D2 顶栏挂载机制：声明-注册-插槽**。页面以 `usePageTitleBar(meta)`（context 注册，或等价轻量单源）在挂载时把 `{title, subtitle, back, filters}` 报给布局层；`app.tsx` 布局配置消费：品牌区之后追加标题区渲染（ProLayout `headerContentRender` 或等价 header 插槽属性，实现者按 antd v6 / ProLayout 实际 API 选型），过滤项渲染进 `actionsRender`（替换原 `HeaderCrumb` 槽位）。*理由*：ProLayout 的 header 插槽在布局配置层，页内组件无法直接塞节点，须经共享状态桥接；注册制让页面保持「只声明数据」。**硬约束**：顶栏无该页注册内容时渲染空（不残留上一页内容）——注册须随卸载清理，路由切换即换页换标题。

**D3 面包屑直接退役不保留**（用户裁决）：`HeaderCrumb` 组件、`crumbItems` 映射、`global-header-crumb` 样式锚点及 `global.less` 窄屏隐藏规则一并清理。*备选*：面包屑保留在过滤项左侧（用户已否）；移入行壳位（否——行壳位标题已表达位置）。

**D4 PageContainer 页头摘除方式**：各页 `PageContainer` 保留容器本体（留白 token 单源仍由其承载，见 `page-container-chrome` 能力页），仅摘除 `header` 相关 props（`header={{...}}` / `breadcrumbRender` / `extra`），等价于 `header={false}` 形态。**不**把 PageContainer 整体换成裸 div——留白单源与未来 ProLayout token 联动依赖它。

**D5 定高偏移回校表**（改页头任何内边距必须回校为既有纪律，本变更是页头消失级别的回校）：

| 常数 | 现值 | 新值口径 |
|---|---|---|
| `SETTINGS_FRAME_OFFSET`（settings/index.tsx） | standalone 124 / embed 68 | standalone = 顶栏 56 + heading 尾带（页头 56 消失，实测校准）；embed = 标题行 48 + 原尾带 |
| `HELP_FRAME_OFFSET`（help/index.tsx） | standalone 112 / embed 56 | standalone = 顶栏 56；embed = 48 |
| `pageChrome.ts` 页框口径 | 含 PageContainer 页头 | 页头占位移除，重算并保注释口径链 |
| `SCREEN_CHROME_OFFSET` 族（command-center shared） | 含页头 | 同步重算 |

实拍校准法沿用（playwright 命名会话截图实测，`SCREEN_CHROME_OFFSET=182` 先例）；注释须互指新旧口径。

**D6 富标题（详情页）整体迁移**：详情页 `headerCfg` 的富组合（返回 + SPEC 名 + Tag + 快速切换下拉）作为 ReactNode 整体传入 `title` 槽位——控件对富节点透明，不拆解重组。*理由*：spec-detail-quick-switch 契约（下拉在 SPEC 名旁）与 Tag wrap 语义在节点内部自洽，控件无需感知。

**D7 移动端行壳位复用 embed 形态**：`<768` 与 embed 同走行壳位——一份代码两个触发条件，不另做移动端专属布局；富标题 wrap（mobile-detail-header-density 契约）在行壳位内继续成立。顶栏 `<768` 维持纯品牌（现状 crumb 已窄屏隐藏，退役后无残留）。

**D8 指挥中心过滤迁顶栏**：`tabBarExtraContent` 双 Select（项目 + 时间窗）状态与联动逻辑原样上移到 `filters` 槽位，页签行 extra 槽位移除。时间窗 Select 仅 org 屏有意义的条件显隐逻辑随迁（控件 `filters` 为 ReactNode，页内自行条件渲染）。

## Risks / Trade-offs

- [ProLayout header 插槽 API 与预期不符（mix 布局下 headerContentRender 定位/宽度行为）] → 实现前先在真实布局冒烟验证插槽定位；不达即换用布局 token / DOM 定位的备选并在 design 补记，场景断言锚定视觉结果而非 API 名。
- [注册制时序竞态：页面卸载与新页注册的闪烁/残留] → 注册清理走同一 effect 的 cleanup；顶栏渲染兜底「无注册渲染空」；场景覆盖路由切换瞬间无上一页标题残留。
- [定高回校误差引发第二滚动条回归] → 延续实拍校准 + `pageChrome.test.mjs`/`helpPageScroll.test.mjs` 既有守卫更新为新口径；两形态（standalone/embed）×两页（settings/help）逐一实拍。
- [embed 契约回归（dsh 面板桥依赖页面内容头）] → `dashboard-embed-mount` delta 已改写契约；embedMount.test.mjs 断言更新；dsh 侧零改动由「参数语义不变」保证。
- [移动端顶栏标题被否决后的观感空洞] → 顶栏纯品牌是现状形态（crumb 窄屏本就隐藏），无新增空洞；行壳位承接全部信息。

## Migration Plan

1. 控件与顶栏插槽先行（含面包屑退役），页面逐页迁移（每页：摘页头 → 声明控件 → 偏移回校）。
2. 全量 rebuild + reload 验证纪律（hash 路由 goto 不重载文档，必须整页 reload——`page-container-chrome` 能力页）；playwright 命名会话实拍 standalone + embed 两形态逐页对照原型。
3. 回滚 = revert 本变更分支（无数据迁移、无 API 变更、dsh 侧零依赖，revert 即回到现状）。

## Open Questions

- 无——界面形态已由原型定稿收敛；实现期 API 级选型（D2 备选）授权实现者按真实 ProLayout 行为就地裁决，不升级用户。
