# 指挥中心四屏前端

<!-- knowledge: capability=command-center-console-ui rev=1
     sources=spec/archive/2026-10-31-add-command-center -->

指挥中心大屏的前端面：`/command-center` 一页四屏（组织总览、交付流水线、裁决收件箱、执行台账）+ KPI 条，承载管理层 90 秒演示路径（组织总览 → SPEC 钻取 → 现场批一张裁决卡 → 台账收尾）。

## 规则

- **入口与页面骨架**：路由 `/command-center`，顶栏导航注册「指挥中心」菜单项（`src/app.tsx` menuDataRender）；页面为脱壳独立页，顶栏提供退出大屏按钮。四屏以 Tab 组织（antd Tabs），默认展示组织总览。
- **四屏独立加载与降级**：各屏数据独立加载；某屏对应端点返回 5xx 或超时时仅该屏渲染错误占位与重试按钮，其余屏与 KPI 条不受影响。后台静默刷新失败保留旧数据，不白屏。
- **数据接入与刷新**：复用既有 services 层 API client 模式（`src/services/dashboard.ts`）接入五个只读端点；页面以固定间隔（前端常量，≥30s，现值 60s）静默轮询，无用户操作下数据自更新，MUST NOT 引入新配置项。
- **组织总览屏**：按后端 org 数据渲染部门分区标题 + 区内车道卡 + 汇报线；汇报线以静态 SVG 细线随数据一次性绘制（无 SMIL 动画节点）。车道卡展示车道名、状态徽标（运行中/空闲）、今日 run 数、7 日成功率、14 日活动静态柱点 sparkline、7 日成本、最近活动时间；花名册内零 run 车道与活跃车道同尺寸出卡。点击有在飞 run 且可归属 SPEC 的车道卡跳转既有详情页 `/projects/:name/:spec`；归属不可得时点击 MUST 禁用。
- **交付流水线屏**：五列泳道（列头：需求评审/待实现/实现中/验证中/已推送），列归属按聚合层桶映射；卡片显示项目 Tag + SPEC 名，保留原生 status 徽标；implementing 列卡带 `running` 时显示在飞 lane 与开始时间。点击卡片跳转 `/projects/:name/:spec`。项目筛选下拉数据源为响应 `projects` 全集，含「全部项目」项。
- **裁决收件箱屏**：待决卡渲染严重度徽标、项目/SPEC 溯源链接、signal_type、调查叙事全文、选项组（label + desc，destructive 选项带「不可逆」红标）。选项执行调用既有 `POST /api/alert-resolve`：成功后该卡移出待决列表并触发 KPI 条刷新；`destructive` 选项执行前弹二次确认（确认语义由选项数据驱动），取消则不发起请求；执行失败卡片保留、内联错误展示、可重试。无待决时显示空态「无待人工裁决事项」。
- **执行台账屏与 KPI 条**：KPI 条展示四指标（7 日交付 SPEC / 人工介入率 / run 成功率 / 单 SPEC 成本）+ 网关状态徽标；`null` 指标 MUST 显示「—」而非 0。台账表格列：项目、SPEC、车道、结果、耗时、tokens、成本、开始时间、trigger（null 显示「—」）。项目筛选与流水线屏同一数据源模式。
- **严肃企业风格硬约束**：采用与 dashboard 一致的暗色控制台风格（数据墨水优先、小号大写标签、静态细线）；MUST NOT 出现插画、动画角色/像素小人、吉祥物、装饰性动效；复用既有 antd 暗色 token 与 tailwind 配置，不引入新色板。
- **钻取不新建详情页**：SPEC 详情一律复用既有 `/projects/:name/:spec` 页面，指挥中心不建自有详情视图。

## 溯源

- 2026-10-31 add-command-center（spec/archive/2026-10-31-add-command-center） — 新增本能力：四屏 Tab 页与导航入口、静态 SVG 汇报线与 sparkline、一键裁决（复用 alert-resolve + destructive 二次确认 + 失败保留现场）、KPI 条空值「—」形态、严肃企业风格红线与 ≥30s 静默轮询
