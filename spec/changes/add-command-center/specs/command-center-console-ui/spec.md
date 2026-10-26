## ADDED Requirements

### Requirement: 指挥中心页面与导航入口

前端 SHALL 新增路由 `/command-center`（指挥中心页）并在顶栏导航注册「指挥中心」菜单项（`src/app.tsx` menuDataRender）。页面 SHALL 以 Tab 组织四屏：组织总览、交付流水线、裁决收件箱、执行台账，默认展示组织总览。页面 MUST 复用既有 services 层 API client 模式（`src/services/dashboard.ts`）接入五个只读端点。

#### Scenario: 导航与默认屏
- **WHEN** 用户打开 dashboard 并点击「指挥中心」菜单
- **THEN** 进入 `/command-center` 且默认渲染组织总览 Tab，四 Tab 均可切换

#### Scenario: 端点故障降级
- **WHEN** 某屏对应端点返回 5xx 或超时
- **THEN** 仅该屏渲染错误占位与重试按钮，其余屏与 KPI 条不受影响

### Requirement: 组织总览屏

组织总览屏 SHALL 按后端 `org` 数据渲染：部门分区标题 + 区内车道卡 + 汇报线。汇报线 SHALL 以静态 SVG 细线绘制（随数据一次性渲染，MUST NOT 使用动画）。车道卡 SHALL 展示：车道名、状态徽标（working=在飞/idle=空闲）、今日 run 数、7 日成功率、14 日活动 sparkline（静态柱点）、7 日成本（`cost_7d`）、最近活动时间。花名册内零 run 车道 MUST 与活跃车道同尺寸出卡。点击有在飞 run 的车道卡 SHALL 跳转该 run 所属 SPEC 的既有详情页 `/projects/:name/:spec`（所属 SPEC 不可得时卡片点击 MUST 禁用）。

#### Scenario: 分区与卡片渲染
- **WHEN** org 数据返回 4 个分区、花名册卡与 1 条静态汇报线集合
- **THEN** 页面按分区分组渲染全部车道卡（含零 run 卡），汇报线以静态 SVG 呈现且无任何动画元素
- **WHEN** 用户点击 status=working 且可归属 SPEC 的 implementer 卡
- **THEN** 跳转到对应 `/projects/:name/:spec` 详情页

### Requirement: 交付流水线屏

交付流水线屏 SHALL 渲染五列泳道：drafted、ready、implementing、verifying、pushed（列归属按聚合层五列桶映射，覆盖 SpecStatus 全量；卡片可显示原生 status 徽标），卡片含项目名、SPEC 名，implementing 列卡有 `running` 时 SHALL 显示在飞 lane 与开始时间。点击卡片 SHALL 跳转既有 `/projects/:name/:spec` 详情页。SHALL 提供项目筛选下拉（数据源为响应 `projects` 全集，含「全部项目」项）。

#### Scenario: 泳道与钻取
- **WHEN** pipeline 数据返回五列卡与 projects 全集
- **THEN** 五列按状态归组渲染，筛选切换项目后仅剩该项目卡片
- **WHEN** 用户点击任一卡片
- **THEN** 跳转到该 SPEC 既有详情页

### Requirement: 裁决收件箱屏

裁决收件箱屏 SHALL 将 inbox 待决卡渲染为决策卡：严重度徽标、项目/SPEC、signal_type、narrative 全文、溯源链接与选项组（label+desc）。选项执行 SHALL 调既有 `POST /api/alert-resolve`，成功后该卡 MUST 移出待决列表并触发 KPI 刷新；`destructive` 选项执行前 MUST 弹二次确认（确认语义由选项数据驱动，与既有前端回退清单行为一致）。执行失败 SHALL 保留卡片并展示错误。无待决时 SHALL 显示空态文案「无待人工裁决事项」。

#### Scenario: 一键裁决成功路径
- **WHEN** 用户在待决卡上选择非 destructive 选项并确认执行，alert-resolve 返回成功
- **THEN** 该卡从列表移除，KPI 条数值刷新

#### Scenario: destructive 二次确认
- **WHEN** 用户选择 destructive=True 的选项
- **THEN** 先弹二次确认，确认后才执行；取消则不发起请求

#### Scenario: 执行失败保留现场
- **WHEN** alert-resolve 返回错误
- **THEN** 卡片保留在列表，展示错误信息，可重试

### Requirement: 执行台账屏与 KPI 条

执行台账屏 SHALL 渲染 KPI 条与台账表格。KPI 条 SHALL 展示四指标 + 网关状态徽标；`null` 指标 MUST 显示「—」而非 0。台账表格列：项目、SPEC、车道、结果、耗时、tokens、成本、开始时间、trigger（null 显示「—」）。 SHALL 提供项目筛选（与流水线屏同一数据源模式）。

#### Scenario: KPI 条与空值
- **WHEN** kpi 数据返回 `run_success_rate_7d=0.8`、`cost_per_spec_7d=null` 与 gateway_health
- **THEN** 成功率显示 80%，单 SPEC 成本显示「—」，网关徽标按 health 数据渲染

#### Scenario: 台账渲染
- **WHEN** ledger 返回 50 行
- **THEN** 表格按开始时间倒序渲染全部行，trigger=null 行该列显示「—」

### Requirement: 严肃企业风格硬约束

指挥中心页 MUST 采用与 dashboard 一致的暗色控制台风格（数据墨水优先、小号大写标签、静态细线）。MUST NOT 出现：插画、动画角色/像素小人、吉祥物、装饰性动效。页面 SHALL 以固定间隔（前端常量，≥30s）静默刷新数据，MUST NOT 引入新配置项。

#### Scenario: 风格与刷新
- **WHEN** 页面渲染完成并静置 2 个刷新周期
- **THEN** 数据在无用户操作下更新两次，页面无动画角色/插画元素，四屏汇报线与图表均为静态渲染
