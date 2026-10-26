# 设计：SPEC 协作拓扑管线视图时序化改进

## Context

管线视图（PipelineView）与派生层（topology.py）由 add-spec-topology-bigscreen 落地，
实测暴露三个层次的问题：数据 bug（spec-review 归属、超长行破窗）、数据链路缺失
（transitions 派生为空）、视图语义缺失（无时间维度、伪串行边）。本设计按
「先治数据、后改视图」分层推进，每层可独立验收。

实测基准样本：`add-collab-graph-bigscreen`（pushed，2026-10-25）——
spec-review 1 + planner-plan 1 + planner-judge 6 + impl 1 + verify 1，
生成场景 ∥ 开发同刻启动，6 轮判定串行，daemon 日志首行 6.6MB 巨型行。

## Goals / Non-Goals

- Goals：spec-review 节点可见；transitions 完整可派生；管线视图时间对齐、
  并行/先后/持续可读；PM 生命周期链上屏；伪串行边消除。
- Non-Goals：不改 spec-review run_id 生成格式；不重构泳道视图结构；
  不治理 admin_monitor 信号业务语义；不引入图表库（延续 design D1 零依赖）。

## Decisions

### D1 spec-review uuid 段在 run_spec_part 单源剥除（修复点最上游）

`run_spec_part`（run_files.py）在既有「前缀剥离 → -a/-r 段剥离 → 时间戳剥离」
链尾追加一步：**仅当** agent 前缀为 `spec-review-` 时，剥除 spec 名与时间戳之间的
6 位 hex 段（正则 `^(.*)-[0-9a-f]{6}$`，剥后非空才生效）。

- 为什么单源修而不在 topology.py 放宽 family 正则：`get_runs` 的 spec 字段、
  `_family_run_paths` 预过滤、`fam_re.fullmatch(spec_part)` fix 家族判定、
  SpecTimeline 归属全部经 `run_spec_part`——下游各自打补丁会漏；单源一处修，
  全部消费者（含本 SPEC 未覆盖的时间轴）同步治愈。
- 风险控制：限定 `spec-review-` 前缀（uuid 段仅此一写入方，spec_review.py:392）；
  spec 名合法以 6hex 结尾的极边界场景会误剥——与既有「9-10 位数字时间戳误剥」
  同级已记录限制，快照测试钉死既有形态零回归。
- 备选否决：改 spec_review.py 去掉 uuid 段——run_id 唯一性靠它防同秒重评碰撞
  （同名 SPEC 重评），且存量/归档 run_id 永远带着 uuid 段，读侧单源剥除是唯一
  能治愈存量的方案。

### D2 读侧窗口防御：探测跳行 + 读取 seek 越行（log_index.py）

- `_first_ts` 探测：块内前 `LOG_INDEX_BLOCK` 字节无 `\n`（超长行征兆）时，
  从块内第一个 `\n` 之后探测下一行，替代整体放弃；
- 窗口读取：行切分后遇到「行长度 > 单行上限阈值（128KB 量级常量）」的行，
  以 seek 越过该行字节区间继续读后续内容——超长行不进内存，单请求读取字节数
  有界（阈值常量 + 窗口上限双重约束）；
- 截断标记语义不变（.truncated 以最终读取终点判定）。
- 否决「扩大窗口上限」：6.6MB 巨型行会让窗口上限需再涨数倍，内存无界化，
  且巨型行本身无信息价值（写侧已截断，存量巨型行只求跳过）。

### D3 写侧截断：序列化出口整体封顶（logger.py）

`Logger.format`（json.dumps 出口，logger.py:41）序列化后超 `LOG_EVENT_MAX_BYTES`
（256KB 常量）时：context 替换为占位摘要
`{"truncated": true, "orig_bytes": <近似原体积>, "context_keys": [顶层键名]}`,
message/level/timestamp/component 原样保留，重新序列化。正常事件路径零改动
（不超限不触碰），逐字节兼容由快照测试钉死。

### D4 管线视图时间对齐布局（PipelineView 重排，复用泳道思路）

- 时间域：取全部可定位时刻节点（parseTsMs）的 min/max 为 t0/t1，无时刻节点
  （user/pm 空值）锚定在 t0 行；跨度 < 60s 时按 60s 兜底（防零跨度除零）；
- 纵坐标：`y = HEADER_H + PAD + (t - t0) / span * contentH`，contentH 随跨度与
  节点数自适应（`max(节点数 × (NODE_H + NODE_GAP), 跨度线性最小高度)`），
  保证时间对齐优先、拥挤时按行错开不重叠；
- 同列同刻/重叠节点：贪心行分配（泳道 assignRows 同思路，迁移到列内使用），
  行偏移叠加在时间坐标上（不覆盖他列同刻节点的水平对齐线）；
- 左侧新增可折叠时间刻度列（复用协作时序 TICK_STEPS_S 档位与 fmtTick），
  列背景/列头保留；
- 悬浮卡、发光、着色、下钻、跨视图联动 selectedId 契约全部不变。

### D5 PM 生命周期节点链渲染 + dispatch 边归位

- transitions 逐条渲染为小节点（高 ~24px，标签 `→<目标状态>`，副行时刻），
  链置于 PMEngine 主节点正下方，纵坐标按转移时刻走 D4 时间域（链即真实时序）；
- dispatch 边视觉归位：**不改写既有 edges 端点**（泳道视图消费同一份 edges 做
  派发标记 ▾，改端点会破泳道）——派生层为 run 首节点附加可选字段
  `dispatch_anchor`（值为归位转移节点 id `tr:<n>`；run 的 started 落在转移区间
  `[t_i, t_{i+1})`；无法定位时缺省回退 pm 主节点）。管线视图渲染 dispatch 边时
  自 anchor 节点出发，泳道视图不消费该字段、行为零变化；
- 边型沿用 dispatch 虚线，颜色不变。

### D6 伪 handoff 边在派生层消除（topology.py，非前端过滤）

handoff 时序链构建处（`derive_topology` work 链）增加重叠判定：
`prev.start < cur.end 且 cur.start < prev.end`（终点缺失取 start，即同刻启动
也视为重叠）→ 跳过该 handoff 边。串行对（prev 终点 ≤ cur 起点）照画。

- 为什么派生层修：泳道视图消费同一份 edges，派生层消除使两视图一致受益；
  前端过滤会造成视图间边集分裂（违背「前端零拓扑推导」的 D2 既有决策）。

## Risks / Trade-offs

- `[600]` run_spec_part 全仓单源改动 → 快照测试钉死非 spec-review 形态零回归
  （含 9-10 位数字保护、fix 家族、attempt/transient 链形态）。
- `[400]` 时间对齐布局在超长跨度（周级 SPEC）下节点拥挤 → contentH 随跨度
  线性伸缩 + 容器纵向滚动（与横向滚动并存），不做对数轴（可读性反直觉）。
- `[300]` transitions 区间归位依赖转移时刻精度（秒级）→ 区间无法定位时回退
  PMEngine 主节点，不虚接。
- `[200]` 写侧截断改变超大事件信息保真 → 占位摘要保留顶层键名与原体积，
  足够定位「哪类事件被截断」；51054 entry 全文本就不可读，无保真损失。

## Migration Plan

无数据迁移。存量巨型行（已落盘）由读侧 seek 跳过；新事件由写侧封顶。
存量 spec-review run 产物归属由 D1 直接治愈（含归档目录）。

## Open Questions

无——四项决策已与用户确认（PM 生命周期节点链 / 纵轴真实时间 / 读写双治 / full+立即）。
