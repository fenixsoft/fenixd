# 指挥中心三屏前端

<!-- knowledge: capability=command-center-console-ui rev=7
     sources=spec/archive/2026-10-31-add-command-center,spec/archive/2026-11-02-add-command-center-spec-view,spec/knowledge/_inbox/done/command-center-light-embed-migration.md,spec/changes/unified-page-title-bar,spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md,spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md,spec/changes/add-command-center-verify-stats -->

指挥中心台面的前端面：`/command-center` 以 ProLayout 内容区常规页承载三 Tab（组织总览、交付流水线、执行台账）+ KPI 条，面向管理层快速检视组织交付态势与执行明细。

## 规则

- **入口与页面骨架**：路由 `/command-center` 为 ProLayout 内容区常规页（侧栏/顶栏与全菜单一致），MUST NOT 回退 `layout:false` 脱壳形态（routes.ts 守卫拦截回潮）。菜单项由 `src/app.tsx` menuDataRender 注册。页面标题与双过滤项由统一标题栏控件（unified-page-title-bar）承载，PageContainer 页头不渲染（`title={false}` 抑制自动页头）。三屏以 antd Tabs 组织，默认展示组织总览；页签行不渲染 extra 区（过滤控件由标题栏承载）。
- **移动端双过滤落内容区首行**：<768px 视口双 Select 不注册统一标题栏 filters 槽位（`filters={undefined}`），改落内容区首行 flex 行——项目 Select `flex:1` 铺行宽、时间窗 Select 定宽 100；时间窗「仅组织总览显示」的条件显隐不变。双 Select 声明收单源（`projectSelect`/`orgWinSelect` 元素常量，isMobile 只切宽度承载）；桌面视口双 Select 仍注册 filters 槽位、落顶栏右上角。
- **URL 深链**：筛选与选中态入 URL——`project`（项目筛选）、`window`（时间窗，脏值回落 today）、`spec` + `spec_project`（org 屏 SPEC 视图二元组，写读单点；名单校验不过自动清除退出）；刷新/分享直达即得筛选语义。时间窗下拉仅总览页签显示，非总览页签不渲染（不留「显示但无效」的死控件）。
- **三屏独立加载与降级**：各屏数据独立加载；某屏对应端点返回 5xx 或超时时仅该屏渲染错误占位与重试按钮，其余屏与 KPI 条不受影响。后台静默刷新失败保留旧数据，不白屏。加载/错误占位框平铺呈现（无描边、无底色）。
- **数据接入与刷新**：复用既有 services 层 API client 模式（`src/services/dashboard.ts`）接入只读聚合端点；前端固定间隔（≥30s，现值 60s）静默轮询，无用户操作下数据自更新，MUST NOT 引入新配置项。
- **组织总览屏**：按后端 org 数据渲染部门分区标题 + 区内车道卡 + 汇报线；汇报线为静态 SVG 细线（无动画节点），按 DOM 实测坐标绘制、随布局自动重算。车道卡展示车道名、状态徽标（运行中/空闲）、今日 run 数、7 日成功率、14 日活动柱点 sparkline、7 日成本、最近活动时间；花名册内零 run 车道与活跃车道同尺寸出卡。点击 spec 名/运行行打开运行记录弹窗（复用 SPEC 详情页 RunRecordModal）；空 run_id 的在飞验证归属条目渲染为显名不可点（不开运行记录弹窗、不报错）；车道卡与运行行均不跳转详情页。
- **SPEC 视图**（org 屏内）：从 specs 名单选中 SPEC 进入 spec 视图，按 spec-runs 聚合端点渲染运行轮次（`spec名 · 第N轮`，最新在前）；未运行显「未运行」，spec-runs 数据未到显「加载中」占位，均无动画。选中的 SPEC 从名单消失时视图自动清空退出。
- **交付流水线屏**：五列泳道（列头：需求评审/待实现/实现中/验证中/已推送），列归属按聚合层桶映射；卡片显示项目 Tag + SPEC 名，保留原生 status 徽标；implementing 列卡带 `running` 时显示在飞 lane 与开始时间。点击卡片钻取既有 `/projects/:name/:spec` 详情页。项目筛选下拉数据源为响应 `projects` 全集，含「全部项目」项。
- **执行台账屏与 KPI 条**：KPI 条展示四指标（7 日交付 SPEC / 人工介入率 / run 成功率 / 单 SPEC 成本）+ 网关状态徽标；`null` 指标 MUST 显示「—」而非 0。台账表格列：项目、SPEC、车道、结果、耗时、tokens、成本、开始时间、trigger（null 显示「—」）。项目筛选与流水线屏同一数据源模式。
- **配色单源**：页面继承 app.tsx rootContainer 的 `dshAlignedTheme`（白底、黑主色 #0f1115、蓝链接 #4176e6）；MUST NOT 页级注入 darkAlgorithm、`colorBgBase '#000'`、html/body 纯黑或深色滚动条样式（index 守卫拦截）。`pages/command-center/shared.ts` 色板常量（BG/PANEL_BORDER/TEXT_MAIN/TEXT_SUB/CARD_BG/ACCENT/GREEN/LINK_STROKE 与 badge 函数族）全部派生自 `theme.ts` dsh 单源常量，不持独立色值（以 `from '../../theme.ts'` 带扩展名导入，type-stripping 直载兼容）。
- **暗种子 *Bg 派生陷阱**：`colorPrimary` 为近黑 #0f1115 时，antd 以主色为种子派生的 `--ant-color-primary-bg` 族是暗色 ramp，任何「选中底色」引用该族即黑底黑字/深底深字。选中/高亮底色一律取 theme.ts 单源常量或中性 fill 族，MUST NOT 引用种子派生族（darkSeedBgToken 守卫测试源码级拦截）。Select「选中+hover 叠加态」只由别名键 `controlItemBgActive/ActiveHover` 承接（组件级 optionActiveBg/optionSelectedBg 覆盖不到叠加态）：theme.ts 根 token 显式压该别名为浅值（DSH_BG_MODULE），并配 Select 组件级 optionActiveBg/optionSelectedBg/optionSelectedColor 显式浅值。
- **Agent 卡自适应宽度**：分区行用 grid `repeat(N, minmax(270px, 1fr))` 流式布局——行左右各 32px padding，剩余宽度按列均分给卡片；列下限单源 `shared.LANE_CARD_MIN_WIDTH=270`（上限不限），纯 CSS 实现，MUST NOT 脚本算宽。containerRef 以 `N×270+(N-1)×14+64` 为 minWidth 下限（块级 auto 宽+minWidth 天然表达 max(100%, 该值)），窄视口出横向滚动。
- **连接线对齐与配色**：汇报线容器监听 MUST 用 ResizeObserver 观察 containerRef 自身盒尺寸（同时覆盖窗口 resize 与侧栏折叠等壳层布局变化两类来源），MUST NOT 回退仅监听 window resize（守卫拦截——侧栏折叠不触发 window resize，量取坐标会陈旧致连线歪斜）。连接线颜色 `LINK_STROKE=rgba(0,0,0,0.2)`，仍比 Bento 卡框（发丝边 #eef2f7）深一档，白底可读。
- **定高滚动模型**：组织总览双向滚动、交付流水线赛道内滚，视口扣减单源 `SCREEN_CHROME_OFFSET`（`pages/command-center/shared.ts`，embed 双档：standalone 126 / embed 118——standalone = ProLayout 顶栏 56 + 页面 padding-top 8 + 页签条 62，embed = 统一标题栏行壳位 48 + 8 + 62；1920×1080 playwright 实拍校准：容器底缘恰贴视口底缘零溢出）。壳层结构（顶栏/行壳位高/padding/页签条）任一变化必须复核本值并重新实拍校准。
- **卡片框 Bento 形态**：org 屏 LaneCard 车道卡与产品团队卡、pipeline 屏五列泳道容器与泳道 SPEC 卡、台账屏 KPI 条主框——五类卡片框为 Bento 形态（发丝边 #eef2f7 + 12 圆角 + 软阴影），单源常量 `CARD_FRAME_BORDER`/`CARD_FRAME_SHADOW`（`pages/command-center/shared.ts`；色值 2026-11-06 对齐 v2 时定形，该域 2026-11-07 已退役为独立存量；本页白底磁贴，不适用 settings 灰底准例）。`PANEL_BORDER` 降级为非框用途：sparkline 空点填充（OrgGrid）与流水线列头分隔线（PipelineBoard）保留原 0.10 档描边；框内结构元素（图标徽章 AVATAR_BORDER、dashed 待命格 REST_BORDER、metric 分隔线）不随框换肤。加载/错误占位框仍平铺（瞬态占位非卡片，知识契约即「占位框平铺」）。global.less 去边框规则作用域为 `.ant-pro-page-container` 内 `.ant-card`，本页页内无 `.ant-card`，不受影响。
- **大屏例外域成员资格**：本页为 ProLayout 嵌入页，不属 DESIGN.md 例外域（`layout:false` 脱壳与域专属 token 表均不适用本页）；大屏例外域已随 spec-topology 拓扑大屏 2026-11-08 退役清零（DESIGN.md 该节改为退役注记）。
- **严肃企业风格红线**：数据墨水优先、小号大写标签、静态细线；MUST NOT 出现插画、动画角色/像素小人、吉祥物、装饰性动效，渲染保持静态。
- **不建自有详情视图**：SPEC 详情一律复用既有 `/projects/:name/:spec` 页面，指挥中心不建自有详情页。

