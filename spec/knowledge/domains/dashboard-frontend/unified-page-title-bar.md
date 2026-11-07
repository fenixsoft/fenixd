# 全站统一标题栏

<!-- knowledge: capability=unified-page-title-bar rev=12
     sources=spec/changes/unified-page-title-bar,spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md,spec/knowledge/_inbox/done/embed-titlebar-frosted-glass.md,spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md,spec/knowledge/_inbox/done/chrome-soft-solid-titlebar-1106.md,spec/knowledge/_inbox/done/v2-overview-titlebar-white-variant-1106.md,spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md,spec/changes/add-spec-subtitle-and-row-click,spec/changes/add-titlebar-subtitle-stacked -->

dashboard 前端唯一的全站内容标题栏控件（`src/components/PageTitleBar.tsx`）：标题/副标题/返回箭头/过滤项四槽位声明，双壳位（顶栏承载 / embed 行壳位承载）自动分流——页面只声明数据，禁止逐页自画同类型标题 div；v2 商业化域六页亦经 V2Page titleBar 槽位并入本控件。

## 规则

- **唯一控件与四槽位**：全部常规页与 v2 六页经 `<PageTitleBar title subtitle? back? filters? />` 声明标题元数据（props 仅此四类槽位）；过滤项与富标题是页内状态，MUST NOT 走全局路由表配置，MUST NOT 散落 `PageContainer header.extra` 或页签 `tabBarExtraContent`。
- **壳位判定收敛控件内部**：行壳位仅 embed 态启用（`embed=1`，dsh web 面板桥 iframe，无顶栏）——60px 半透明玻璃底固定标题带，满宽贴顶。standalone（含移动端）一律注册制落 ProLayout 顶栏，桌面与移动同机制、档位不同：桌面标题落品牌之后、过滤项落顶栏右上角；移动端标题与汉堡、logo 同条渲染在 `ant-pro-global-header`（顶栏缩进移动档 8 / 桌面 104），过滤项随 actionsRender 落 `right-content`（help 目录按钮实测可用）。移动端内容区不铺任何标题带——移动端标题即最顶那条带 logo/汉堡的顶栏。页面侧零环境分支。
- **embed 档毛玻璃固定标题带**：embed 档行壳位为钉视口顶的固定标题带——60px 半透明玻璃底 `DSH_BG_SOFT_GLASS`（`DSH_BG_SOFT` 的 60% 透明 rgba 形态，`theme.ts` soft 染色族同源共改，守卫测试钉族内（SOFT/GLASS/HEADER_GLASS 族）rgb 通道一致与玻璃透明度必须 <1）+ `position: sticky`（top 0、zIndex 20，仍在文档流占位——定高页 FRAME_OFFSET 族只吃高度不吃定位）+ `backdrop-filter: blur(8px)`（与 standalone 顶栏玻璃同值，附 `-webkit-` 前缀兜底旧移动端 webview；standalone 顶栏玻璃染色与布局 chrome 底色单源见 `layout-chrome-tinting`）；内容滚过标题带时透出模糊内容，观感对齐 standalone 顶栏。毛玻璃生效前提=底必须半透明：玻璃底改回实底则模糊层静默失效（无运行时报错），守卫测试钉住背景取值形态与玻璃底透明度防回潮。
- **移动端副标题与返回箭头隐藏**：`subtitle` 与 `back` 返回箭头仅在非移动视口渲染，顶栏插槽（HeaderSlot）与 embed 行壳位两处同条件（`!isMobile`；箭头隐藏为 2026-11-06 用户指令，移动端导航走系统返回/菜单）；桌面顶栏与 embed 档（桌面 iframe 语境）不受影响。此为全站控件行为，七个常规页与 v2 六页移动端同步生效。
- **声明-注册-插槽机制**：顶栏壳位采用注册制——控件在挂载时把 meta 登记进模块级注册表（`pageTitleBarStore`），布局层（`app.tsx`）经标题区插槽（`headerContentRender`）与过滤项插槽（`actionsRender`）消费渲染；meta 任一字段变化即重登记，注销与注册由同一 effect 的 cleanup 承担（CSR 下 layout effect 注册先于绘制，路由切换瞬间旧页注销与新页注册同批 flush，插槽无空窗闪烁）。
- **壳位单源互斥**：同一 meta 任一时刻只渲染于一处壳位——行壳位时不注册、顶栏壳位时不渲染行本体；视口宽度跨 768px 阈值翻转时旧壳位节点随 effect 清理，MUST NOT 双标题并存或切换后残留。顶栏无注册内容时渲染空（不残留上一页标题）。
- **形态基准**：标题 18px/700、副标题 12px 三级灰与标题基线对齐、副标题计数 `tabular-nums`（`TitleBarNum`）、过滤项 antd 28px small 档、行壳位定高 embed 60 底缘细线；配色全部取 `theme.ts` 单源，零新色。
- **v2 六页并入**：v2 商业化域六页不自画标题带（V2TitleBand/V2BackArrow 不存在，守卫 `tests/v2TitleBarGuard.test.mjs` 钉死勿回填），标题元数据一律经 `<V2Page titleBar={<PageTitleBar … />}>` 声明进本控件。槽位渲染在 `.v2-page` 直下、`.v2-inner` 之前：行壳位标题带满宽贴顶（sticky 钉视口顶依赖此结构，进 `.v2-inner` 会被居中收窄 + 页顶内边距架空，实测移动端内缩 14px 即此因）；standalone 桌面控件本体 null，标题经注册表落 ProLayout 顶栏插槽（副标题基线同行）。v2 侧壳与变体契约见 `v2-commercial-ui`。
- **内容区无页头**：7 个常规页（跨项目概览、项目列表、SPEC 详情、设置、运维、指挥中心、帮助）均不渲染 PageContainer 页头，内容直接从首屏卡片/表格起；PageContainer 本体保留（内容区留白 token 单源仍由其承载，见 `page-container-chrome`），但必须传 `title={false}` 显式抑制自动页头——不传 title 时 ProLayout 会从路由上下文兜底取路由名渲染页头，与标题栏双标题并存。v2 六页经 V2Page 壳跳过 PageContainer，同语义。
- **过滤项统一右上落位**：页级过滤控件全部收编进 `filters` 槽位，落位随壳位（顶栏右上角 / 行右端）——设置页「作用域」Select、运维页处置链页签「全部项目」Select（仅页签激活时渲染）、指挥中心「全部项目」+时间窗双 Select（时间窗仅 org 屏显隐逻辑随迁页内条件渲染）。移动端 filters 槽位即「标题栏右侧控件位」的单一定点——控件上移标题栏的需求一律经 filters 槽位声明（standalone 落顶栏右上角 FiltersSlot 天然右对齐、embed 行壳位 FiltersNode `marginLeft:auto` 落行右端），不在内容区手画按钮行（帮助页「文档目录」按钮移动端即此定式，与 v2 帮助目录按钮同构）；窄幅放不下的过滤组整组下放内容区且不注册槽位（指挥中心双下拉移动端 `filters={undefined}`、落内容区首行）。
- **返回箭头与富标题**：项目列表页返回箭头（回 `/overview`）走 `back` 槽位渲染在标题左侧；SPEC 详情页富组合（返回箭头 + SPEC 名 + 模式/状态 Tag + 快速切换下拉）作为 ReactNode 整体传入 `title` 槽位——控件对富节点透明不拆解，快速切换下拉保持渲染在 SPEC 名旁（`spec-detail-quick-switch` 契约延续）。
- **SPEC 详情标题栏中文标题下方行**：两个 SPEC 详情页把中文标题作为**块级第二行收进 `title` 富节点内部**，不经 `subtitle` 槽（两页声明零 subtitle 槽；槽位行尾跟随是概览等页副标题形态，详情中文标题要确定性换行位置、不随宽度漂移），形态同列表名称列副标题行：12px/次级色/单行省略、零外边距+行高 14px 贴排，左对齐与英文标题首字对齐。既有 subtitle 槽消费面（概览等页）保持标题行内右侧形态不变，组件不做全局翻转、不新增堆叠声明。数据源为 `/api/specs/<spec>` 详情响应的 `title` 字段，null/空不渲染（缺失容错与列表规则一致）；v1 详情（projects/detail）下方行只取 `title`，v2 详情（v2/specDetail）经单源 `combineSpecSubtitle` 组合渲染「中文标题 · branch」（branch 空只显中文标题，title 空维持 branch 单独显示，双空不渲染）；移动端中文下方行不渲染（页级 gate）；v1 参数缺失/loading/error 分支 detail 必空自然不渲染。
- **详情富标题两列结构与标签簇随块居中**：富标题内部为两列 flex（外层 alignItems center + wrap）：左列=英文名+中文下方行，右簇=模式/状态胶囊（v1 另含快速切换下拉，Space align center）`flexShrink: 0` 随标题块整体垂直居中（playwright boundingRect 实测簇中心=箭头中心=标题栏中心）；中文下方行用 `width: 0 + minWidth: '100%'` 定宽技巧——不参与左列 max-content 定宽（列宽只由英文名决定，右簇紧跟英文名不被中文行宽度推开），再撑回列宽超出即省略；窄视口外层 wrap 右簇下坠。配套：控件 `TitleNode` 加 `minWidth: 0`（flex 项默认 min-width:auto 会撑住下方行 min-content，允许收缩才能让省略号生效）。移动端富标题只显英文标题（页级 `!isMobile`/`!mobile` gate）：右簇（模式/状态胶囊与状态转移、v1 快速切换下拉——移动端无快速切换入口系设计内取舍）与中文下方行均不渲染。守卫 `specTitleSubtitle.test.mjs` 钉死形态（零 subtitle 槽 + 下方行块级视觉锚），pageTitleBar / pageChrome / embedMount 既有守卫同步钉版。
- **顶栏无面包屑**：顶栏右侧全局面包屑在任何视口宽度均不渲染（`HeaderCrumb` 组件、`crumbItems` 映射与 `global-header-crumb` 样式锚点不复存在），位置指示职责由顶栏页面标题承担；顶栏右上角只渲染该页过滤项（无过滤项页右上角为空）。
- **定高偏移口径**：定高页扣减常数为双档并经 playwright 实拍校准，对象仅两类——`pageChrome.ts` 项目详情页框（desktop 150/142、mobile 198/142）与指挥中心 `SCREEN_CHROME_OFFSET`（standalone 126 / embed 118）。回校后定高卡体 `calc(100vh - offset)` 恰满视口——右栏自滚、无第二根滚动条、无视口下空带。帮助/设置页为文档级滚动页，不持定高偏移常数（滚动形态见 `document-scroll-unify`）；其目录/菜单 sticky 钉位常数（standalone 56 / embed 60）与本栏高度联动。改标题行或内容区顶带任何内边距必须回校全部联动常数并重新实拍；回校按实际渲染盘点——命中标题栏高度依赖字面量族（56/60、126/130 同族）才改、未命中不动（避免全族误改），SPEC 详情两页中文标题下方行堆叠使标题块增高，实测两页零命中，既有常数未动。
- **豁免面**：现存豁免仅两类——`layout:false` 脱壳页（SPEC 协作拓扑大屏）无壳层不适用；菜单「项目」父项落点 `/projects` 的兜底占位页（`PagePlaceholder`，项目列表就绪后自动重定向、仅空列表时兜底可见）保留其占位页头不迁移。v2 六页不在豁免面（titleBar 槽位并入）。
- **非 embed 布局基线不变**：除标题栏迁移与面包屑退役外，ProLayout 侧栏结构、菜单数据、页签、主题 token 零改动；内容区左右留白仍走 `paddingInlinePageContainerContent` 单源。
- **界面原型为 UI 真相源**：全部界面形态（顶栏排布、标题行尺寸、过滤项密度、行壳位同构关系）以已批准入库的高保真原型为准（standalone.html 独立形态 / embed.html 嵌入形态，原型持久保留于 SPEC 归档目录）；实现与评审必须对照原型，原型与文字描述冲突时以原型为准并升级用户裁决。

