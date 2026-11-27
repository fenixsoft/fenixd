<!-- knowledge: capability=dashboard-overview rev=6 sources=spec/archive/2026-09-02-add-multi-project-monitoring,spec/archive/2026-09-18-fix-dashboard-fault-isolation,spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md,spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md,spec/archive/2026-11-27-consolidate-alerts-to-ops-page,spec/knowledge/_inbox/done/2026-11-16-overview-narrow-width-wrap-and-ledger-scroll-floor.md -->

# 项目总览页

Dashboard 首页的跨项目概览：Bento 统计卡 + 项目台账磁贴（桌面表格 / 移动堆叠卡双形态），2 秒自动刷新，故障隔离可降级；视觉消费 v2 商业化域走镜像不引用。

## 现行规则

- 概览页不承载告警信息面：不渲染告警横幅、告警列表、裁决控件或「清理所有事件」入口，也不为告警展示维护专属数据管线（无告警 SSE 订阅、无告警合帧、无告警降级轮询，页面内 MUST NOT 残留 `getAlerts`/`clearAllAlerts` 引用）；告警感知面收敛到运维菜单徽标与运维页告警记录页签。既有 `GET /api/overview` 心跳刷新与故障隔离降级行为不受影响。
- 页面顶部为统计卡：SPEC 总数、任务进度、活跃 Agent、Token 消耗四卡，卡片等高、数值与说明两端对齐；统计卡为 Bento 磁贴形态（#eef2f7 发丝边 + 12 圆角 + 软阴影，圆角取全站统一的 Bento 磁贴 12px 条款）。
- 统计卡行网格样式收 global.less 单源（页内 inline 样式会挡媒体查询，不得回迁 inline）；<768px 转 2×2 网格，列轨 `minmax(0,1fr)`（钳掉 1fr 隐式 auto 下限，防长内容撑破，v2 同款）、gap 12；统计卡 body 内边距 14px 16px（对齐 v2 移动磁贴）。
- 下方项目清单为台账表格磁贴（`pages/overview/components/ProjectTable.tsx`），呈现复制自 v2 overview 的台账磁贴两形态（v2 域 2026-11-07 已退役，本组件为独立存量）：桌面（≥768px）= 台账表格，移动（<768px）= 堆叠项目卡；桌面磁贴不限高、无 sticky 表头——「5 行封顶滚动」需求的落地面是 dsh web 侧栏「项目」分区，antd 表格限高滚动与 sticky 纪律由 project-ledger-bounded-scroll 页留存。
- 台账行为契约不随视觉形态切换：乐观删除与在飞 pending 记账语义沿用，删除/结算后经 onProjectRemoved/onProjectSettle 同步侧边栏菜单；行点击跳转本产项目页 `/projects/:name`（不跳 /v2/）；错误态与 `exists=false` 的不可读行数据列渲染「—」，不伪装 0。
- 台账行呈现 daemon 运行态徽标（`daemon="running"` 显示「运行中」正向色，`daemon="stopped"` 显示「未运行」弱化/警示色）、SPEC 数/任务进度/问题阻塞/活跃运行等数据列与「自动」发现标记；SPEC 数、问题阻塞、活跃运行三个数字列居中对齐。
- 台账列宽与横向滚动下限为视口双档单源（`LEDGER_WIDTHS` 常量；断点取 antd xl=1200px，`useMediaQuery('(max-width: 1199.98px)')` 首帧同步取值）：≥1200px 宽档固定列 SPEC 数 96 / 任务进度 220 / 问题阻塞 108 / 活跃运行 108 / 操作 72（合计 604）+ `scroll.x=890`（= 604 + 无宽度「项目」列最小 286）；<1200px 窄档 80/190/92/92/56（合计 510）+ `scroll.x=700`（= 510 + 项目列最小 190），窄档是窄桌面档其余列让位下限，与移动分支（<768px 堆叠卡）正交。容器宽度 ≥ 当档 scroll.x 下限时表格按 100% 铺满、「项目」列吃剩余空间，宽视口列宽分配不变（PC 零影响）。固定列宽下限须按表头/内容实宽核算（如「问题/阻塞」表头约 78px ≤ 92），不得拍脑取值。
- 横向滚动条治理以「消除」为目标，`scroll.x` 下限与固定列让位双管齐下缺一不可：antd Table 固定布局下 px 列宽不随容器收缩，只调 scroll.x 下限时固定列不收缩，容器更窄处滚动条必复发。实测边界口径：1200px 视口 sider 展开态容器 912px 走宽档无横向滚动条；994px 视口 sider 收起态容器 898px、展开态容器 706px 均走窄档无横向滚动条（展开态项目列 196px）。
- ProjectTable 台账 JSX 开标签内的属性位注释使用 `//` 行注释形态（文件既有惯例）；`{/* */}` 表达式容器在 JSX 属性位非法，esbuild 直接构建失败（报 `Expected "..." but found "}"`）。
- 运行态筛选（全部/运行中/未运行）为 antd Radio 并排按钮组（原版样式），激活项黑底白字——挂独立单源覆写类 `.ov-radio-dark`（DESIGN.md 一般域条款；projects 页两组过滤同挂同源类）；独立胶囊形态（.ov-chip）已退役，守卫禁回潮。移动端不渲染筛选行（v2 原型无筛选行）；与 v2 域自身筛选胶囊（.v2-chip）的形态分叉系有意为之，不应对齐。
- 行级错误态：项目摘要 `error` 字段非空时该行呈错误态（警示色）并展示错误原因文案，不得以正常徽标/进度数字形态呈现误导；错误行不被静默过滤——它本身就是「该项目当前不可用」的可见信号；单项目错误态不影响其它行、`totals` 展示或页面整体可用性。
- 所有被监控项目在同一概览页统一展示，任意项目可下钻其项目页；概览每 2 秒自动刷新（轮询 `/api/overview`）。
- 多项目状态自动跟随：新启动 daemon 的项目（被发现或已注册）在服务端发现缓存（默认约 10s）与健康缓存（默认约 5s）过期后自动出现/更新，无需重启 Dashboard 服务或手动刷新。
- 加载失败降级：`/api/overview` 请求失败且此前无成功数据时，显示错误提示与「重试」入口（触发重新请求），不得渲染空白页、空白骨架或永久加载态；已成功加载过之后刷新失败（30s 心跳或 SSE 触发的重载），继续展示上一次成功的数据并在其上显示错误提示，不得清空已展示的台账/统计与 `totals`；下一次刷新成功后展示最新数据、错误提示消失。
- 视觉形态出处=复制不引用：overview 侧台账磁贴复制自 v2 并保留 `OV_*` 常量与 global.less `.ov-*` 规则族（v2 域 2026-11-07 退役，现为独立存量，「两处同改」镜像同步指令随之失效），不存在跨域 import（原 DESIGN.md v2 例外域条款已随域退役外禁引用，守卫测试拦截跨域 import）。
- PageContainer 页级去阴影规则（`box-shadow: none`）会打到统计卡：Bento 软阴影必须挂高特异性豁免规则（1 id + 3 类）覆写，且置于去阴影规则之后。

