# 仪表盘前端
> 最后更新：2026-11-05 20:37 UTC+8

仪表盘前端。本域能力条目清单如下（能力页由存量回填批次逐步产出，落盘后此处升级为链接）。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [dashboard-ui](dashboard-ui.md) | 仪表盘基础界面 | 2026-10-03 04:59 |
| [dashboard-overview](dashboard-overview.md) | 项目总览页 | 2026-10-03 04:59 |
| [dashboard-spec-table](dashboard-spec-table.md) | SPEC 列表表格 | 2026-10-06 17:00 |
| [spec-table-improvements](spec-table-improvements.md) | SPEC 列表体验改进 | 2026-10-03 04:59 |
| [spec-list-filter-stickiness](spec-list-filter-stickiness.md) | 列表过滤条件保持 | 2026-10-03 04:59 |
| [add-spec-context-menu](add-spec-context-menu.md) | SPEC 列表右键菜单 | 2026-10-03 04:59 |
| [add-spec-priority-and-delete-api](add-spec-priority-and-delete-api.md) | SPEC 优先级与删除操作 | 2026-10-03 04:59 |
| [spec-detail-tabs](spec-detail-tabs.md) | SPEC 详情页签 | 2026-10-03 04:59 |
| [spec-detail-quick-switch](spec-detail-quick-switch.md) | SPEC 详情快速切换 | 2026-10-03 04:59 |
| [spec-doc-view](spec-doc-view.md) | SPEC 文档查看 | 2026-10-03 04:59 |
| [spec-status-actions-modal](spec-status-actions-modal.md) | 状态变更操作弹窗 | 2026-10-03 04:59 |
| [spec-approve-push-modal](spec-approve-push-modal.md) | 审批推送弹窗 | 2026-10-03 04:59 |
| [spec-timeline-accuracy](spec-timeline-accuracy.md) | 时间轴准确性（backward 序判定依赖生命周期枚举完整登记） | 2026-11-04 15:55 |
| [spec-timeline-admin-events](spec-timeline-admin-events.md) | 时间轴 admin 事件 | 2026-10-03 04:59 |
| [timeline-gate-failure-display](timeline-gate-failure-display.md) | 时间轴门禁失败展示 | 2026-10-03 04:59 |
| [task-progress-phase-display](task-progress-phase-display.md) | 任务进度按阶段呈现 | 2026-10-03 04:59 |
| [quality-gates-progress](quality-gates-progress.md) | 质量门禁进度呈现 | 2026-10-07 03:30 |
| [activity-records-tabs](activity-records-tabs.md) | 活动记录页签 | 2026-10-03 04:59 |
| [project-page-tabs](project-page-tabs.md) | 项目详情页签 | 2026-10-03 04:59 |
| [dashboard-spec-archive](dashboard-spec-archive.md) | 归档查询视图 | 2026-10-06 17:00 |
| [ui-theme](ui-theme.md) | 主题切换 | 2026-10-03 04:59 |
| [v2-overview-page](v2-overview-page.md) | v2 总览页 | 2026-10-03 04:59 |
| [v2-project-list-page](v2-project-list-page.md) | v2 项目列表页 | 2026-10-03 04:59 |
| [v2-spec-detail-page](v2-spec-detail-page.md) | v2 SPEC 详情页 | 2026-10-03 04:59 |
| [v2-config-page](v2-config-page.md) | v2 配置页 | 2026-10-03 04:59 |
| [v2-alerts-activities](v2-alerts-activities.md) | v2 告警与活动页 | 2026-10-03 04:59 |
| [v2-admin-doc-modals](v2-admin-doc-modals.md) | v2 管理文档弹窗 | 2026-10-03 04:59 |
| [v2-run-stream-modal](v2-run-stream-modal.md) | v2 run 流弹窗 | 2026-10-03 04:59 |
| [v3-spec-detail-page](v3-spec-detail-page.md) | v3 SPEC 详情页 | 2026-10-03 04:59 |
| [v3-spec-doc-view](v3-spec-doc-view.md) | v3 SPEC 文档查看 | 2026-10-03 04:59 |
| [v3-activities-page](v3-activities-page.md) | v3 运维页（三页签：处置链/自动运维记录/告警记录，默认处置链，`/chain` 重定向并入） | 2026-11-05 18:19 |
| [v3-settings-page](v3-settings-page.md) | v3 设置页（左菜单 sticky 钉住、页面文档级滚动） | 2026-11-05 20:37 |
| [topology-bigscreen-ui](topology-bigscreen-ui.md) | SPEC 协作拓扑大屏（脱壳全屏双视图、管线视图纵轴真实时间+PM 生命周期链+并行无伪串行边、跨视图联动、下钻复用） | 2026-10-30 23:11 |
| [collab-graph-bigscreen-ui](collab-graph-bigscreen-ui.md) | 协作图谱大屏（overview 入口、8 角色固定就位、项目筛选器、下钻明细与跨大屏跳转） | 2026-10-30 23:11 |
| [command-center-console-ui](command-center-console-ui.md) | 指挥中心三屏前端（/command-center ProLayout 嵌入页、org/pipeline/ledger 三 Tab+SPEC 视图、标题与双过滤迁统一标题栏、theme.ts 配色单源与暗种子 *Bg 陷阱压制、Agent 卡流式自适应、连接线 ResizeObserver、SCREEN_CHROME_OFFSET 双档定高、KPI 条空值「—」、严肃企业风格红线） | 2026-11-04 20:48 |
| [dashboard-embed-mount](dashboard-embed-mount.md) | dashboard 嵌入挂载（apiBase 前缀单点、embed=1 壳层隐藏+统一标题行内嵌内容区首行、缺省行为不变） | 2026-11-05 18:27 |
| [harness-brand-projection](harness-brand-projection.md) | 对话视图 harness 品牌投影（context 缺省 Claude、run_metrics harness 键真相源、回退链、DshLogo 官方资产） | 2026-10-30 23:11 |
| [timeline-origin-request](timeline-origin-request.md) | 时间轴立项原话展示（fenix-new 立项原话 request.md 持久化、时间轴首 state 节点附着、前端引用块渲染、缺失静默降级） | 2026-10-31 17:53 |
| [page-container-chrome](page-container-chrome.md) | 内容区留白与边框治理（ProLayout token 留白单源、零值尾部 spread 传导、去边框页级作用域豁免、rebuild 后 reload 验证纪律） | 2026-11-04 17:07 |
| [run-visual-agent-labels](run-visual-agent-labels.md) | run 时间轴 agent 标签映射（AGENT_LABEL/RUN_ID_PREFIX_LABEL 新车道登记纪律、漏登记回退「未知 Agent」） | 2026-11-04 17:46 |
| [unified-page-title-bar](unified-page-title-bar.md) | 全站统一标题栏（四槽位声明控件、顶栏/内容区首行双壳位自动分流、embed 档 60px 毛玻璃固定标题带、PageContainer 页头与面包屑退役、过滤项统一右上落位、定高偏移 embed 双档回校、脱壳大屏与占位页豁免） | 2026-11-05 18:27 |
| [dsh-bridge-projects-section](dsh-bridge-projects-section.md) | dsh 面板桥「项目」菜单行折叠开关（点击=分区展开/折叠非主面板切换、右缘状态箭头、整行拦截层机制约束、键盘路径保留主面板注册） | 2026-11-05 18:14 |
| [v2-commercial-ui](v2-commercial-ui.md) | v2 商业化界面域（Bento 磁贴工作台六页：/v2/* 路由前缀隔离与现产菜单零污染、主题单源分立互不引用、定稿原型为 UI 真相源、真实 API 消费缺口「—」、DESIGN.md 例外域条款） | 2026-11-05 18:44 |
| [document-scroll-unify](document-scroll-unify.md) | 帮助/设置页文档级滚动统一（滚动条跨标题区域三模式同构、目录/菜单 sticky 钉住 56/60 双档纯定位、两页无定高偏移与内滚、贴缘负边距不存续、守卫锁定） | 2026-11-05 20:37 |
