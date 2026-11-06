# 全站统一标题栏

<!-- knowledge: capability=unified-page-title-bar rev=6
     sources=spec/changes/unified-page-title-bar,spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md,spec/knowledge/_inbox/done/embed-titlebar-frosted-glass.md,spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md,spec/knowledge/_inbox/done/chrome-soft-solid-titlebar-1106.md,spec/knowledge/_inbox/done/v2-overview-titlebar-white-variant-1106.md -->

dashboard 前端唯一的全站内容标题栏控件（`src/components/PageTitleBar.tsx`）：标题/副标题/返回箭头/过滤项四槽位声明，双壳位（顶栏承载 / embed 行壳位承载）自动分流——页面只声明数据，禁止逐页自画同类型标题 div；v2 商业化域六页亦经 V2Page titleBar 槽位并入本控件。

## 规则

- **唯一控件与四槽位**：全部常规页与 v2 六页经 `<PageTitleBar title subtitle? back? filters? />` 声明标题元数据（props 仅此四类槽位）；过滤项与富标题是页内状态，MUST NOT 走全局路由表配置，MUST NOT 散落 `PageContainer header.extra` 或页签 `tabBarExtraContent`。
- **壳位判定收敛控件内部**：行壳位仅 embed 态启用（`embed=1`，dsh web 面板桥 iframe，无顶栏）——60px 半透明玻璃底固定标题带，满宽贴顶。standalone（含移动端）一律注册制落 ProLayout 顶栏，桌面与移动同机制、档位不同：桌面标题落品牌之后、过滤项落顶栏右上角；移动端标题与汉堡、logo 同条渲染在 `ant-pro-global-header`（顶栏缩进移动档 8 / 桌面 104），过滤项随 actionsRender 落 `right-content`（help 目录按钮实测可用）。移动端内容区不铺任何标题带——移动端标题即最顶那条带 logo/汉堡的顶栏。页面侧零环境分支。
- **embed 档毛玻璃固定标题带**：embed 档行壳位为钉视口顶的固定标题带——60px 半透明玻璃底 `DSH_BG_SOFT_GLASS`（`DSH_BG_SOFT` 的 60% 透明 rgba 形态，`theme.ts` soft 染色族同源共改，守卫测试钉族内（SOFT/GLASS/HEADER_GLASS 族）rgb 通道一致与玻璃透明度必须 <1）+ `position: sticky`（top 0、zIndex 20，仍在文档流占位——定高页 FRAME_OFFSET 族只吃高度不吃定位）+ `backdrop-filter: blur(8px)`（与 standalone 顶栏玻璃同值，附 `-webkit-` 前缀兜底旧移动端 webview；standalone 顶栏玻璃染色与布局 chrome 底色单源见 `layout-chrome-tinting`）；内容滚过标题带时透出模糊内容，观感对齐 standalone 顶栏。毛玻璃生效前提=底必须半透明：玻璃底改回实底则模糊层静默失效（无运行时报错），守卫测试钉住背景取值形态与玻璃底透明度防回潮。
- **移动端副标题隐藏**：`subtitle` 仅在非移动视口渲染，顶栏插槽（HeaderSlot）与 embed 行壳位两处同条件（`!isMobile`）；桌面顶栏与 embed 档（桌面 iframe 语境）不受影响。此为全站控件行为，七个常规页与 v2 六页移动端同步生效。
- **声明-注册-插槽机制**：顶栏壳位采用注册制——控件在挂载时把 meta 登记进模块级注册表（`pageTitleBarStore`），布局层（`app.tsx`）经标题区插槽（`headerContentRender`）与过滤项插槽（`actionsRender`）消费渲染；meta 任一字段变化即重登记，注销与注册由同一 effect 的 cleanup 承担（CSR 下 layout effect 注册先于绘制，路由切换瞬间旧页注销与新页注册同批 flush，插槽无空窗闪烁）。
- **壳位单源互斥**：同一 meta 任一时刻只渲染于一处壳位——行壳位时不注册、顶栏壳位时不渲染行本体；视口宽度跨 768px 阈值翻转时旧壳位节点随 effect 清理，MUST NOT 双标题并存或切换后残留。顶栏无注册内容时渲染空（不残留上一页标题）。
- **形态基准**：标题 18px/700、副标题 12px 三级灰与标题基线对齐、副标题计数 `tabular-nums`（`TitleBarNum`）、过滤项 antd 28px small 档、行壳位定高 embed 60 底缘细线；配色全部取 `theme.ts` 单源，零新色。
- **v2 六页并入**：v2 商业化域六页不自画标题带（V2TitleBand/V2BackArrow 不存在，守卫 `tests/v2TitleBarGuard.test.mjs` 钉死勿回填），标题元数据一律经 `<V2Page titleBar={<PageTitleBar … />}>` 声明进本控件。槽位渲染在 `.v2-page` 直下、`.v2-inner` 之前：行壳位标题带满宽贴顶（sticky 钉视口顶依赖此结构，进 `.v2-inner` 会被居中收窄 + 页顶内边距架空，实测移动端内缩 14px 即此因）；standalone 桌面控件本体 null，标题经注册表落 ProLayout 顶栏插槽（副标题基线同行）。v2 侧壳与变体契约见 `v2-commercial-ui`。
- **内容区无页头**：7 个常规页（跨项目概览、项目列表、SPEC 详情、设置、运维、指挥中心、帮助）均不渲染 PageContainer 页头，内容直接从首屏卡片/表格起；PageContainer 本体保留（内容区留白 token 单源仍由其承载，见 `page-container-chrome`），但必须传 `title={false}` 显式抑制自动页头——不传 title 时 ProLayout 会从路由上下文兜底取路由名渲染页头，与标题栏双标题并存。v2 六页经 V2Page 壳跳过 PageContainer，同语义。
- **过滤项统一右上落位**：页级过滤控件全部收编进 `filters` 槽位，落位随壳位（顶栏右上角 / 行右端）——设置页「作用域」Select、运维页处置链页签「全部项目」Select（仅页签激活时渲染）、指挥中心「全部项目」+时间窗双 Select（时间窗仅 org 屏显隐逻辑随迁页内条件渲染）。
- **返回箭头与富标题**：项目列表页返回箭头（回 `/overview`）走 `back` 槽位渲染在标题左侧；SPEC 详情页富组合（返回箭头 + SPEC 名 + 模式/状态 Tag + 快速切换下拉）作为 ReactNode 整体传入 `title` 槽位——控件对富节点透明不拆解，快速切换下拉保持渲染在 SPEC 名旁（`spec-detail-quick-switch` 契约延续）。
- **顶栏无面包屑**：顶栏右侧全局面包屑在任何视口宽度均不渲染（`HeaderCrumb` 组件、`crumbItems` 映射与 `global-header-crumb` 样式锚点不复存在），位置指示职责由顶栏页面标题承担；顶栏右上角只渲染该页过滤项（无过滤项页右上角为空）。
- **定高偏移口径**：定高页扣减常数为双档并经 playwright 实拍校准，对象仅两类——`pageChrome.ts` 项目详情页框（desktop 150/142、mobile 198/142）与指挥中心 `SCREEN_CHROME_OFFSET`（standalone 126 / embed 118）。回校后定高卡体 `calc(100vh - offset)` 恰满视口——右栏自滚、无第二根滚动条、无视口下空带。帮助/设置页为文档级滚动页，不持定高偏移常数（滚动形态见 `document-scroll-unify`）；其目录/菜单 sticky 钉位常数（standalone 56 / embed 60）与本栏高度联动。改标题行或内容区顶带任何内边距必须回校全部联动常数并重新实拍。
- **豁免面**：现存豁免仅两类——`layout:false` 脱壳页（SPEC 协作拓扑大屏）无壳层不适用；菜单「项目」父项落点 `/projects` 的兜底占位页（`PagePlaceholder`，项目列表就绪后自动重定向、仅空列表时兜底可见）保留其占位页头不迁移。v2 六页不在豁免面（titleBar 槽位并入）。
- **非 embed 布局基线不变**：除标题栏迁移与面包屑退役外，ProLayout 侧栏结构、菜单数据、页签、主题 token 零改动；内容区左右留白仍走 `paddingInlinePageContainerContent` 单源。
- **界面原型为 UI 真相源**：全部界面形态（顶栏排布、标题行尺寸、过滤项密度、行壳位同构关系）以已批准入库的高保真原型为准（standalone.html 独立形态 / embed.html 嵌入形态，原型持久保留于 SPEC 归档目录）；实现与评审必须对照原型，原型与文字描述冲突时以原型为准并升级用户裁决。

