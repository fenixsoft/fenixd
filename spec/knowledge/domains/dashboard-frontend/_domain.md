# 仪表盘前端
> 最后更新：2026-11-12 18:00 UTC+8

仪表盘前端。本域能力条目清单如下（能力页由存量回填批次逐步产出，落盘后此处升级为链接）。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [dashboard-ui](dashboard-ui.md) | 仪表盘基础界面 | 2026-10-03 04:59 |
| [dashboard-overview](dashboard-overview.md) | 项目总览页（Bento 统计卡 + 项目台账磁贴双形态、运行态 Radio 筛选、跨域镜像不引用） | 2026-11-06 17:54 |
| [dashboard-spec-table](dashboard-spec-table.md) | SPEC 列表表格（桌面台账表格重绘非替换（2026-11-06 对齐 v2 改版定形）、行内容台账形态、名称列中文副标题与标题命中搜索、整行点击进详情、三点菜单文档入口、SPEC 信息图标 + Popover 提示与弹层内清除；移动端磁贴卡片流层级与状态 chips/筛选 Drawer/加载更多编排、内容区背景白底单源） | 2026-11-10 15:04 |
| [spec-table-improvements](spec-table-improvements.md) | SPEC 列表体验改进 | 2026-10-03 04:59 |
| [spec-list-filter-stickiness](spec-list-filter-stickiness.md) | 列表过滤条件保持 | 2026-10-03 04:59 |
| [add-spec-context-menu](add-spec-context-menu.md) | SPEC 列表右键菜单 | 2026-11-10 15:04 |
| [add-spec-priority-and-delete-api](add-spec-priority-and-delete-api.md) | SPEC 优先级与删除操作 | 2026-10-03 04:59 |
| [spec-detail-tabs](spec-detail-tabs.md) | SPEC 详情页签 | 2026-10-03 04:59 |
| [spec-detail-quick-switch](spec-detail-quick-switch.md) | SPEC 详情快速切换 | 2026-10-03 04:59 |
| [spec-doc-view](spec-doc-view.md) | SPEC 文档查看（端点契约、三页签懒加载与组件内缓存、GFM 安全渲染链接协议白名单、空态/错误态/加载态三态区分、入口与跳转隔离） | 2026-11-08 00:40
| [spec-status-actions-modal](spec-status-actions-modal.md) | 状态变更操作弹窗 | 2026-10-03 04:59 |
| [spec-approve-push-modal](spec-approve-push-modal.md) | 审批推送弹窗 | 2026-10-03 04:59 |
| [spec-timeline-accuracy](spec-timeline-accuracy.md) | 时间轴准确性（backward 序判定依赖生命周期枚举完整登记） | 2026-11-04 15:55 |
| [spec-timeline-admin-events](spec-timeline-admin-events.md) | 时间轴 admin 事件 | 2026-10-03 04:59 |
| [timeline-gate-failure-display](timeline-gate-failure-display.md) | 时间轴门禁失败展示 | 2026-10-03 04:59 |
| [task-progress-phase-display](task-progress-phase-display.md) | 任务进度按阶段呈现 | 2026-10-03 04:59 |
| [quality-gates-progress](quality-gates-progress.md) | 质量门禁进度呈现（详情页行渲染 Bento 勾选块形态，2026-11-06 对齐 v2 改版定形） | 2026-11-06 17:11 |
| [activity-records-tabs](activity-records-tabs.md) | 活动记录页签 | 2026-10-03 04:59 |
| [project-page-tabs](project-page-tabs.md) | 项目详情页签（六分面：项目首页居首/功能开发默认、tab 参数持久化 replace 语义、按需加载门控） | 2026-11-10 14:54 |
| [project-home-tab](project-home-tab.md) | 项目首页页签（只读文件浏览：git 可见文件树/目录导航与面包屑/内容渲染分通道（md 管线/图片 raw 直显/PrismLight 代码高亮/纯文本兜底）/文件下载/README GFM 安全渲染/URL path 持久化与挂载一次性 seed/project-files 四端点与路径越界防护） | 2026-11-10 18:13 |
| [dashboard-spec-archive](dashboard-spec-archive.md) | 归档查询视图 | 2026-10-06 17:00 |
| [ui-theme](ui-theme.md) | 主题切换 | 2026-10-03 04:59 |
| [spec-detail-page](spec-detail-page.md) | SPEC 详情页（常驻信息区 + 四页签：运行时间轴/场景结果/Bug 列表/失败截图，运行节点展开对话流按需加载，场景双空态语义，Bug 卡片与截图 lightbox） | 2026-10-03 04:59 |
| [activities-page](activities-page.md) | 运维记录页（三页签：处置链/自动运维记录/告警记录，默认处置链，`/chain` 重定向并入） | 2026-11-08 00:40
| [settings-page](settings-page.md) | 设置页（全表面命名「配置」避让 dsh 官方「设置」、四处标签同步面、左菜单 sticky 钉住、页面文档级滚动、全量卡 Bento 边框灰底准例、标题栏作用域控件移动端瘦身） | 2026-11-07 21:43 |
| [command-center-console-ui](command-center-console-ui.md) | 指挥中心三屏前端（/command-center ProLayout 嵌入页、org/pipeline/ledger 三 Tab+SPEC 视图、标题与双过滤迁统一标题栏（移动端双过滤落内容区首行）、theme.ts 配色单源与暗种子 *Bg 陷阱压制、五类卡片框 Bento 形态、Agent 卡流式自适应、连接线 ResizeObserver、SCREEN_CHROME_OFFSET 双档定高、KPI 条空值「—」、严肃企业风格红线） | 2026-11-07 21:43 |
| [dashboard-embed-mount](dashboard-embed-mount.md) | dashboard 嵌入挂载（apiBase 前缀单点、embed=1 壳层隐藏+统一标题行内嵌内容区首行、缺省行为不变） | 2026-11-05 18:27 |
| [harness-brand-projection](harness-brand-projection.md) | 对话视图 harness 品牌投影（context 缺省 Claude、run_metrics harness 键真相源、回退链、DshLogo 官方资产） | 2026-10-30 23:11 |
| [timeline-origin-request](timeline-origin-request.md) | 时间轴立项原话展示（fenix-new 立项原话 request.md 持久化、时间轴首 state 节点附着、前端引用块渲染、缺失静默降级） | 2026-10-31 17:53 |
| [page-container-chrome](page-container-chrome.md) | 内容区留白与边框治理（ProLayout token 留白单源、内容区间距 15px + 呼吸带 16px 标记类、零值尾部 spread 传导、去边框页级作用域豁免、前端冒烟加载纪律：hash 入口必须带 `/#/` 与 rebuild 后 reload 验证） | 2026-11-10 18:13 |
| [run-visual-agent-labels](run-visual-agent-labels.md) | run 时间轴 agent 标签映射（AGENT_LABEL/RUN_ID_PREFIX_LABEL 新车道登记纪律、漏登记回退「未知 Agent」） | 2026-11-04 17:46 |
| [unified-page-title-bar](unified-page-title-bar.md) | 全站统一标题栏（四槽位声明控件、SPEC 详情页中文标题富标题内部下方行堆叠（移动端只显英文标题、subtitle 槽行内形态保留既有消费面）、embed 行壳位单档 60px 毛玻璃固定标题带、standalone 含移动端统一注册落 ProLayout 顶栏（移动=汉堡+logo+标题同条、副标题移动端隐藏）、v2 六页经 titleBar 槽位并入、PageContainer 页头与面包屑退役、过滤项统一右上落位（filters 槽位=移动端标题栏右侧控件位单一定点）、定高偏移双档回校、脱壳大屏与占位页豁免） | 2026-11-08 00:40
| [document-scroll-unify](document-scroll-unify.md) | 帮助/设置页文档级滚动统一（滚动条跨标题区域三模式同构、目录/菜单 sticky 钉住 56/60 双档纯定位、两页无定高偏移与内滚、贴缘负边距不存续、守卫锁定） | 2026-11-05 20:37 |
| [project-ledger-bounded-scroll](project-ledger-bounded-scroll.md) | antd 表格限高滚动与 sticky 表头纪律（限高层钉 .ant-table-content、sticky 钉 thead>tr、rect 行高校准、几何证据验证；fenixd 台账磁贴不限高，「5 行封顶」原侧栏分区落地面已退役） | 2026-11-09 17:12 |
| [layout-chrome-tinting](layout-chrome-tinting.md) | 布局 chrome 底色 soft 染色统一（顶栏毛玻璃只换 rgb 通道双档、colorBgScrollHeader 必随配、菜单侧栏 soft 实底平涂一体、三处边框同取 colorSplit、soft 染色族守卫） | 2026-11-06 16:55 |
| [spec-detail-bento-skin](spec-detail-bento-skin.md) | SPEC 详情页 Bento 皮肤（顶栈五卡磁贴化、任务清单/质量门禁行渲染 Bento 勾选块形态（2026-11-06 对齐 v2 改版定形）、时间轴磁贴、页签区退出 bento 与卡体 padding 归零——内容交互零改动） | 2026-11-06 17:11 |
| [sidebar-submenu-bounded-scroll](sidebar-submenu-bounded-scroll.md) | 侧栏子菜单限高滚动与定制滚动条（独立访问侧栏 inline 子菜单 5 项封顶 200px、gutter stable、中性灰 alpha 滚动条五条、锚点唯一与动画共存、headless overlay 引擎量宽判据） | 2026-11-06 17:54 |
| [dsh-settings-ui-contract](dsh-settings-ui-contract.md) | dsh 设置 UI 架构契约与停靠插件（设置弹窗壳结构与 settings.section 插槽、稳定钩子面、useModalLayer 语义边界与 aria-modal 不可翻转、收缩态 56px 窄轨与触发按钮幂等开、停靠页面化三规） | 2026-11-07 21:32 |
| [dsh-web-connection-baseline](dsh-web-connection-baseline.md) | dsh web 连接基线与「重新连接中」重连环判读（浏览器 API 基线双门槛、低版本症状签名 101 正常零业务帧、close 4000 下游症状、健康握手对照、服务端/cookie/frp 排除面、console 优先与 tcpdump 取证纪律、无能力探测开放缺口） | 2026-11-07 21:36 |
| [dsh-web-wide-table-scrollbar](dsh-web-wide-table-scrollbar.md) | dsh web 对话框宽表横向滚动与全宽变量同步（wide/fill 分流、bleed 公式无下限缺陷、全宽覆盖须同步列宽变量、退化路径 margin 夹紧、哈希类失配自动回退、变量探针与活站假设验证配方） | 2026-11-07 21:40 |
| [prolayout-header-actions-minwidth-ratchet](prolayout-header-actions-minwidth-ratchet.md) | ProLayout 顶栏动作区 min-width 棘轮锁（ResizeObserver 实测回写自锁只升不降、filters 槽宽组件 SPA 残留锁宽挤压标题签名、global.less 单源恒零化勿删、顶栏挂宽组件零额外处理、分态复现与逐元素量宽排查定式） | 2026-11-07 22:03 |
| [timeline-chain-nodes](timeline-chain-nodes.md) | 时间轴处置链节点渲染（kind="chain" 紧凑链事件卡片 Bento 形态、六形态中文标签/着色映射圆点同源、未知形态中性灰兜底自有键防御、命名防混淆红线、折叠零特判与四类节点零回归） | 2026-11-08 12:14 |
| [fenix-dash-bridge-workspace-nav](fenix-dash-bridge-workspace-nav.md) | dsh 侧栏工作区行项目导航与富提示（名称点击=项目详情 iframe 深链、行首图标原生展开/收缩分流、名称悬停富提示深卡：简介/运行态/状态胶囊/任务/活跃 Agent、路径优先匹配判据、语义锚点拦截层与锚点漂移静默降级、原生提示互斥以常驻消解器兜底（竞速型观察器反模式）与交互面角色守卫（菜单/对话框/下拉不误伤、matches+querySelector 双查）、非 fenix 行零侵入、数据失效回退原生、固定条目收敛 5 项、60s 项目-工作区自动对齐、删除项目回退原生、官方列表滚动条注入维持、UI 可见性断言两件套与 portal 根排查定式、路径行沉淀数据面与 sink 可选方法实现红线（真 sink 集成回归+源码钉）、模块作用域探针法） | 2026-11-11 13:14 |
| [blocked-disposition-display](blocked-disposition-display.md) | blocked SPEC 处置相位三态显示（后端 `blocked_phase` 单点判定 repairing/queued/null——在飞处置 run/持久载体挂起件/等人面、升级件不入排队、显示层零状态机影响；前端四处共用 `blockedPhaseMeta` 三态标签与 fail-open 容错回退） | 2026-11-09 20:16 |
| [dsh-web-password-login](dsh-web-password-login.md) | dsh web 账号密码登录（fenix-dsh-auth 三 exact 路由接管、未认证首页登录页替代原生 401 文本、token 通道捕获-回放保留、登录自动带 token 瞬时中间态、设置「登录」分区与凭据端点契约、scrypt 哈希存储、同源校验与失败限流、六契约探测 warn-only 降级） | 2026-11-10 13:49 |
| [dsh-sidebar-right-tab-contract](dsh-sidebar-right-tab-contract.md) | dsh 右缘页签注册契约与文件定位落点（两段注册 definition+body seat、useTabInfo params 深链、keepMounted 跨会话保活、guide 发现入口、「侧边栏」=右缘 dock 语义定调、定位运行时落点优先级与可选注入服务降级序） | 2026-11-11 13:09 |
| [dsh-new-session-button](dsh-new-session-button.md) | dsh 侧栏同款「新会话」按钮（外观单点规格 38px/0.5px 描边/12px 圆角/new-chat-outline 内联图标、theme.ts 三常量配色单源、global.less 伪类态与压内联红线、仅 embed 态渲染、requestHostNewSession 点击分离、getComputedStyle hover 实测与测试钉行纪律） | 2026-11-12 18:00 |

