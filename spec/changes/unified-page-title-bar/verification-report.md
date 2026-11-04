# 验证报告：unified-page-title-bar

> ⚠️ 本报告由框架于 2026-11-04T12:43:05Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-04T12:43:04.099650+00:00+run-result@mtime1793796184152691372

## 结论：✅ 通过（verified）

**状态：verified — 24/24 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 24/24 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 24 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 14.46M |
| 本链增量 Token（输出） | 0.15M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| settings-standalone-topbar-title-and-filters | 独立访问（无 embed=1）桌面视口打开设置页：顶栏自左向右为品牌与页面标题「设置」、「作用域：」过滤 Select 落顶栏右上角；内容区首屏直接是设置卡片（页签菜单「模型」起），无内容标题行；无副标题页不渲染副标题槽位。本场景与 settings-mobile-shell-fallback 共同构成壳位互斥双静态端（引擎词表无 resize 动作，跨阈值动态切换不可驱动，两端各自证「标题仅渲染一处壳位」）。出处：/#/settings（config/routes.ts:52、config.ts:15 hash 路由）；现状页头/作用域 Select（pages/settings/index.tsx:343-368）；顶栏锚点 [data-testid=pro-layout-global-header]（pro-components dist 7310 chunk 实证）。 | pass | 0/7 | - |
| settings-embed-first-row-title-bar | 以 ?embed=1（dsh web 面板桥 iframe）打开设置页：全局侧栏与顶栏不渲染（app.tsx:159 menuRender/headerRender:false 语义延续），统一标题栏自动落内容区首行承载「设置」标题与「作用域：」过滤（行右端）。出处：/?embed=1#/settings（embedMount.ts:4-5 参数位于 hash 前）；dashboard-embed-mount spec embed 隐藏壳层 Scenario。 | pass | 0/5 | - |
| settings-mobile-shell-fallback | 独立访问 390×844（<768px）打开设置页：顶栏仅渲染品牌（Fenix Harness），不承载标题与过滤项；统一标题栏整体落内容区首行（与 embed 同款载体），标题与「作用域：」过滤可见，内容区无横向溢出。本场景为壳位互斥移动端。出处：390 视口 D7 移动端行壳位复用 embed 形态（design D7）；unified-page-title-bar spec 移动端壳位降级 Scenario。 | pass | 0/7 | - |
| overview-title-subtitle-topbar | 打开跨项目概览页（standalone）：顶栏渲染标题「跨项目概览」+ 动态副标题「监控 N 个项目」（计数随 /api/overview 项目数）；PageContainer 页头摘除，内容区不再出现标题文本，首屏直接是统计卡与项目卡列表。出处：现状 header title/subTitle（pages/overview/index.tsx:206-210）；副标题随迁 Requirement。 | pass | 0/5 | - |
| overview-cards-enter-project | 概览项目卡交互回归（覆盖交互候选 cards）：点击项目卡「进入」动作下钻项目列表页，终态顶栏为「{项目名} + 共 N 个 SPEC + 返回箭头」形态。出处：「进入」按钮 onClick history.push（pages/overview/components/ProjectCards.tsx:250-259）；列表页 header title/onBack（pages/projects/list.tsx:1670-1678）。 | pass | 0/5 | - |
| project-list-back-arrow | 项目列表页返回箭头行为：直接打开 /#/projects/fenixd（列表页无过滤项注册，顶栏唯一按钮=返回箭头），点击后回概览页、顶栏标题切换为「跨项目概览」。「{项目名} + 共 N 个 SPEC」标题形态由 overview-cards-enter-project 场景在列表页终态覆盖。出处：onBack 恒 push /overview（pages/projects/list.tsx:1678）；返回箭头随迁 Requirement。 | pass | 0/3 | - |
| spec-detail-rich-title-topbar | SPEC 详情页富标题整体迁移：独立访问打开 /#/projects/fenixd/unified-page-title-bar，点击快速切换下拉展开面板；终态顶栏渲染 SPEC 名 + 模式/状态 Tag + 快速切换下拉（aria-label=切换 SPEC，页面自 authored 属性稳定），面板列出行可见，内容区首屏为详情页签区。出处：富标题 headerCfg（pages/projects/detail.tsx:1194-1218）；快速切换面板类名（detail.tsx:1133/1150）；spec-detail-quick-switch 契约延续。 | pass | 0/7 | - |
| command-center-filters-topbar | 指挥中心双过滤迁顶栏（org 屏静态）：standalone 打开组织总览页签，「全部项目」Select 与时间窗 Select 渲染在顶栏右上角（.ant-select 计数 2）；页签行 extra 区不再渲染（.ant-tabs-extra-content 移除）。出处：现状 tabBarExtraContent 双 Select（pages/command-center/index.tsx:149-172）；D8 迁移条款。 | pass | 0/4 | - |
| command-center-window-org-only | 指挥中心时间窗 Select 仅 org 屏显隐：从组织总览切「交付流水线」页签后顶栏 Select 计数降为 1（时间窗消失，显隐逻辑随迁 filters 槽位），页签激活。出处：现状 activeKey==='org' 条件渲染（command-center/index.tsx:162-170）；D8 显隐逻辑随迁条款。 | pass | 0/4 | - |
| command-center-filter-refetch | 指挥中心过滤联动：在顶栏右上角项目 Select 选择 fenixd，组织总览屏数据联动重拉（/api/command-center/org 请求在交互步窗口内出现），终态 Select 现值为 fenixd、零控制台错误。出处：org 端点 project/window 查询参数（services/dashboard.ts:1521）；现状 onChange=setProject（command-center/index.tsx:154）。 | pass | 0/3 | - |
| chain-filter-topbar-refetch | 处置链过滤迁顶栏：standalone 打开处置链页，顶栏承载标题「处置链」与副标题「Admin → Arbiter → Human 自动处置链观测（只读）」，「全部项目」Select 落顶栏右上角；选择 fenixd 触发 /api/chain 重拉，终态 Select 现值 fenixd、链观测卡片仍在内容区首屏。出处：现状 header/extra Select（pages/chain/index.tsx:215-227）；getChainOverview project 参数（services/dashboard.ts:627-630）。 | pass | 0/7 | - |
| embed-command-center-filters-functional | embed 态过滤可用：以 ?embed=1 打开指挥中心，双过滤 Select 渲染在内容区首行标题栏右端（.ant-select 计数 2），切换项目过滤触发组织总览数据重拉，过滤功能与独立访问等价。出处：unified-page-title-bar spec embed 态过滤可用 Scenario；embed 无顶栏（app.tsx:159）。 | pass | 0/7 | - |
| embed-overview-shell-hidden | embed=1 打开概览页：全局侧栏与顶栏不渲染，内容区首行为统一标题栏（「跨项目概览」+「监控 N 个项目」副标题随迁），概览内容（项目卡列表）正常渲染、零控制台错误。SSE 自动刷新断言超出引擎词表（EventSource 无法驱动），以内容渲染+零控制台错误作降级证据。出处：dashboard-embed-mount spec embed 隐藏壳层 Scenario（MODIFIED 后标题行内嵌语义）。 | pass | 0/6 | - |
| embed-apibase-prefix-combo | 参数组合 ?embed=1&apiBase=/fenix-dashboard：壳层隐藏且数据请求走前缀。以 mock 哨兵拦截前缀化 /fenix-dashboard/api/overview（哨兵项目 prefix-probe 仅在前缀命中时渲染；裸实例无该前缀路由，若前端未拼前缀则请求落真实端点、哨兵缺席即失败，确定性区分两种实现）；断言哨兵项目卡与「监控 1 个项目」渲染、壳层隐藏。apiBase 前缀化语义属 dashboard-embed-mount 交付（前端 URL 拼接），mock 的前缀路径非本 SPEC 交付端点，不触「禁 mock 交付端点」铁律。前缀请求之外的辅助请求（告警/SSE）在裸实例上前缀 404 属预期，本场景不断言 no_console_error。出处：embedMount.ts:4-5/61-65 apiBase 拼接单点；dashboard-embed-mount spec 参数组合 Scenario。 | pass | 0/5 | - |
| non-embed-baseline-unchanged | 非 embed 布局基线不变：独立访问打开概览页，ProLayout 侧栏（pro-layout-sider）与顶栏（pro-layout-global-header，品牌 Fenix Harness）照常渲染，侧栏菜单含「概览」等基础项；唯一差异为面包屑退役（.global-header-crumb 全宽度消失）与顶栏出现页面标题。出处：布局基线 Requirement；D3 面包屑退役清理锚点（app.tsx:98）。 | pass | 0/7 | - |
| breadcrumb-retired-detail | 顶栏面包屑退役（面包屑最丰富页取证）：打开 SPEC 详情页（面包屑原形态「概览 / fenixd / spec 名」），顶栏内面包屑组件（.ant-breadcrumb）与其样式锚点（.global-header-crumb）均不渲染，项目名 fenixd 不再以面包屑形态出现在顶栏（位置由顶栏页面标题表达）。出处：D3 面包屑退役条款；现状 HeaderCrumb（app.tsx:96-99/154）。 | pass | 0/5 | - |
| topology-bigscreen-exempt | 脱壳大屏豁免：打开 SPEC 协作拓扑大屏 /#/projects/fenixd/unified-page-title-bar/topology（layout:false 脱壳路由），保持独立全屏形态——ProLayout 侧栏与顶栏不渲染，统一标题栏控件（含富标题切换下拉）不渲染，形态与本变更前一致。出处：脱壳路由（config/routes.ts:36-42 layout:false）；豁免面条款。 | pass | 0/6 | - |
| projects-placeholder-exempt | 项目父项落点占位页豁免：以 mock 空项目列表（/api/overview 哨兵，页面骨架依赖的壳层接口，非本 SPEC 交付端点）打开 /#/projects，「项目」兜底占位页保留 PageContainer 页头（标题「项目」仍在内容区渲染，「建设中」空态可见）——豁免面不迁移本控件，壳层照常。出处：占位页保留页头条款；PagePlaceholder（components/PagePlaceholder.tsx:10-22）；空列表兜底不重定向（pages/projects/index.tsx:17-25）。 | pass | 0/4 | - |
| settings-fixed-height-standalone-1440 | 设置页定高回校（standalone，1440×900）：卡体 calc(100vh - SETTINGS_FRAME_OFFSET) 恰满视口——body 无纵向溢出（即无第二根滚动条、卡底不探出视口），设置卡片可见，标题与作用域过滤仍在顶栏。出处：定高页偏移回校 Requirement；SETTINGS_FRAME_OFFSET（pages/settings/index.tsx:50，standalone 档去掉页头 56 占位）；卡体定高（settings/index.tsx:374，className settings-page）。 | pass | 0/4 | - |
| settings-fixed-height-embed-1440 | 设置页定高回校（embed，1440×900）：?embed=1 下卡体按标题行 48px 重算口径恰满视口——body 无纵向溢出、无第二根滚动条；顶栏/侧栏不渲染，标题行在内容区首行。出处：SETTINGS_FRAME_OFFSET embed 档=标题行 48+尾带（pages/settings/index.tsx:48-50 注释口径）。 | pass | 0/5 | - |
| help-fixed-height-standalone-1440 | 帮助页定高回校（standalone，1440×900）：HELP_FRAME_OFFSET 按 standalone=顶栏 56 校准后帮助卡体恰满视口（body 无纵向溢出，滚动条下沉正文容器）；顶栏渲染标题「帮助」，无副标题无过滤项（顶栏 .ant-select 计数 0）。出处：HELP_FRAME_OFFSET（pages/help/index.tsx:48-54）；定高页偏移回校 Requirement。 | pass | 0/5 | - |
| settings-scope-switch-interaction | 设置页作用域过滤交互（standalone）：顶栏「作用域：」Select 选择「项目级：fenixd」触发配置重拉（/api/config 在交互步窗口内出现），终态 Select 现值为「项目级：fenixd」，左侧页签菜单随项目级作用域出现「自省」「Hook」页签。出处：作用域 Select（pages/settings/index.tsx:343-368）；getConfig project 参数（services/dashboard.ts:2235-2237）；项目级页签 push（settings/index.tsx:335-340、pageLabels.ts:28-30）。 | pass | 0/5 | - |
| mobile-detail-tag-wrap | 详情富标题行壳位窄屏换行：390×844 视口打开 /#/projects/fenixd/unified-page-title-bar（长名 SPEC），富标题组合（SPEC 名+模式/状态 Tag+切换下拉）渲染在内容区首行标题栏并自然换行，内容区无横向溢出，切换下拉（aria-label=切换 SPEC）保持在标题区；顶栏不承载标题。出处：mobile-detail-header-density MODIFIED 条款（载体迁行壳位、wrap 语义延续、390 不溢出）。 | pass | 0/5 | - |
| activities-title-subtitle-topbar | 运维记录标题+副标题随迁：standalone 打开运维记录页，顶栏渲染「运维记录」与副标题「跨项目 Administrator 活动」，内容区不再出现标题行，活动卡（data-testid=activity-card）照常渲染。出处：现状 header（pages/activities/index.tsx:605-608）；副标题随迁 Requirement（任务 2.1）。 | pass | 0/5 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

