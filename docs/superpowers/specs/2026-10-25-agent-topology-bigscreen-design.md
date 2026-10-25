# SPEC 协作拓扑大屏（Agent Topology Big-Screen）设计文档

日期：2026-10-25
状态：建设者复核完成、争议项已裁决（定稿待最终批准）

## 1. 背景与意图

管理层希望构建 AI-Native 组织：以前靠人工的开发、测试、运维等 SDLC 节点，现在由 AI Agent 替代。当前 dashboard 的 SPEC「运行时间轴」（`SpecTimeline.tsx`，antd 纵向线性时间轴）是一条审计级的流水账，无法呈现「各 Agent 像人类团队一样分工协作」的拓扑关系。

本设计新增一个 **SPEC 协作拓扑大屏**：把完成该 SPEC 的每个 Agent（run 实例）以图状态排布，其中两个特殊节点：

- **用户 / fenix-new** —— 需求提出者（图入口）
- **PMEngine** —— 项目经理 Agent（非 LLM 驱动的调度引擎，派发中枢）

定位是 **IOC（智能运维中心）大屏**：既服务于向管理层汇报「AI-Native 开发流程」，也支持日常观察在飞 SPEC 的实时协作状态。视觉语言对齐 IOC/BI 大屏惯例（深色底、发光高亮、KPI 数值条）。

## 2. 目标 / 非目标 / 反目标

### 目标

1. 单 SPEC 视角的 Agent 协作拓扑，提供两个可切换视图：
   - **管线视图（A · 分层管线 DAG）**：左→右为 SDLC 阶段列，每个 run 是一个节点，同角色多轮在同列重复出现；用户/fenix-new 入口、PMEngine 调度节点、最右「人工批准」交付闸门。回答「AI 是怎么走完人类 SDLC 流程的」。
   - **协作时序视图（D · 角色泳道时序拓扑）**：行是角色泳道，横轴真实时间，run 是色块（宽度=耗时），跨泳道箭头=交接。回答「谁在什么时候干活、谁和谁并行」。
2. **切换式组织**：一屏只渲染一个视图，顶部胶囊切换，每个视图独占最大画布。
3. **脱壳大屏形态**：独立路由、无 dashboard 框架（无侧边栏/亮色壳）、全屏深色；右上角退出按钮；浏览器 F11 即为纯电视墙。
4. 实时性：复用 dashboard SSE 通道，在飞节点发光脉冲、新 run 实时上屏。
5. 下钻：点击任何 Agent 节点 → 复用现有运行记录弹窗（`RunRecordModal`/`ClaudeOutputPane`）；点击 PMEngine 节点 → 展示状态转移记录；点击用户节点 → 展示人工动作记录（创建/批准/人工处置）。
6. 跨视图联动高亮：在一个视图选中节点，切到另一视图时同步定位高亮。

### 非目标（本轮不做）

- 多 SPEC / 项目级总览大屏（可另行立项）
- 移动端专项适配（页面按桌面/大屏优先，小屏可用性不设门槛）
- 图的编辑能力（不做通用图编辑器）
- 用图视图替换现有线性时间轴（现有界面零改动，线性时间轴继续承担审计明细）

### 反目标（出现即算失败）

- 改动现有任何页面的行为或视觉（包括 SPEC 列表、SPEC 详情页）
- 图上堆砌审计明细（门禁拒绝原因全文、总结 markdown 等）导致不可读——明细只进下钻
- 退回力导向自由布局（方案 C 已被否决：位置无语义、两次看同图形态不同）

## 3. 入口与路由

- 入口：SPEC 列表「更多」下拉菜单（桌面表格 `list.tsx` 操作列 + 移动卡片 `SpecCardList` 两处同源 `specMenuItems`）新增一项 **「协作拓扑」**，仅做导航，不弹窗。
- 路由：`/projects/:name/:spec/topology`（与现有 `/projects/:name/:spec` 详情路由平级、不冲突），脱离 ProLayout 布局壳（umi 路由层处理，`layout: false` 或平级挂载，由 plan 细化）。
- 退出按钮返回来源页（`/projects/:name/:spec` 或 `/projects/:name`）。

## 4. 页面结构（两视图共用）