> 退役注记：v2 商业化界面域十页（v2-overview-page / v2-project-list-page / v2-project-detail-page
> / v2-spec-detail-page / v2-config-page / v2-alerts-activities / v2-ops-page /
> v2-admin-doc-modals / v2-run-stream-modal / v2-commercial-ui）于 2026-11-07 用户指令随
> v2 六页代码整体退役删除（本域不再收录）；历史规则见
> spec/changes/redesign-dashboard-v2-ui 与 -mobile 两个 SPEC 目录及 git 历史。
> 一般域各页「镜像 v2 形态」条款已改历史出处口径（样式值保留）。
>
> 退役注记：SPEC 协作拓扑大屏（原 topology-bigscreen-ui）于 2026-11-08 用户指令退役批删除（页面/路由/派生端点整体移除）；协作图谱大屏（原 collab-graph-bigscreen-ui）功能代码已随 v2 界面域退役消失，本批补收口。历史见 spec/archive/2026-10-30-add-spec-topology-bigscreen、spec/archive/2026-10-30-add-collab-graph-bigscreen 与 git 历史。
>
> 退役注记：dsh 面板桥「项目」菜单行折叠开关与内嵌项目分区（原 dsh-bridge-projects-section）于 2026-11-09 随 move-project-nav-to-workspace-rows 退役删除——「项目」入口收敛进官方工作区行，现役规则见 fenix-dash-bridge-workspace-nav；历史见该 SPEC 与 git 历史。
