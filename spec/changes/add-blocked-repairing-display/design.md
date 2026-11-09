## Context

`blocked` 状态外部显示目前是单标签：`STATUS_META`（`core/dashboard/static/src/services/dashboard.ts`）对 `blocked` 渲染「阻塞」critical 红，列表页（`list.tsx` 状态列）与详情页（`detail.tsx` 头部 + spec 切换下拉）均经 `statusMeta(status)` 消费。后端 summary builder（`core/dashboard/data/summary.py`）已有后端单点判定先例：`frozen` 字段（结构化优先、文本前缀回退），前端只消费不重复判定。

知识库锚点：
- `spec/knowledge/domains/admin-ops/blocked-disposition-classification.md`：blocked 已有「冻结转人工（frozen）/阻塞待 admin」二分类契约，消费者含「dashboard 双标签」；
- `spec/knowledge/domains/admin-ops/escalation-chain.md` / `chain-observability.md`：链在办件、pending 排队件有既有数据源（`admin_alerts.json`、`.fenix/escalation_chain_state.json`、arbiter ledger），处置链视图已消费「链上在办件（当前 run 标识）」；
- run 在飞判定：run 产物末行终态映射（`core/dashboard/data/runs.py` `_RUN_TERMINAL_STATUS_MAP` + 元数据 memo 缓存）与 `RUN_ID_AGENT_PREFIXES`（`core/agent_runner/run_files.py`，`admin-`/`arbiter-` 前缀单源表）。

用户定调（2026-11-09）：不改状态机；显示层三态——在飞处置 run →「修复中」、仅挂起排队 →「排队中」、等待人工 →「阻塞」。

## Goals / Non-Goals

**Goals:**
- 人工可从 SPEC 列表/详情一眼分辨：哪些阻塞 agent 正在自愈（修复中）、已受理排队（排队中）、真正需要自己介入（阻塞）。
- 判定单点在后端（`blocked_phase` 字段），与 `frozen` 同模式；前端零重复判定。
- 零状态机/调度/筛选/计数影响；不引入平行真相源与新配置键。

**Non-Goals:**
- 不新增状态机状态、不改 STATE.md 任何写入路径。
- 不改运维页处置链视图（`/activities` 三页签）、不改告警面板、不动命令中心页面。
- 不改筛选选项与状态计数口径（`blocked` 仍按真实状态统计）。
- 不处理 frozen 专属视觉强化（冻结态已有 Modal 内解冻入口，保持现状）。

## Decisions

1. **字段形态：summary 新增 `blocked_phase: "repairing" | "queued" | null`**（而非两个布尔）。理由：三态互斥，单枚举字段消除非法组合；读侧容错缺省 `null` = 现状显示，存量零迁移。
2. **判定数据源复用既有单源**：
   - 在飞 run：spec 关联 run 清单按 `admin-`/`arbiter-` 前缀过滤（`RUN_ID_AGENT_PREFIXES` 真源表判定 agent 归属，不手写前缀字面量），非终态判定复用 `_RUN_TERMINAL_STATUS_MAP` 末行口径与 run 元数据 memo 缓存——清单路径增量成本近似零；
   - 链在办/pending：读链状态文件与 `admin_alerts.json` 的既有读路径（处置链视图同源），不新开读法。
3. **人工升级件不计入 `queued`**：升级 kind 告警是「等人」信号（`human-escalation-alerts` 契约），计入排队会掩护真正需介入的件——这是本需求的核心价值，宁缺勿滥。
4. **前端渲染辅助**：`services/dashboard.ts` 新增相位标签辅助（`blockedPhaseMeta(record)` 形态），`statusMeta` 本体与 `STATUS_META` 键域不变；列表/详情/切换下拉三处共用同一辅助，禁复制分支（三态语义单源）。
5. **tone 选型**：修复中 = 进行中蓝（info，与「实现中/验证中」同类语义），排队中 = 等待橙（warning）；阻塞维持 critical 红。色板均为站内既有 token，无新色值。
6. **容错口径**：`blocked_phase` 缺席/非法值 → 按「阻塞」渲染（现状行为）；告警/链文件读取异常 → fail-open 降级，绝不沿 `/api/specs` 链路抛 500（对齐 summary 既有 `_int_or_zero` 式容错纪律）。

## Risks / Trade-offs

- **误报「修复中」**：stale run 产物末行非终态被误判在飞 → 复用 run 元数据既有 stale/新鲜度口径（与 `run_activity` 同源），由实现与测试覆盖该场景。
- **`queued` 与「修复中」的瞬时抖动**：处置 run 起飞瞬间 queued→repairing，刷新间隙标签跳变——可接受（30s 轮询节奏下本就存在），不做粘滞。
- **读放大**：blocked SPEC 才进入告警/链文件判定路径，且命中 summary 既有缓存链；预计清单接口无可测开销，回归以 `tests/test_dashboard_data.py` 既有性能断言为准。