```
┌──────────────────────────────────────────────────────────────┐
│ SPEC 协作拓扑 · <spec-name>          [KPI条]        退出大屏 ✕ │
│                              总耗时 │ 总成本 │ 派发/完成/重试   │
├──────────────────────────────────────────────────────────────┤
│         ( 管线视图 | 协作时序 )   ← 胶囊切换器                  │
│                                                              │
│                    当前视图独占剩余全部画布                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

- **KPI 条**：总耗时（`total_duration`）、总成本（Σ `cost_usd`）、派发/完成/失败重试计数、当前 SPEC 状态。
- **节点悬浮卡**：角色名 · run_id · 状态 · LLM · 耗时 · 成本 · 重试次数；「点击查看运行记录」提示。
- **在飞语义**：`running` 状态节点描边发光 + 脉冲动画；`error`/`gate-blocked` 红、`superseded` 中性、`interrupted`/`cancelled` 橙——色板语义与现有 `SpecTimeline` 圆点着色规则同源（设计上抽公共常量，渲染两处各自消费）。

## 5. 管线视图（A）规格

- **阶段列**（左→右，列头中文，列间虚线分隔）：

| 列 | 归入的节点 |
|---|---|
| 需求 | 用户/fenix-new（入口）、需求评审 Agent（`spec-review-`）、争议裁决 Agent（`dispute-judge-`） |
| 规划 | 规划 Agent（`planner-`）、生成场景 Agent（`planner-plan-`）、判定结果 Agent（`planner-judge-`） |
| 开发 | 开发 Agent（`impl-`，含 fast-track） |
| 审查/修复 | 代码审查 Agent（`impl-ocr-`）、修复 Agent（`repair-`） |
| 测试/验证 | 测试 Agent（`test-`）、验证 Agent（`verify-`）、验证执行（确定性节点，非 agent run） |
| 运维 | 运维 Agent（`admin-`） |
| 交付 | 交付终点（终态 `pushed`）：按实际触发方自适应渲染——确有人工批准（approve_push_request）时渲染「人工批准」闸门节点（标注批准时间）；fast-track 连跳 / 自动推送渲染「自动推送」普通终点。MUST NOT 对未发生人工批准的 SPEC 虚构「人工批准」节点（state 节点结构化 context 可判触发方） |

- 角色判别单源复用现有 `agentLabel` 逻辑（`agent_type` 优先、`run_id` 前缀兜底），映射表抽为共享常量，MUST NOT 在新视图内重复实现第二套前缀匹配。
- 同列节点纵向排列（按时间从上到下）；列内节点数多时列内滚动或压缩节点高度（plan 细化）。
- **边 = 交接**：时间序上「上一节点终结 → 下一节点启动」；并行 run 的边一律从 PMEngine 节点出发（表达「由 PM 派发」）。失败重试边（橙）只连**同 base run_id 的 attempt 链**（`-a<n>`/`-r<n>` 后缀归并，归并用 `strip_run_id_suffixes` 现成先例）；不同 base run_id 的两次独立重派 MUST NOT 连成重试边（按普通交接处理，防止假叙述）。
- `fix-*` 子 SPEC 的 run（时间轴已有 `spec` 字段标记）正常入列，节点带 🔧 角标。
- 验证执行节点（kind=verify）：菱形或方形特殊节点。数据源 timeline 只保留末轮，多轮验证会失真为「只验证了一次」——后端派生时另扫运行日志取全部「开始验证」行，**每轮各渲染一个验证执行节点**：历史轮仅显示时长，末轮（与现存 report.json 配对的那轮）显示 N 场景/通过/失败统计摘要。
- 运维处置/升级告警事件（kind=admin）不在 A 中渲染为节点（避免审计噪音），仅 D 中呈现。

## 6. 协作时序视图（D）规格

- **泳道行**（自上而下）：用户/fenix-new、PMEngine、需求评审、规划、开发、审查/修复、测试/验证、运维。
- 横轴 = 真实时间，起止为该 SPEC 最早/最晚节点时间，刻度自适应（分钟/小时档）。
- run = 泳道内色块（宽度=耗时，颜色=角色/状态语义同上）；同泳道并行 run 上下错行。
- PMEngine 泳道：状态转移为细刻度标记（悬浮显示 from→to）；每次派发为紫色小方块。
- 用户泳道：创建、人工处置、批准等人工动作为标记点。
- 跨泳道箭头 = 交接（同 A 的边语义）；并行 run 的箭头自 PMEngine 派发点出发。
- 在飞 run 色块右端为虚线尾迹 + 发光脉冲。

## 7. 数据与接口

- **后端新增只读端点**：`GET /api/projects/<name>/specs/<spec>/topology`，返回派生后的图数据：

```jsonc
{
  "spec": "fix-provider-transient-backoff",
  "status": "done",
  "kpis": { "total_duration": 4980, "total_cost_usd": 3.42, "dispatched": 14, "completed": 12, "retried": 1 },
  // KPI 口径（裁量定稿）：dispatched = 逻辑 run 数（同一次派发的多个 attempt
  // 归并为 1，避免瞬断重试虚增派发数）；retried = attempt>1 或被弃置
  // （superseded/stale）的 run 数；completed = 有成功终态的 run 数。
  // total_cost_usd：全部 run 不可计价时为 null（与 cost_summary_from_timeline 同语义）。
  "nodes": [ { "id": "run-impl-04", "kind": "run|verify|user|pm|approve", "role": "implementer",
               "stage": "dev", "lane": "dev", "status": "running", "start": "...", "end": "...",
               "duration_seconds": 720, "cost_usd": 0.84, "llm": "...", "retry": 1, "run_id": "...", "fix_spec": null } ],
  "edges": [ { "from": "n1", "to": "n2", "type": "handoff|dispatch|retry|approve" } ]
}
```

- 派生逻辑放后端（Python、可单测）：以现有 timeline 数据源（run/state/verify 事件，与 `SpecDetail.timeline` 同源）为唯一输入，产出 nodes/edges/lanes；前端零拓扑推导。
- SSE：复用现有 spec 维度事件流，拓扑端点数据变更后前端重新拉取（或 SSE 携带 invalidate 信号），不做增量 patch（大屏全量重渲染成本可接受，节点量级 ~几十）。
- **已归档 SPEC：降级可用（用户定稿，选项 a）**。归档链路会把 run 产物物理删除（`archive_spec_runs`），归档 SPEC 的数据源只剩 state/verify/admin 节点——拓扑图塌缩为状态骨架（PMEngine 状态刻度 + 状态转移 + 验证/运维事件），无 Agent 节点、无成本。前端必须对归档 SPEC 显式提示「run 明细已随归档清理」（横幅或空态文案，plan 细化），KPI 中 `total_cost_usd` 为 null。**不触碰归档链路**（快照持久化方案已评估、明确不做）；入口对归档 SPEC 照常提供。

## 8. 技术选型（我的裁量）

- **渲染：手写 SVG + React**，不引入 ECharts/G6/X6 等重型图表库。理由：两个视图布局均为确定性布局（A 列坐标固定、D 泳道坐标=时间线性映射），无需通用图布局引擎；SVG 便于精确控制 IOC 风格（发光滤镜、脉冲动画）；零新依赖符合本项目「薄」的取向。若 plan 阶段发现列内布局复杂度超预期，可复议 dagre 这类纯布局工具（仅算法、无渲染）。
- 后端端点挂在现有 dashboard HTTP 服务（`core/dashboard/routes/`），遵循现有路由注册约定。
- **单源与红线豁免（裁量定稿）**：把 `SpecTimeline.tsx` 内联的状态着色分支抽为共享常量模块（角色中文名/前缀映射、run 状态语义色），`SpecTimeline.tsx` 改为导入消费——属「行为与视觉严格等价的纯迁移」，豁免于第 9 节零改动红线（仓库有等价抽取先例：SpecTimeline 本身即自 detail.tsx 等价迁出），等价性由纯函数测试背书。跨语言无法字面单源：后端 stage/role 归列以 `run_files.RUN_ID_AGENT_PREFIXES`/`infer_run_agent_type` 为权威源；前端常量仅服务前端渲染。

## 9. 约束

- 前端遵循仓库现有 lint 规则（禁止嵌套三元等，见既有 code-review 先例）。
- 现有页面零改动红线：`list.tsx` 仅新增菜单项与导航 handler；detail 页面不触碰。`SpecTimeline.tsx` 仅允许第 8 节定义的等价纯迁移（抽常量、改导入），渲染输出严格等价；除此之外不改动。归档链路（`archive_spec_runs`）零改动。
- 新增配置项为零（无需 Dashboard 设置界面，规避「新增配置必须带 UI」约定）。
- 后端派生逻辑须带 pytest 单测（拓扑派生规则表驱动用例），前端组件遵循现有测试形态。

## 10. 留给 builder 的部分

- 具体组件拆分、SVG 坐标计算、缩放/平移（SPEC 很长时 D 视图允许横向滚动或缩放，交互方式由 plan 定）
- umi 路由脱壳的具体做法（`layout: false` vs 平级路径）
- 列内/泳道内节点拥挤时的具体策略（滚动 / 压缩 / 聚合）
- SSE 失效信号的精确接线方式
- 测试用例清单与 fixture 形态
