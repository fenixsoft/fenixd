# v2 总览页

<!-- knowledge: capability=v2-overview-page rev=2
     sources=spec/archive/2026-09-05-v2-overview-page,spec/knowledge/_inbox/done/v2-overview-titlebar-white-variant-1106.md -->

v2 域的项目总览入口（`/v2/overview`）：Bento KPI 磁贴 + 告警横幅 + 项目台账表格的白底满宽工作台，项目生命周期操作的列表级入口，桌面/移动双形态。

## 规则

- **页面形态**：`V2Page variant="overview"`——页底白（V2_WHITE）、内容列随外部容器满宽（无 1400px 居中收窄）、左右固定 30px；移动断点内回填 14px 侧距（移动原型形态不下探桌面 30px）。标题元数据经 V2Page `titleBar` 槽位声明进全站统一标题栏，页面零自画标题带（壳位机制见 `unified-page-title-bar`，域条款见 `v2-commercial-ui`）。
- **数据消费与刷新**：复用 `services/dashboard.ts` 既有客户端消费 `/api/` 端点，缺口字段「—」占位；数据刷新走 30s 心跳轮询（域条款），无 SSE 定向重拉通道。
- **KPI 磁贴行**：四卡等宽磁贴——SPEC 总数 / 任务进度圆环 / Token 消耗 / 活跃 Agent 堆叠条；桌面 auto-fit 网格、移动 2×2 网格 `minmax(0, 1fr)` 等宽钳制（移动形态「按类型分布」徽标与桌面圆环形态细节见 `v2-commercial-ui` 关键行为）。任务进度磁贴移动形态数值与「已完成」分两行。
- **告警横幅**：桌面多行明细 pre-wrap + 内嵌裁决选择题；移动端转胶囊卡（单条摘要 + 去处置/标记已处理双按钮 + 收起/展开渐进披露，次级告警行内嵌裁决 Select）。
- **项目台账表格（桌面）**：名称搜索 + 运行态 `.v2-chip` 胶囊筛选（激活黑底白字 `V2_PRIMARY`，非 antd 描边态）；行点击进项目详情——跳转语义由整行承载，不依赖行内按钮；操作列仅三点 Dropdown，收编 进入/停止/安装托管/删除 四项且进入居首（列宽 72），删除带 antd 确认框；项目名称格 PC 形态 pre-wrap 全显。
- **项目卡（移动）**：台账转堆叠项目卡——搜索过滤、卡片点击即进入详情；flex 纵列子项 `min-width: 0` 防撑破；简介 mobile 形态 `.v2-ellipsis` 单行省略；卡头更多菜单仅 停止/安装托管/删除（无进入项，进入由卡片点击承载）。

## 溯源

- 史前复原 — v2 概览页统计块 + 项目卡片 + 启停删操作 + SSE 重拉骨架；项目卡片点击跳转项目页
- 2026-09-05 v2-overview-page（spec/archive/2026-09-05-v2-overview-page） — 落地统计块 / 卡片数据适配（adaptOverview / adaptProjects）、生命周期操作 confirm 闭环与 sse:state / sse:refresh 定向重拉
- 2026-11-06 v2-overview-titlebar-white-variant-1106（spec/knowledge/_inbox/done/v2-overview-titlebar-white-variant-1106.md） — 整页改写为 Bento 工作台现状：KPI 四磁贴 + 告警横幅 + 项目台账表格、白底满宽变体（variant="overview"）、titleBar 槽位并入统一标题栏、筛选 `.v2-chip` 胶囊、操作列三点收编（进入居首）、移动 2×2 等宽钳制与项目卡简介单行省略；史前统计块/项目卡网格/启停删按钮/SSE 定向重拉规则废除
