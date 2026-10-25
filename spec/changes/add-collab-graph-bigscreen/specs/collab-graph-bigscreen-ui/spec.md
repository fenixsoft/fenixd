## ADDED Requirements

### Requirement: overview 入口与脱壳大屏路由

overview 页 MUST 新增「协作图谱大屏」入口（不改动现有内容布局语义）；点击进入 `/overview/collab-graph` 独立路由：全屏深色、无 dashboard 框架壳，顶部为大屏标题 + 全局 KPI 条 + 项目筛选器 + 退出按钮（返回 overview）。前端渲染 MUST 手写 SVG + React，MUST NOT 引入图表库依赖。

#### Scenario: 入口进入大屏

- **WHEN** 在 overview 页点击「协作图谱大屏」
- **THEN** 跳转 `/overview/collab-graph`，呈现全屏深色图谱页面，无侧边栏

#### Scenario: 退出返回

- **WHEN** 点击退出按钮
- **THEN** 返回 overview 页

### Requirement: 角色固定就位图谱

图谱 MUST 将 8 个角色节点按 SDLC 阶段固定就位（用户→PMEngine→需求评审→规划→开发→审查/修复→测试/验证→运维→交付方向的确定性布局，无力导向算法），两次进入同一页面节点位置 MUST 一致。节点大小映射累计成本或时长（实现裁量取一，全屏一致），在飞角色节点发光脉冲；边宽映射交接次数（weight），有交接流动的边 MUST 有方向指示。

#### Scenario: 固定就位可预期

- **WHEN** 两次进入大屏（期间数据有变化）
- **THEN** 节点位置完全一致，仅大小/边宽/脉动随数据变化

#### Scenario: 边宽随交接次数变化

- **WHEN** 「规划→开发」边 weight 为 20、「测试/验证→运维」边 weight 为 2
- **THEN** 前者边显著宽于后者（同一映射函数下）

### Requirement: 项目筛选器

页面 MUST 提供项目筛选器（全部 + 各项目），切换后图谱与 KPI 重新按该范围聚合；筛选器当前选中态 MUST 可辨识。

#### Scenario: 切换单项目

- **WHEN** 筛选器从「全部」切到某单项目
- **THEN** 图谱边与 KPI 仅反映该项目数据

### Requirement: 下钻明细与跨大屏跳转

点击角色节点或边 MUST 打开下钻明细面板：列出该角色（或该交接对）最近的 run/交接明细，每条含项目名、SPEC 名、时间、状态；明细条目 MUST 提供跳转到对应 SPEC 单 SPEC 协作拓扑大屏（`/projects/<name>/<spec>/topology`）的入口。归档 SPEC 条目 MUST 标注「明细已归档清理」且不可跳转单 SPEC 大屏（或跳转后由其降级提示承接）。

#### Scenario: 节点下钻列明细

- **WHEN** 点击开发角色节点
- **THEN** 面板列出最近的开发 run 明细（项目/SPEC/时间/状态），并可跳转对应单 SPEC 大屏

### Requirement: 归档口径注记

响应含 `archived_excluded > 0` 时，页面 MUST 显示口径注记（如「N 个已归档 SPEC 仅计入 KPI，不计入图谱」）。

#### Scenario: 注记可见

- **WHEN** 存在已归档 SPEC
- **THEN** 图谱页面可见归档口径注记文案

### Requirement: 实时刷新

页面 MUST 在项目/SPEC 数据变更后重新拉取聚合数据（复用既有 SSE 通道或失效信号），SSE 不可用时 MUST 至少 30 秒轮询兜底；在飞节点的出现/消失 MUST 随刷新可见。

#### Scenario: 在飞角色实时点亮

- **WHEN** 某项目新派发开发 run 并推送 SSE
- **THEN** 大屏刷新后开发节点进入在飞脉动态

### Requirement: 现有界面零改动红线

除 overview 页新增入口、路由表与服务层新增条目外，MUST NOT 改动任何现有页面/组件行为与视觉；单 SPEC 大屏（`add-spec-topology-bigscreen` 交付物）与归档链路 MUST 零改动。

#### Scenario: overview 既有内容不变

- **WHEN** 审查本 change 交付物 diff
- **THEN** overview 页 diff 仅含入口新增，既有卡片/列表渲染逻辑无改动
