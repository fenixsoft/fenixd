## ADDED Requirements

### Requirement: 独立脱壳大屏页面

MUST 新增前端路由 `/projects/:name/:spec/topology` 渲染全屏深色大屏页面：无 dashboard 侧边栏/亮色框架壳，顶部为 SPEC 名 + KPI 条（总耗时/总成本/派发完成重试计数/状态）+ 退出按钮；退出按钮 MUST 返回来源页。页面 MUST NOT 复用 dashboard 布局壳；现有所有页面路由与渲染行为 MUST 保持不变。

#### Scenario: 入口进入大屏

- **WHEN** 在 SPEC 列表「更多」菜单点击「协作拓扑」
- **THEN** 跳转 `/projects/:name/:spec/topology`，呈现全屏深色页面，无侧边栏

#### Scenario: 退出返回

- **WHEN** 点击右上角「退出大屏」
- **THEN** 返回该项目 SPEC 列表或详情页

### Requirement: 双视图切换式组织

页面 MUST 提供「管线视图」与「协作时序视图」两个视图，胶囊切换器一屏独占渲染其一（不做并排）。渲染 MUST 使用手写 SVG + React，MUST NOT 引入图表库依赖（ECharts/G6/X6 等）。

#### Scenario: 胶囊切换

- **WHEN** 点击切换器另一视图
- **THEN** 原视图卸载、新视图独占画布，KPI 条保持

### Requirement: 管线视图七阶段列

管线视图 MUST 按 7 阶段列（需求/规划/开发/审查修复/测试验证/运维/交付）左→右排布节点：用户/fenix-new 为需求列入口节点、PMEngine 为规划列调度节点；同角色多轮在同列重复出现（按时间自上而下）；交接边实线、重试边橙色、并行 run 的边自 PMEngine 出发；在飞（running）节点发光脉冲，失败/门禁拒绝红、中止橙、弃置中性灰。`fix-*` 子 SPEC 的 run 节点带 🔧 角标。

#### Scenario: 在飞节点发光

- **WHEN** 存在 status=running 的 run 节点
- **THEN** 该节点描边发光并脉冲，KPI 计数含其在飞状态

#### Scenario: 多轮同列重复

- **WHEN** 开发列存在 3 个不同 run 的开发节点
- **THEN** 开发列纵向呈现 3 个节点

### Requirement: 协作时序泳道视图

协作时序视图 MUST 以角色泳道为行（用户、PMEngine、需求评审、规划、开发、审查/修复、测试/验证、运维）、真实时间为横轴：run 为色块（宽度=耗时、同泳道并行错行）、PMEngine 泳道含派发标记与状态转移刻度、用户泳道含人工动作标记、跨泳道箭头=交接、在飞 run 色块右端虚线尾迹。交付终点节点不单设泳道，以 PMEngine 泳道内 `pushed` 状态转移刻度收尾呈现。时间刻度 MUST 自适应（分钟/小时档）；SPEC 时间跨度长时 MUST 支持横向滚动或缩放。

#### Scenario: 色块宽度对齐耗时

- **WHEN** 两个 run 耗时分别为 10 分钟与 60 分钟
- **THEN** 后者色块宽度为前者 6 倍（同刻度下）

#### Scenario: 长跨度可滚动

- **WHEN** SPEC 跨度超过视口宽度
- **THEN** 时间轴可横向滚动（或缩放），泳道标签保持可见

### Requirement: 跨视图联动高亮

在一个视图选中节点后切换视图，另一视图 MUST 同步定位并高亮同一 run 的节点。

#### Scenario: 切换后同步高亮

- **WHEN** 在管线视图选中某 run 节点后切换到协作时序视图
- **THEN** 协作时序视图中对应色块处于高亮态

### Requirement: 节点下钻复用运行记录

点击 run 节点 MUST 打开现有运行记录弹窗（`RunRecordModal`/`ClaudeOutputPane`）查看转录；点击 PMEngine 节点展示状态转移记录；点击用户节点展示人工动作记录。MUST NOT 新建第二套转录查看组件。

#### Scenario: 点击 run 节点下钻

- **WHEN** 点击某个 run 节点
- **THEN** 弹出现有运行记录弹窗并加载该 run 转录

### Requirement: 归档 SPEC 降级提示

对 `archived: true` 的拓扑数据，页面 MUST 正常渲染状态骨架并显示「run 明细已随归档清理」显式提示；MUST NOT 渲染空白无解释页面。

#### Scenario: 归档 SPEC 打开大屏

- **WHEN** 打开已归档 SPEC 的大屏页面
- **THEN** 显示状态骨架与降级提示横幅

### Requirement: 实时刷新

页面 MUST 复用既有 SSE 通道在 spec 数据变更后重新拉取拓扑数据（全量重渲染）；SSE 不可用时 MUST 至少 30 秒轮询兜底。

#### Scenario: 在飞 run 上屏

- **WHEN** SSE 推送该 SPEC 的新 run 事件
- **THEN** 页面重新拉取拓扑并渲染新节点

### Requirement: 现有界面零改动红线

除 `list.tsx` 新增菜单项与导航 handler、`SpecTimeline.tsx` 等价纯迁移、路由表与服务层新增条目外，MUST NOT 改动任何现有页面/组件的行为与视觉。`SpecTimeline.tsx` 迁移后渲染输出 MUST 与迁移前严格等价（纯函数单测背书）；detail 页面与归档链路 MUST 零改动。

#### Scenario: SpecTimeline 等价迁移

- **WHEN** 抽取状态着色/角色映射为共享常量后渲染任意时间轴 fixture
- **THEN** 渲染结果与迁移前一致（纯函数断言通过），行为与视觉零变化

#### Scenario: 归档链路零改动

- **WHEN** 审查本 change 交付物 diff
- **THEN** `archive_spec_runs` 所在归档链路无任何改动
