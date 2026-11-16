## ADDED Requirements

> **界面原型（UI 真相源）**：`spec/changes/unified-page-title-bar/specs/unified-page-title-bar/prototype/`（standalone.html = 独立访问形态，embed.html = dsh web 嵌入形态，双整页截图随原型入库）。相关界面 Scenario 的布局、排布、尺寸观感以 prototype/ 为准，冲突须升级用户裁决。

### Requirement: 统一标题栏控件双壳位
dashboard 前端 SHALL 提供唯一的全站标题栏控件（含**标题 / 副标题 / 返回箭头 / 过滤项**四类声明槽位），各常规页只声明数据、MUST NOT 逐页自画同类型标题 div。控件按运行环境自选壳位：独立访问（无 `embed=1`）且视口 ≥768px 时渲染进顶部标题栏（Fenix Harness 品牌之后，标题 18px/700、副标题 12px 三级灰基线随迁，过滤项落顶栏右上角）；`embed=1`（dsh web 面板桥）或视口 <768px 时顶栏不承载，控件 SHALL 自动渲染为内容区首行标题栏（48px、白底、底缘分隔细线，排布与顶栏壳位同构）。壳位判定 MUST 收敛在控件内部，页面侧零环境分支；判定 MUST 单源互斥——同一时刻标题栏仅渲染于一处壳位，视口宽度跨 768px 阈值切换时退出侧壳位（顶栏注册或行壳位节点）MUST 清理，不出现双标题并存或残留。

#### Scenario: 顶栏承载（standalone）
- **WHEN** 独立访问（无 `embed=1`）以 ≥768px 视口打开设置页
- **THEN** 顶栏自左向右为「logo + Fenix Harness」、页面标题「设置」、右上角「作用域」过滤 Select；内容区首屏直接是设置卡片，无内容标题行；界面排布以 prototype/standalone.html 为准

#### Scenario: embed 内容区首行承载
- **WHEN** 以 `?embed=1` 启动（dsh web 面板桥 iframe）打开设置页
- **THEN** 无顶栏与侧栏，内容区首行为统一标题栏（「设置」+ 右侧作用域过滤），行高 48px 贴视口顶全幅呈现；界面排布以 prototype/embed.html 为准

#### Scenario: 移动端壳位降级
- **WHEN** 独立访问以 390px 视口（<768px）打开设置页
- **THEN** 顶栏仅渲染品牌（不承载标题与过滤项），统一标题栏整体渲染在内容区首行（与 embed 壳位同款载体），页面 `scrollWidth` 不超过视口宽，无横向溢出

#### Scenario: 视口跨阈值壳位互斥
- **WHEN** 独立访问下视口宽度在 ≥768px 与 <768px 之间来回切换（resize）
- **THEN** 任一时刻页面标题仅渲染于一处壳位（顶栏或内容区首行），切换后另一侧无残留，不出现双标题并存

### Requirement: 内容区标题栏退役
全部常规页（跨项目概览、项目列表、SPEC 详情、设置、运维记录、处置链、指挥中心、帮助）SHALL 摘除 PageContainer 页头（`header` 配置与页头渲染），内容区不再渲染标题行；页面内容直接从首屏卡片/表格起。无壳的脱壳页（SPEC 协作拓扑大屏 `layout:false`）不在本控件适用范围；菜单「项目」父项落点 `/projects` 的兜底占位页（`PagePlaceholder`，项目列表就绪后自动重定向、仅空列表时兜底可见）同为豁免面——保留其占位页头，不迁移本控件。

#### Scenario: 概览内容区首屏
- **WHEN** 打开跨项目概览页（standalone）
- **THEN** 「跨项目概览」标题出现在顶栏（副标题「监控 N 个项目」随迁），PageContainer 页头区域不再渲染，统计卡片为内容区第一屏元素

#### Scenario: 脱壳大屏豁免
- **WHEN** 打开 SPEC 协作拓扑大屏（`/projects/:name/:spec/topology`）
- **THEN** 大屏保持独立全屏形态，不渲染统一标题栏控件，形态与本变更前一致

### Requirement: 过滤项统一右上落位
页级过滤控件 SHALL 全部收编进统一标题栏控件的过滤槽位，落位由壳位决定（standalone 顶栏右上角 / 行壳位行右端），MUST NOT 再散落在 PageContainer `header.extra` 或页签 `tabBarExtraContent`：设置页「作用域」Select、处置链页「全部项目」Select、指挥中心「全部项目」+ 时间窗 Select（现挂组织总览页签 `tabBarExtraContent`）全部迁入；指挥中心页签行迁出后不再渲染 extra 区。

#### Scenario: 指挥中心双过滤迁顶栏
- **WHEN** 打开指挥中心页（standalone）
- **THEN** 「全部项目」Select 与时间窗 Select 渲染在顶栏右上角，组织总览页签行右端不再有过滤控件；切换过滤值时四屏数据联动行为与本变更前一致

#### Scenario: 处置链项目过滤迁顶栏
- **WHEN** 打开处置链页（standalone）
- **THEN** 「全部项目」过滤 Select 渲染在顶栏右上角，链观测卡片为内容区首屏元素

