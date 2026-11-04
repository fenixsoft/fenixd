# 全站统一标题栏

<!-- knowledge: capability=unified-page-title-bar rev=1
     sources=spec/changes/unified-page-title-bar -->

dashboard 前端唯一的全站内容标题栏控件（`src/components/PageTitleBar.tsx`）：标题/副标题/返回箭头/过滤项四槽位声明，双壳位（顶栏承载 / 内容区首行承载）自动分流——页面只声明数据，禁止逐页自画同类型标题 div。

## 规则

- **唯一控件与四槽位**：全部常规页经 `<PageTitleBar title subtitle? back? filters? />` 声明标题元数据（props 仅此四类槽位）；过滤项与富标题是页内状态，MUST NOT 走全局路由表配置，MUST NOT 散落 `PageContainer header.extra` 或页签 `tabBarExtraContent`。
- **壳位判定收敛控件内部**：`embed=1`（dsh web 面板桥 iframe，无顶栏）或视口 <768px（移动端顶栏维持纯品牌）时渲染为内容区首行标题栏（48px、白底、底缘细线，与顶栏壳位同构排布）；独立访问且 ≥768px 时渲染进顶部标题栏（Fenix Harness 品牌之后，标题 18px/700、副标题 12px 三级灰基线随迁），过滤项落顶栏右上角。页面侧零环境分支。
- **声明-注册-插槽机制**：顶栏壳位采用注册制——控件在挂载时把 meta 登记进模块级注册表（`pageTitleBarStore`），布局层（`app.tsx`）经标题区插槽（`headerContentRender`）与过滤项插槽（`actionsRender`）消费渲染；meta 任一字段变化即重登记，注销与注册由同一 effect 的 cleanup 承担（CSR 下 layout effect 注册先于绘制，路由切换瞬间旧页注销与新页注册同批 flush，插槽无空窗闪烁）。
- **壳位单源互斥**：同一 meta 任一时刻只渲染于一处壳位——行壳位时不注册、顶栏壳位时不渲染行本体；视口宽度跨 768px 阈值翻转时旧壳位节点随 effect 清理，MUST NOT 双标题并存或切换后残留。顶栏无注册内容时渲染空（不残留上一页标题）。
- **形态基准**：标题 18px/700、副标题 12px 三级灰与标题基线对齐、副标题计数 `tabular-nums`（`TitleBarNum`）、过滤项 antd 28px small 档、行壳位 48px 底缘细线；配色全部取 `theme.ts` 单源，零新色。
- **内容区无页头**：8 个常规页（跨项目概览、项目列表、SPEC 详情、设置、运维记录、处置链、指挥中心、帮助）均不渲染 PageContainer 页头，内容直接从首屏卡片/表格起；PageContainer 本体保留（内容区留白 token 单源仍由其承载，见 `page-container-chrome`），但必须传 `title={false}` 显式抑制自动页头——不传 title 时 ProLayout 会从路由上下文兜底取路由名渲染页头，与标题栏双标题并存。
- **过滤项统一右上落位**：页级过滤控件全部收编进 `filters` 槽位，落位随壳位（顶栏右上角 / 行右端）——设置页「作用域」Select、处置链页「全部项目」Select、指挥中心「全部项目」+时间窗双 Select（时间窗仅 org 屏显隐逻辑随迁页内条件渲染）。
- **返回箭头与富标题**：项目列表页返回箭头（回 `/overview`）走 `back` 槽位渲染在标题左侧；SPEC 详情页富组合（返回箭头 + SPEC 名 + 模式/状态 Tag + 快速切换下拉）作为 ReactNode 整体传入 `title` 槽位——控件对富节点透明不拆解，快速切换下拉保持渲染在 SPEC 名旁（`spec-detail-quick-switch` 契约延续）。
- **顶栏无面包屑**：顶栏右侧全局面包屑在任何视口宽度均不渲染（`HeaderCrumb` 组件、`crumbItems` 映射与 `global-header-crumb` 样式锚点不复存在），位置指示职责由顶栏页面标题承担；顶栏右上角只渲染该页过滤项（无过滤项页右上角为空）。
- **定高偏移口径**：定高页扣减常数为 embed 双档并经 playwright 实拍校准——settings/help `FRAME_OFFSET`（standalone 56 / embed 48）、`pageChrome.ts` 项目详情页框（desktop 150/142、mobile 198/142）、指挥中心 `SCREEN_CHROME_OFFSET`（standalone 126 / embed 118）。回校后定高卡体 `calc(100vh - offset)` 恰满视口——右栏自滚、无第二根滚动条、无视口下空带。改标题行或内容区顶带任何内边距必须回校并重新实拍。
- **豁免面**：`layout:false` 脱壳页（SPEC 协作拓扑大屏）无壳层不适用；菜单「项目」父项落点 `/projects` 的兜底占位页（`PagePlaceholder`，项目列表就绪后自动重定向、仅空列表时兜底可见）保留其占位页头不迁移。
- **非 embed 布局基线不变**：除标题栏迁移与面包屑退役外，ProLayout 侧栏结构、菜单数据、页签、主题 token 零改动；内容区左右留白仍走 `paddingInlinePageContainerContent` 单源。
- **界面原型为 UI 真相源**：全部界面形态（顶栏排布、标题行尺寸、过滤项密度、行壳位同构关系）以已批准入库的高保真原型为准（standalone.html 独立形态 / embed.html 嵌入形态，原型持久保留于 SPEC 归档目录）；实现与评审必须对照原型，原型与文字描述冲突时以原型为准并升级用户裁决。

## 关键行为

- dsh 侧零改造：embed 契约仍由查询参数承载（`embed`/`apiBase` 语义不变），标题行由本控件在嵌入态自动内嵌，dsh web 面板桥无需任何变更。
- 副标题承载：概览「监控 N 个项目」、项目列表「共 N 个 SPEC」、运维记录「跨项目 Administrator 活动」、处置链页副标题均随标题渲染在标题栏；无副标题页（设置、指挥中心、帮助）不渲染副标题槽位。

## 溯源

- 2026-11-04 unified-page-title-bar（spec/changes/unified-page-title-bar/） — 新增本能力：四槽位统一控件与双壳位自动分流（顶栏注册-插槽 / embed·移动端内容区首行 48px）、PageContainer 页头全站退役（本体保留 + `title={false}`）、过滤项收编、面包屑全局退役、富标题整体迁移、定高偏移五处常数 embed 双档回校、脱壳大屏与占位页豁免
