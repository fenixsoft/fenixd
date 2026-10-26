## MODIFIED Requirements

### Requirement: 管线视图七阶段列

管线视图保留七阶段列（需求/规划/开发/审查修复/测试验证/运维/交付）作为横向分组，
纵向从「列内排序」升级为**真实时间线性映射**：

- 节点纵坐标 = 节点时刻（started）到时间轴的线性映射；图高随时间跨度自适应；
- 时间重叠（并行）的节点水平对齐于同一时刻带，并行结构可直接读出；
- 先后顺序由纵轴位置直接表达（上→下=时间早→晚），同列同刻多节点按行错开
  （贪心行分配，协作时序视图 assignRows 同思路）；
- 节点持续时长可读（耗时文本保留，节点悬浮卡不变）；
- 无可定位时刻的节点（user/pm 空时刻、归档骨架）降级到锚定行渲染，图不断链；
- 在飞发光脉冲、失败/中止/弃置着色、fix 角标、悬浮详情卡、点击下钻等既有
  交互全部保留。

#### Scenario: 并行节点水平对齐（生成场景 ∥ 开发）

- **WHEN** planner-plan 与 implementer 同刻启动（实测样本
  `add-collab-graph-bigscreen`：两者 started 均为 2026-10-25T14:32:58Z）
- **THEN** 两节点在管线视图中水平对齐于同一时刻带（分处规划列/开发列），
  视觉上可辨认为并行执行

#### Scenario: 串行先后可读

- **WHEN** 6 轮 planner-judge 依次执行（started 依次为 15:11→15:32→15:55→
  16:06→16:26→16:39，实测样本）
- **THEN** 六节点纵坐标自上而下严格递增，先后顺序与间隔无需悬停即可读出

#### Scenario: 无时刻节点降级布局

- **WHEN** user/pm 节点无时刻（created 与 transitions 均空）或归档骨架 SPEC 打开大屏
- **THEN** 无时刻节点降级到固定锚定行渲染，不抛错、不出现 NaN 坐标

## ADDED Requirements

### Requirement: PMEngine 生命周期节点链

管线视图中，PMEngine 状态转移（`transitions`，每次 from→to 一条）渲染为**节点链**：
每次状态转换一个小节点（显示状态名与时刻），按时间串联在 PMEngine 节点处，
构成可见的生命周期链；各 run 的派发（dispatch）边自生命周期链上对应状态的节点
出发（按派发时刻落在哪个转移区间归位，区间无法定位时自 PMEngine 主节点出发）。

#### Scenario: 多次状态转换逐节点呈现

- **WHEN** transitions 含 9 条转移（实测样本 add-collab-graph-bigscreen 修复数据链路后）
- **THEN** 管线视图渲染 9 个状态转换节点（如 drafted→reviewing、ready→implementing…），
  每个节点显示目标状态名与时刻，链序与转移时序一致

#### Scenario: transitions 为空不渲染链不断链

- **WHEN** transitions 为空数组（归档 SPEC / 日志窗口无转移行）
- **THEN** 不渲染生命周期链，PMEngine 主节点保留，user→pm→各节点既有边不断链

### Requirement: 并行无伪串行边

管线视图的全局时序 handoff 链不再把并行节点串成伪依赖，判定为单一规则：画
handoff 边当且仅当前一节点与后一节点**串行**——`prev.end ≤ cur.start` 且
`prev.start < cur.start`（终点缺失按 start 处理）；时间重叠或同刻启动（含双零
时长同刻退化）一律不画。该规则同时满足下方两个 Scenario（串行贴邻含
prev.end == cur.start 保留边；同刻启动无边）。attempt 链 retry 边与 PMEngine
dispatch 边不受影响。

#### Scenario: 同刻启动节点间无 handoff 边

- **WHEN** implementer 与 planner-plan 同刻启动（实测样本 2026-10-25T14:32:58Z）
- **THEN** 派生边中不存在 `run:impl-… → run:planner-plan-…` 的 handoff 边

#### Scenario: 串行节点保留 handoff 边

- **WHEN** planner-judge 第 1 轮结束时刻不晚于第 2 轮开始时刻（串行判定链）
- **THEN** 相邻两轮之间保留 handoff 边
