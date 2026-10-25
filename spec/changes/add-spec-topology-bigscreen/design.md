# Design: add-spec-topology-bigscreen

## Context

管理层推动 AI-Native 组织，需要以 IOC 大屏形态展示「各 Agent 像人类 SDLC 角色一样协作完成 SPEC」。现有 `SpecTimeline.tsx` 为线性审计时间轴（state/admin/verify/run 四类节点），无拓扑形态。完整需求与视觉裁决见 `docs/superpowers/specs/2026-10-25-agent-topology-bigscreen-design.md`（brainstorming 定稿，含两轮 mockup 用户选型：A 管线 DAG + D 泳道时序、切换式、脱壳全屏、归档降级为选项 a）。

## Goals / Non-Goals

- Goals：单 SPEC 协作拓扑大屏（双视图切换）、后端只读派生端点、下钻复用运行记录、SSE 实时、零新依赖
- Non-Goals：多 SPEC 项目级总览、移动端专项适配、图编辑能力、替换线性时间轴、归档快照持久化（已评估明确不做）

## Decisions

1. **渲染手写 SVG + React，零图表库**：两视图均为确定性布局（A 列坐标固定、D 泳道坐标=时间线性映射），无需通用图布局引擎；SVG 便于发光滤镜/脉冲动画的 IOC 风格控制。若实现中列内布局复杂度超预期，允许引入 dagre 类纯布局算法（无渲染层）。
2. **拓扑派生放后端**（`core/dashboard/data/topology.py`）：timeline/runs 数据为唯一输入，产出 nodes/edges/kpis；前端零推导。角色前缀映射以 `run_files` 的映射为权威源（跨语言不强行单源，前端常量仅服务渲染）。
3. **KPI 口径（裁决定稿）**：dispatched=逻辑 run（attempt 归并）；retried=attempt>1 或 superseded/stale；completed=成功终态；total_cost_usd 全不可计价为 null。
4. **重试边仅连 attempt 链**（`strip_run_id_suffixes` 语义），独立重派为 handoff——防止假叙述。
5. **多轮验证逐轮节点**：扫日志「开始验证」行，历史轮仅时长、末轮带 report.json 统计。
6. **交付终点自适应**：按 pushed 转移 context 判人工批准/自动推送，不虚构人工动作。
7. **归档 SPEC 降级（用户选型 a）**：骨架数据 + `archived: true` + 前端显式提示；归档链路零改动，不做快照。
8. **零改动红线豁免窄口**：`SpecTimeline.tsx` 状态着色/角色映射等价纯迁移至 `src/utils/runVisual.ts`（渲染严格等价，纯函数单测背书，仓库有等价抽取先例）；detail 页面与归档链路零改动。
9. **脱壳方式留给实现**：`embedMount.ts` 运行时布局开关为现成先例；路由平级新增（umi 精确段匹配与 `/projects/:name/:spec` 不冲突）。
10. **实时刷新**：复用既有 SSE 通道（run_meta/refresh + throttled 拉取先例），全量重拉不做增量 patch（节点量级 ~几十）；SSE 不可用 30s 轮询兜底。

## Risks / Trade-offs

- **归档 SPEC 图为骨架**（用户已接受）：汇报已完成 SPEC 前需确认未归档；后续如需完整历史可另行立项「归档拓扑快照」。
- **切换式单视图**：A/D 不能同屏（用户选型接受），联动高亮弥补跨视图对照。
- **节点拥挤**：列内/泳道内节点极多时可滚动或压缩——具体策略留给实现，验收标准是「不重叠遮挡」。
- **数据源双读**（timeline + 日志扫描验证轮次）：验证轮次历史统计不可得（report.json 每轮覆盖），设计已明确仅末轮带统计。

## Open Questions

（无——全部裁决已在 brainstorming 与建设者复核中定稿）
