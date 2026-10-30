# 提案：SPEC 协作拓扑管线视图时序化改进

## Why

SPEC 协作拓扑页（`/#/projects/<project>/<spec>/topology`）的管线视图无法回答三个基本问题：哪些 Agent 参与了协作、按什么顺序执行、哪些是并行的。以 `add-collab-graph-bigscreen` 实测取证：

1. **需求评审 Agent 整体不可见**（数据 bug）：需求评审 run_id 恒插入 6 位 uuid 段
   （`core/pm_engine/spec_review.py:392`），`run_spec_part` 推断出带尾巴的
   `<spec>-<6hex>`，family 全等匹配失败 → 所有 SPEC 的 spec-review run 节点全部丢失。
2. **状态转换不可见**：PMEngine 生命周期转移（drafted→reviewing→ready→implementing→…→pushed）
   数据已派生下发但管线/泳道视图均未渲染（仅藏在 PM 节点点击弹窗）；且本 SPEC 实测
   transitions=0——daemon 日志首行存在 6.6MB 巨型行（admin_monitor 信号把 51054 个
   untracked entry 全文嵌入 context，`core/logger.py:41` 序列化无体积上限），锚定
   窗口首行探测失败回退文件头后，1MB 窗口整体落在巨型行内部，锚点后事件全部丢失。
3. **先后与并行不可见**（视图 bug）：管线视图按七阶段列布局、纵坐标仅排序不做时间
   映射——生成场景（planner-plan）与开发（implementer）同刻启动的并行结构不可见，
   6 轮判定（planner-judge）串行的先后持续不可读；全局时序链还把并行节点强行串成
   伪 handoff 边（`开发 → 生成场景`），进一步误导。

## What Changes

- **（修复）需求评审 run 归属**：`run_spec_part` 对 spec-review 形态
  （`spec-review-<spec>-<6hex>-<ts>`）剥除 uuid 段，恢复单源推断正确性——
  拓扑/时间轴/运行记录归属全部受益。
- **（修复）日志读侧锚定窗口健壮性**：块首行探测失败或窗口被超长行占满时，
  跳过超长行内容（不整读入内存），保证锚点时刻之后的可解析事件不因单个巨型行丢失。
- **（修复）日志写侧单事件体积上限**：`core/logger.py` 序列化加截断防御，
  超限事件截断并留痕，防止单条 context 再次撑爆日志窗口。
- **（视图）管线视图纵轴改真实时间**：列=阶段保留，节点纵坐标按真实时间线性映射，
  同刻/时间重叠节点水平对齐（并行一目了然），上→下即执行先后，持续时长可读。
- **（视图）PMEngine 生命周期节点链**：每次状态转换渲染为带时刻与状态名的小节点，
  串成生命周期链置于 PMEngine 节点处；派发边自对应状态节点出发。
- **（视图）伪 handoff 边清理**：时间重叠/同刻启动的节点间不再画串行 handoff 边，
  并行结构由时间轴对齐直接表达。
- 泳道视图（协作时序）因数据修复自动恢复需求评审泳道与 PM 状态转移刻度，不改结构。

## Capabilities

### 修改的能力

- **specs/topology-derivation/**（MODIFIED，现存于活跃变更 add-spec-topology-bigscreen）：
  run 归属判定新增 spec-review uuid 段剥除；拓扑派生对超长日志行健壮。
- **specs/topology-bigscreen-ui/**（MODIFIED，同上）：管线视图时间对齐布局、
  PM 生命周期节点链、伪 handoff 边清理。

### 新增的能力

- **specs/daemon-log-event-governance/**（ADDED）：daemon 日志单事件读侧
  （锚定窗口跳过超长行）与写侧（序列化体积上限）双重治理。

## Impact

- **影响代码**：`core/agent_runner/run_files.py`（归属单源）、`core/logger.py`
  （写侧截断）、`core/dashboard/data/log_index.py`（读侧窗口）、
  `core/dashboard/data/topology.py`（派生适配）、
  `core/dashboard/static/src/pages/projects/topology/PipelineView.tsx`（重排布局）。
- **受益面**：所有 SPEC 的拓扑页与运行时间轴（spec-review 节点恢复、状态转移数据
  恢复）；归档 SPEC 走既有骨架降级，不受影响。
- **风险**：`run_spec_part` 为全仓归属单源，剥除段严格限定 spec-review 前缀形态，
  不触碰既有时间戳剥离边界（code-review item 6c089e65a080 保护）。
- **非目标**：不改 spec-review run_id 生成格式（uuid 段保留，防同秒重评碰撞）；
  不重构泳道视图；不治理 admin_monitor 信号的业务语义。