## 关键行为

- dsh 侧零改造：embed 契约仍由查询参数承载（`embed`/`apiBase` 语义不变），标题行由本控件在嵌入态自动内嵌，dsh web 面板桥无需任何变更。
- 副标题承载：概览「监控 N 个项目」、项目列表「共 N 个 SPEC」、运维「跨项目 Administrator 活动与处置链观测」（罩三页签）经 subtitle 槽随标题渲染在标题栏，仅桌面视口可见（移动端隐藏）；无副标题页（设置、指挥中心、帮助）不渲染副标题槽位。SPEC 详情两页中文标题不走本槽（富节点内下方行，见规则条目）。
- 守卫契约：`pageTitleBar.test.mjs` / `embedMount.test.mjs` 钉移动顶栏 + embed 行壳位的双壳位新契约，页壳位结构变化须两测试同步钉版。

## 溯源

- 2026-11-04 unified-page-title-bar（spec/changes/unified-page-title-bar/） — 新增本能力：四槽位统一控件与双壳位自动分流（顶栏注册-插槽 / embed·移动端内容区首行 48px）、PageContainer 页头全站退役（本体保留 + `title={false}`）、过滤项收编、面包屑全局退役、富标题整体迁移、定高偏移五处常数 embed 双档回校、脱壳大屏与占位页豁免
- 2026-11-05 dashboard-ops-tabs-chain-merge（spec/knowledge/_inbox/done/dashboard-ops-tabs-chain-merge.md） — 处置链独立页并入运维页三页签随迁：常规页清单 8→7、处置链单项目 Select 例改运维页页签条件渲染、运维页副标题改罩三页签（原处置链页副标题条目消失）
- 2026-11-05 embed-titlebar-frosted-glass（spec/knowledge/_inbox/done/embed-titlebar-frosted-glass.md） — embed 档行壳位升格固定标题带毛玻璃：60px 半透明玻璃底 DSH_BG_SOFT_GLASS（DSH_BG_SOFT 60% 透明形态，同源共改守卫）+ sticky 钉视口顶 + backdrop blur(8px)（-webkit- 兜底），移动端档 48px 白底随流与 sticky 占位语义不变；行壳位旧「48px 白底」单档表述改写为双档形态
- 2026-11-05 settings-help-document-scroll-unify（spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md） — 定高偏移口径改写：settings/help `FRAME_OFFSET`（standalone 56 / embed 48）条目随两页转文档级滚动消失，现存对象仅项目详情页框与指挥中心 SCREEN_CHROME_OFFSET；回校纪律扩及帮助/设置目录/菜单 sticky 钉位常数（56/60）联动
- 2026-11-06 chrome-soft-solid-titlebar-1106（spec/knowledge/_inbox/done/chrome-soft-solid-titlebar-1106.md） — 行壳位玻璃守卫表述改钉 soft 染色族（SOFT/GLASS/HEADER_GLASS 族 rgb 通道一致、玻璃透明度必须 <1）；布局级 chrome 染色（顶栏玻璃双档/侧栏实底/边框三处同源）拆分至新页 layout-chrome-tinting
- 2026-11-06 v2-overview-titlebar-white-variant-1106（spec/knowledge/_inbox/done/v2-overview-titlebar-white-variant-1106.md） — v2 六页经 V2Page titleBar 槽位并入统一标题栏（v2 自画标题带与豁免面退役，新增 v2 并入条款）；行壳位收敛 embed 单档——移动端 48px 行壳位废除，移动端标题并入 ProLayout 顶栏（汉堡+logo+标题同条、缩进档 104→8、filters 落 right-content）；副标题移动端隐藏（顶栏插槽与行壳位两处同条件）
- 2026-11-06 add-spec-subtitle-and-row-click（spec/changes/add-spec-subtitle-and-row-click/） — 新增 SPEC 详情标题栏中文副标题消费面条款（v1 详情增 subtitle 声明、v2 详情与 branch 组合渲染「中文标题 · branch」、title 缺失容错不渲染、移动端隐藏零改动）
- 2026-11-06 交互会话用户指令链「下方行 + 间隔缩小 + 箭头/标签居中 + 移动端只显标题」（SPEC 详情中文标题定版，未走 SPEC） — 条款改版「SPEC 详情标题栏中文标题下方行」并新增「详情富标题两列结构与标签簇随块居中」：中文标题收进 title 富节点内部块级第二行（12px 次级/单行省略/零外边距行高 14 贴排），零 subtitle 槽，v2 combineSpecSubtitle 组合单源保持；富标题两列 flex（左列名+中文行、右簇胶囊随块取中，量测簇中心 21→28 对齐标题栏；中文行 width 0+minWidth 100% 定宽技巧防列宽被撑开）；控件三处随改（TitleNode minWidth 0、两壳位标题行 alignItems center、返回箭头移动端隐藏并入移动端隐藏规则）；移动端富标题只显英文名（胶囊簇/快速切换下拉/中文行全隐藏）；同日先行「subtitle 槽行尾内联档」（控件 nowrap+截尾）被更正回退，控件守卫锚（pageTitleBar/embedMount）随回退复原，specTitleSubtitle 守卫改钉下方行形态
- 2026-11-06 add-titlebar-subtitle-stacked（spec/changes/add-titlebar-subtitle-stacked/） — 已落地的详情页中文标题下方堆叠形态成文契约化：「SPEC 详情标题栏中文标题下方行」条款去历史化改写并升格 MUST（两页声明零 subtitle 槽、既有 subtitle 槽消费面保持行内右侧形态不变、组件不全局翻转不新增堆叠声明）；「详情富标题两列结构」条款钉死守卫面（specTitleSubtitle 零 subtitle 槽+下方行块级视觉锚，pageTitleBar/pageChrome/embedMount 同步）；「定高偏移口径」增补按实际渲染盘点回校条款（命中 56/60、126/130 族才改，两详情页堆叠行实测零命中既有常数未动）
- 2026-11-07 mobile-ui-fixes-1107（spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md） — 「过滤项统一右上落位」条款补移动端定式：filters 槽位即移动端「标题栏右侧控件位」单一定点，控件上移标题栏一律走槽位、不在内容区手画按钮行；窄幅放不下的过滤组整组下放内容区不注册槽位（指挥中心双下拉）