## 溯源

- 史前复原 — 概览页统计卡与项目清单布局基线（四卡、卡片等高、数值与说明两端对齐）
- 2026-09-02 add-multi-project-monitoring（spec/archive/2026-09-02-add-multi-project-monitoring） — 新增 daemon 健康徽标、「自动」标记保留与多项目状态自动跟随（发现/健康缓存过期自愈）
- 2026-09-18 fix-dashboard-fault-isolation（spec/archive/2026-09-18-fix-dashboard-fault-isolation） — 新增项目级错误态展示与错误卡片不静默过滤，建立概览加载失败降级（重试入口 + 保留上次成功数据）
- 2026-11-06 overview-ledger-bento-align-1106（spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md） — 项目清单由项目卡片墙改写为台账表格磁贴（ProjectTable，桌面表格/移动堆叠卡双形态、行为契约不随视觉切换）、统计卡换 Bento 皮肤与网格迁 global.less（移动 2×2）、运行态筛选改 Radio 黑底白字（.ov-radio-dark）、数字列居中；登记跨域镜像不引用纪律与 PageContainer 去阴影陷阱
- 2026-11-06 antd-table-scroll-maxheight-sticky-th-1106（spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md） — 台账磁贴细则句改写为不限高口径：表格限高方案撤销，「5 行封顶」落地面为 dsh web 侧栏项目分区
- 2026-11-12 consolidate-alerts-to-ops-page（spec/archive/2026-11-27-consolidate-alerts-to-ops-page/） — 概览页告警面整体退役入页：AlertBanner 组件、横幅样式与页级专属告警 SSE 管线删除，页面收敛为统计卡+项目台账+错误态/降级视图，心跳与降级行为不变
- 2026-11-16 2026-11-16-overview-narrow-width-wrap-and-ledger-scroll-floor（spec/knowledge/_inbox/done/2026-11-16-overview-narrow-width-wrap-and-ledger-scroll-floor.md） — 登记台账列宽视口双档（LEDGER_WIDTHS 宽档合计 604+scroll.x 890 / 窄档合计 510+700，断点 1200px）与横向滚动条消除口径（scroll.x 下限+固定列让位双管齐下）、ProjectTable JSX 属性位注释形态惯例
