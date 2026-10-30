# SPEC 协作拓扑大屏

<!-- knowledge: capability=topology-bigscreen-ui rev=1
     sources=spec/archive/2026-10-30-add-spec-topology-bigscreen,spec/archive/2026-10-30-improve-spec-topology-pipeline-view -->

单 SPEC 的「Agent 分工协作」IOC 大屏：脱壳全屏深色页面、双视图切换，回答哪些 Agent 参与、按什么顺序执行、哪些并行。

## 规则

- **独立脱壳页面**：前端路由 `/projects/:name/:spec/topology` 渲染全屏深色大屏——无 dashboard 侧边栏/亮色框架壳，顶部为 SPEC 名 + KPI 条（总耗时/总成本/派发完成重试计数/状态）+ 退出按钮（返回来源页）；不复用 dashboard 布局壳，现有所有页面路由与渲染行为零变化。
- **双视图切换式组织**：「管线视图」与「协作时序视图」胶囊切换、一屏独占渲染其一（不做并排）；渲染使用手写 SVG + React，MUST NOT 引入图表库依赖（ECharts/G6/X6 等）；切换后原视图卸载、KPI 条保持。
- **管线视图（阶段列 × 真实时间）**：七阶段列（需求/规划/开发/审查修复/测试验证/运维/交付）为横向分组；纵向为节点时刻到时间轴的线性映射——图高随时间跨度自适应（跨度 <60s 按 60s 兜底防除零）；时间重叠（并行）的节点水平对齐同一时刻带；先后顺序由纵轴位置直接表达（上→下=时间早→晚）；同列同刻多节点按行错开（贪心行分配）；节点持续时长可读（耗时文本与悬浮卡保留）；无可定位时刻的节点（user/pm 空时刻、归档骨架）降级到锚定行渲染，图不断链、不出现 NaN 坐标。
- **PMEngine 生命周期节点链**：`transitions` 每次状态转换渲染为一个小节点（目标状态名与时刻）按时间串联在 PMEngine 节点处，构成可见生命周期链；各 run 的派发边自生命周期链上对应状态节点出发（按派发时刻落在哪个转移区间归位，区间无法定位时自 PMEngine 主节点出发）；`transitions` 为空不渲染链，PMEngine 主节点与既有边不断链。
- **并行无伪串行边**：画 handoff 边当且仅当前后节点**串行**——`prev.end ≤ cur.start` 且 `prev.start < cur.start`（终点缺失按 start 处理）；时间重叠或同刻启动（含双零时长同刻退化）一律不画；attempt 链 retry 边与 PMEngine dispatch 边不受影响。
- **协作时序泳道视图**：角色泳道为行（用户、PMEngine、需求评审、规划、开发、审查/修复、测试/验证、运维）、真实时间为横轴——run 为色块（宽度=耗时、同泳道并行错行）；PMEngine 泳道含派发标记与状态转移刻度；用户泳道含人工动作标记；跨泳道箭头=交接；在飞 run 色块右端虚线尾迹；交付终点不单设泳道、以 PMEngine 泳道内 `pushed` 状态转移刻度收尾；时间刻度自适应（分钟/小时档）；SPEC 跨度长时支持横向滚动或缩放（泳道标签保持可见）。
- **跨视图联动高亮**：一个视图选中节点后切换视图，另一视图同步定位并高亮同一 run 的节点。
- **节点下钻复用运行记录**：点击 run 节点打开现有运行记录弹窗（`RunRecordModal`/`ClaudeOutputPane`）查看转录；PMEngine 节点展示状态转移记录；用户节点展示人工动作记录；MUST NOT 新建第二套转录查看组件。
- **状态着色与角标**：在飞（running）节点发光脉冲；失败/门禁拒绝红、中止橙、弃置中性灰；`fix-*` 子 SPEC 的 run 节点带 🔧 角标。
- **归档 SPEC 降级提示**：对 `archived: true` 的拓扑数据正常渲染状态骨架并显示「run 明细已随归档清理」显式提示，MUST NOT 渲染空白无解释页面。
- **实时刷新**：复用既有 SSE 通道，spec 数据变更后重新拉取拓扑数据全量重渲染；SSE 不可用时至少 30 秒轮询兜底。
- **现有界面零改动红线**：除 SPEC 列表新增菜单项与导航 handler、`SpecTimeline.tsx` 等价纯迁移（状态着色/角色映射抽为共享常量，渲染输出严格等价、纯函数单测背书）、路由表与服务层新增条目外，MUST NOT 改动任何现有页面/组件的行为与视觉；detail 页面与归档链路零改动。

## 溯源

- 2026-10-30 add-spec-topology-bigscreen（spec/archive/2026-10-30-add-spec-topology-bigscreen） — 新增本能力：脱壳大屏路由与入口、双视图切换（七阶段列管线 + 角色泳道时序）、跨视图联动、下钻复用、SSE/轮询刷新、SpecTimeline 等价迁移与零改动红线
- 2026-10-30 improve-spec-topology-pipeline-view（spec/archive/2026-10-30-improve-spec-topology-pipeline-view） — 修订：管线视图纵轴从列内排序升级为真实时间线性映射（并行水平对齐/先后可读/无时刻节点锚定行降级）、新增 PMEngine 生命周期节点链与派发边归位、并行同刻启动节点间不再画伪串行 handoff 边