#### Scenario: embed 态过滤可用
- **WHEN** 以 `?embed=1` 打开指挥中心页
- **THEN** 双过滤 Select 渲染在内容区首行标题栏右端，过滤功能与独立访问等价

### Requirement: 副标题随迁
页面副标题 SHALL 随标题迁入统一标题栏控件（12px、三级灰字、与标题基线对齐）；副标题中的计数 MUST 用 tabular-nums 排版（跨项目概览「监控 N 个项目」、项目列表「共 N 个 SPEC」、运维记录「跨项目 Administrator 活动」、处置链页副标题同理）。无副标题页（设置、指挥中心、帮助）不渲染副标题槽位。

#### Scenario: 概览动态副标题随迁
- **WHEN** 概览数据加载完成（4 个项目）
- **THEN** 顶栏标题「跨项目概览」右侧渲染灰字副标题「监控 4 个项目」，计数 4 为 tabular-nums

### Requirement: 返回箭头随迁
项目列表页（`/projects/:name`）标题区的返回箭头（onBack 返回概览）SHALL 随标题迁入统一标题栏控件，渲染在标题左侧；SPEC 详情页同理（返回 + 富标题整体迁移）。

#### Scenario: 项目页返回箭头
- **WHEN** 从概览下钻打开项目列表页（standalone）
- **THEN** 顶栏渲染「← {项目名} + 共 N 个 SPEC」（原型中 fenixd 为示例项目名的具象值，title 槽位渲染当前路由项目名，原型字面文案不构成对具体项目名的约束），点击返回箭头回到 `/overview`，行为与本变更前一致

### Requirement: SPEC 详情富标题整体迁移
SPEC 详情页标题区富组合（返回箭头 + SPEC 名 + 模式 Tag + 状态 Tag + 快速切换下拉）SHALL 作为整体随标题迁入统一标题栏控件；快速切换下拉 MUST 保持渲染在 SPEC 名旁（spec-detail-quick-switch 契约延续），切换行为不变。

#### Scenario: 详情富标题顶栏承载
- **WHEN** 打开 SPEC 详情页（standalone）
- **THEN** 顶栏渲染返回箭头 + SPEC 名 + 模式/状态 Tag + 快速切换下拉，内容区首屏为详情页签区；切换下拉展开可选同项目其他 SPEC

### Requirement: 顶栏面包屑退役
顶栏右侧全局面包屑（`HeaderCrumb`，经 `actionsRender` 注入）SHALL 全局移除（全部视口宽度），位置指示职责由顶栏页面标题承担；相关样式锚点（`global-header-crumb`）与面包屑条目映射函数一并退役清理。

#### Scenario: 顶栏右上角仅过滤项
- **WHEN** 以 ≥768px 视口打开任意常规页
- **THEN** 顶栏右上角只渲染该页过滤项（无过滤项页右上角为空），「概览 / fenixd / spec 名」面包屑不再出现

### Requirement: 定高页偏移常数回校
页头消失改变视口高度链，定高页偏移常数 SHALL 同步回校并在注释中保留口径说明：settings `SETTINGS_FRAME_OFFSET`、help `HELP_FRAME_OFFSET`（standalone 档去掉 PageContainer 页头 56px 占位；embed 档改按 48px 标题行重算）、`pageChrome.ts` 页框口径、指挥中心 `SCREEN_CHROME_OFFSET` 族。回校后定高卡体 `calc(100vh - offset)` MUST 恰满视口——右栏自滚、无第二根滚动条、无视口下空带。

#### Scenario: 设置页定高无第二滚动条
- **WHEN** 1440×900 视口打开设置页（standalone 与 `?embed=1` 两形态）
- **THEN** 两形态下右栏自滚、左侧菜单固定，页面不出现第二根滚动条，卡底不探出视口

#### Scenario: 帮助页定高回校
- **WHEN** 1440×900 视口打开帮助页（standalone）
- **THEN** 帮助卡体恰满视口（滚动条下沉到正文容器），页头消失后的偏移与实际页框占用一致

### Requirement: 非 embed 布局基线不变
独立访问形态下，除标题栏迁移与面包屑退役外，ProLayout 布局 MUST 与现状一致：侧栏结构、菜单数据、页签、卡片、表格、主题 token 零改动；内容区左右留白仍走 `paddingInlinePageContainerContent` 单源（15px）。

#### Scenario: 侧栏与主题零回归
- **WHEN** 独立访问打开概览页并与改造前对比
- **THEN** 侧栏菜单、配色、卡片表格形态一致；唯一差异为顶栏出现页面标题+副标题、内容区页头消失

### Requirement: 界面以原型为 UI 真相源
本能力全部界面形态（顶栏排布、标题行尺寸、过滤项密度、副标题灰阶层级、行壳位同构关系）以 `spec/changes/unified-page-title-bar/specs/unified-page-title-bar/prototype/` 为 UI 真相源（主题 token 取 `theme.ts` 单源真值）；实现与评审 MUST 对照原型，原型与文字描述冲突时以原型为准并升级用户裁决。

#### Scenario: 实现对照原型
- **WHEN** 实现者渲染任一常规页标题栏
- **THEN** 形态与 prototype/standalone.html 或 prototype/embed.html 对应壳位一致（标题 18px/700、副标题 12px 三级灰、过滤项 28px small 档、行壳位 48px）