## 溯源

- 2026-10-31 add-command-center（spec/archive/2026-10-31-add-command-center） — 新增本能力：四屏 Tab 脱壳深色大屏形态、静态 SVG 汇报线与 sparkline、一键裁决复用 alert-resolve、KPI 条空值「—」形态、严肃企业风格红线与 ≥30s 静默轮询
- 2026-11-02 add-command-center-spec-view（spec/archive/2026-11-02-add-command-center-spec-view） — 裁决收件箱页签移除（alert-resolve 一键裁决随页签退役），org 屏新增 SPEC 视图（specs 名单派生 + spec-runs 聚合端点 + 运行记录弹窗），整卡钻取改为点击 spec 名开弹窗
- 2026-11-04 command-center-light-embed-migration（spec/knowledge/_inbox/done/command-center-light-embed-migration.md） — 黑改白+去脱壳嵌入改版：ProLayout 常规页、配色挂 theme.ts 单源、暗种子 *Bg 陷阱别名压制（controlItemBgActive）、Agent 卡流式自适应（minmax 270px 单源）、连接线 ResizeObserver+换灰、定高扣减换 SCREEN_CHROME_OFFSET=182、占位框平铺、DESIGN.md 大屏域收缩为 spec-topology 一项
- 2026-11-04 unified-page-title-bar（spec/changes/unified-page-title-bar/） — 页头退役随迁改造：页面标题与双过滤项迁统一标题栏（standalone 顶栏 / embed·移动端行壳位），页签行 `tabBarExtraContent` extra 区移除，PageContainer 改传 `title={false}`，SCREEN_CHROME_OFFSET 回校 182→standalone 126/embed 118 双档
- 2026-11-06 overview-ledger-bento-align-1106（spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md） — 改写数据卡描边条款为卡片框 Bento 形态：五类卡片框（车道卡/团队卡/泳道容器/泳道 SPEC 卡/KPI 条主框）发丝边 + 12 圆角 + 软阴影（CARD_FRAME_* 镜像单源）、PANEL_BORDER 降级非框用途、占位框平铺与框内结构不换肤保留
- 2026-11-07 mobile-ui-fixes-1107（spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md） — 新增「移动端双过滤落内容区首行」条款：双 Select 声明收单源（isMobile 只切宽度承载）、移动端 filters 槽位不注册（filters={undefined}）、首行 flex 行（项目 Select flex:1 + 时间窗定宽 100）；桌面顶栏右上角形态不变
- 2026-11-08 协作拓扑与会话接入退役批（用户指令，无归档 SPEC，登记见 log.md） — 镜像条款收口：大屏例外域成员资格条款收口（例外域清零）
- 2026-11-12 add-command-center-verify-stats（spec/changes/add-command-center-verify-stats/） — org 屏补充空 run_id 在飞验证归属条目渲染条款：`AttributableRun.run_id` 放宽可空、显名不可点（不开运行记录弹窗），`activityLineState` 主路径过滤器保留空条目
