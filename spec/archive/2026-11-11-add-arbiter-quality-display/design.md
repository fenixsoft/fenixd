# Design: add-arbiter-quality-display

## Context

add-arbiter-lane（fbeb3f104，2026-10-31）把「框架外验尸者」制度化为全局决策者车道：run_id 形如 `arbiter-<spec>-<ts>`，处置台账落 `.fenix/arbiter_ledger.jsonl`（五段结构，kind ∈ {disposition, escalation, spec-proposed}，disposition/escalation 条目带 run_id）。界面侧现状（2026-11-01 实测取证）：

- 指挥中心 `aggregate_org`：arbiter 是花名册外观测 lane，单独出卡在「其他」分区（实测 4 runs），与质量线 judge 卡并存；既有归并单点 `LANE_ALIASES`（dispute-judge→judge、repair→code-fix）已服务同族需求，组织网格与 spec 视图轮次（`aggregate_spec_runs`）两处消费
- SPEC 时间轴：后端 `get_spec_timeline` 经 `get_runs` 已含 arbiter run 节点（实测 evo-refine-midflight-outlier-dims 时间轴 2 条 arbiter 节点）；前端 `runVisual.ts` 的 `AGENT_LABEL`/`RUN_ID_PREFIX_LABEL` 缺 arbiter 条目 → 渲染「未知 Agent」；台账零界面消费

设计宪法：`DESIGN.md`（界面设计约束以 DESIGN.md 为准——本 SPEC 为既有界面小改，无新页面/布局重构，不涉及偏离条款）。

## Goals

1. 指挥中心把 arbiter 归并进 judge 卡，统一显示「质量裁决」
2. SPEC 时间轴 arbiter 节点可见（正确标签）且处理记录可见（处置结论 + 根因摘要）

## Decisions

- **D1 归并走既有单点 `LANE_ALIASES`（后端一行）**：`core/dashboard/data/command_center.py` 归并表加 `"arbiter": "judge"`。组织网格与 spec 视图轮次自动同口径（两处既有消费点）；时间线/拓扑屏保持原生 agent_type 的既有定稿口径不动（归并表注释已明示消费面边界，不扩散）。前端零改动即可显示「质量裁决」（judge 的 `LANE_LABELS` 已是「质量裁决」，OrgGrid 图标映射消费 judge lane 不变）。
- **D2 前端标签补条目于单源 `runVisual.ts`**：`AGENT_LABEL` 加 `arbiter: '质量裁决 Agent'`；`RUN_ID_PREFIX_LABEL` 加 `['arbiter-', '质量裁决 Agent']` 前缀兜底（防 agent_type 泛型化退化——spec-review 前缀漂移事故先例）。两表同改，标签不落第二份。
- **D3 台账联查在后端（timeline.py），前端只渲染**：`get_spec_timeline` 对 agent_type=arbiter 的 run 节点联查 `.fenix/arbiter_ledger.jsonl`（按 run_id 全等匹配，取 disposition/escalation 条目；读侧复用 `core.pm_engine.arbiter.load_arbiter_ledger` 单源防双实现漂移，每请求整台账读入一次、循环内内存匹配），节点附 `arbiter: {kind, root_cause, action_or_upgrade, signal_type}`（root_cause/action_or_upgrade 截断 200 字符下发，防巨型行——巨型行破锚定窗前科）。前端 SpecTimeline run 节点卡片加条件渲染块。台账读取 fail-open（文件缺失/行损坏/未命中 → 静默省略），对齐 `_ocr_lane_summary` 的 lane_summary 既有模式；spec-proposed 条目（run_id 为空）天然不命中 run_id 全等匹配。
- **D4 快速车道（fast-track）**：单模块（dashboard 前后端）小改、无迁移、场景 ≤6，单个 Agent 一次完成实现与验证（用户 2026-11-01 确认）。
- **D5 daemon 重启信号随 SPEC 交付**：聚合层与时间轴是 daemon 内存代码，`restart_request` 落位仓库根（JSON：reason/origin/date），实际重启由 supervisor 消费信号完成（dashboard 类 SPEC 既有纪律）。

## Risks

- **归并吞掉 arbiter 独立观测口径**：归并后指挥中心不再有 arbiter 独立计数。判定为可接受——arbiter 本就是「质量裁决」编制的执行面（dispute-judge→judge 同理），细分口径仍可从 run 产物与台账取；时间轴保留原生 agent_type 兜底可区分。
- **台账联查成本**：台账为 jsonl 追加文件（当前 7 条、每条 ≤ 数 KB），时间轴单次请求逐 run 联查为 O(runs × ledger)，arbiter run 密度极低（单飞串行），无性能风险；仍按行流式解析并容错损坏行。
- **同 run_id 多台账条目**：理论上一次 run 至多产一条 disposition 或 escalation（run 生命周期单结论）；防御取匹配条目中 created 最新一条，不因重放/修补条目翻倍渲染。

## 非目标

- 拓扑屏/执行台账页的 arbiter 展示（各有独立消费面，不在本需求）
- dispute-judge 标签调整（既有「争议裁决 Agent」口径维持）
- 台账的独立浏览界面（add-arbiter-lane 遗留面，另行立项）