## 关键行为

- dsh 侧零改造：embed 契约仍由查询参数承载（`embed`/`apiBase` 语义不变），标题行由本控件在嵌入态自动内嵌，dsh web 面板桥无需任何变更。
- 副标题承载：概览「监控 N 个项目」、项目列表「共 N 个 SPEC」、运维「跨项目 Administrator 活动与处置链观测」（罩三页签）随标题渲染在标题栏，仅桌面视口可见（移动端隐藏）；无副标题页（设置、指挥中心、帮助）不渲染副标题槽位。
- 守卫契约：`pageTitleBar.test.mjs` / `embedMount.test.mjs` 钉移动顶栏 + embed 行壳位的双壳位新契约，页壳位结构变化须两测试同步钉版。

## 溯源

- 2026-11-04 unified-page-title-bar（spec/changes/unified-page-title-bar/） — 新增本能力：四槽位统一控件与双壳位自动分流（顶栏注册-插槽 / embed·移动端内容区首行 48px）、PageContainer 页头全站退役（本体保留 + `title={false}`）、过滤项收编、面包屑全局退役、富标题整体迁移、定高偏移五处常数 embed 双档回校、脱壳大屏与占位页豁免
- 2026-11-05 dashboard-ops-tabs-chain-merge（spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md） — 处置链独立页并入运维页三页签随迁：常规页清单 8→7、处置链单项目 Select 例改运维页页签条件渲染、运维页副标题改罩三页签（原处置链页副标题条目消失）
- 2026-11-05 embed-titlebar-frosted-glass（spec/knowledge/_inbox/done/embed-titlebar-frosted-glass.md） — embed 档行壳位升格固定标题带毛玻璃：60px 半透明玻璃底 DSH_BG_SOFT_GLASS（DSH_BG_SOFT 60% 透明形态，同源共改守卫）+ sticky 钉视口顶 + backdrop blur(8px)（-webkit- 兜底），移动端档 48px 白底随流与 sticky 占位语义不变；行壳位旧「48px 白底」单档表述改写为双档形态
- 2026-11-05 settings-help-document-scroll-unify（spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md） — 定高偏移口径改写：settings/help `FRAME_OFFSET`（standalone 56 / embed 48）条目随两页转文档级滚动消失，现存对象仅项目详情页框与指挥中心 SCREEN_CHROME_OFFSET；回校纪律扩及帮助/设置目录/菜单 sticky 钉位常数（56/60）联动
- 2026-11-06 chrome-soft-solid-titlebar-1106（spec/knowledge/_inbox/done/chrome-soft-solid-titlebar-1106.md） — 行壳位玻璃守卫表述改钉 soft 染色族（SOFT/GLASS/HEADER_GLASS 族 rgb 通道一致、玻璃透明度必须 <1）；布局级 chrome 染色（顶栏玻璃双档/侧栏实底/边框三处同源）拆分至新页 layout-chrome-tinting
- 2026-11-06 v2-overview-titlebar-white-variant-1106（spec/knowledge/_inbox/done/v2-overview-titlebar-white-variant-1106.md） — v2 六页经 V2Page titleBar 槽位并入统一标题栏（v2 自画标题带与豁免面退役，新增 v2 并入条款）；行壳位收敛 embed 单档——移动端 48px 行壳位废除，移动端标题并入 ProLayout 顶栏（汉堡+logo+标题同条、缩进档 104→8、filters 落 right-content）；副标题移动端隐藏（顶栏插槽与行壳位两处同条件）
