## Context

2026-09-03 的人工全天复盘流程（用户发起 → 会话内取证 → 会话内汇总）验证了回顾的价值与所需数据面（STATE 终态 / runs 计数 / 告警记录 / 日志 ERROR 聚合）。框架已有可复用基础：Administrator Agent 通道（`run_administrator`，signal 驱动 + DISPOSITION 落痕）、admin_monitor 巡检循环（interval 分钟级）、配置热更新（30s mtime）、v3 设置页配置模式。todo.md 为新产物，项目根当前不存在该文件。

## Goals / Non-Goals

**Goals**

- 每晚一次自动化回顾，取证零人工；产物沉淀到项目根 todo.md
- 条目质量对齐「新 agent 可直接起草 SPEC 提案」标准
- 三配置键 + v3 设置页，热更新生效
- 防重复 / 补跑 / 首次创建 / 追加不覆盖

**Non-Goals**

- 不自动创建 SPEC（用户判定权保留，场景硬性锁定）
- 不做 todo 条目的自动闭环追踪（仅自省时由 Agent 在 prompt 上下文中人工标注关系）
- 不引入独立守护进程/外部 cron——调度挂在 admin_monitor 既有巡检循环

## Decisions

**D1 调度判定挂在 admin_monitor 巡检循环**：每轮巡检检查「enabled && 本地时间 ≥ run_at && last_run_date < 今天」→ 触发。天然获得补跑（启动后首轮巡检即补）与防重复（状态文件）；不新增定时器/线程。巡检间隔（分钟级）决定实际触发精度，SPEC 场景只约束「run_at 后首个巡检周期」语义。

**D2 自省走独立 run 类型 `self-review`**：复用 `_run_claude` 通道但独立 run_id 前缀（`review-<date>`），不占用 spec 维度预算与实现预算；token 记入 cost-observability 的 administrator 名下（或独立 self-review 类目，实现时二选一并保持对账口径一致）。prompt 由框架聚合当日数据摘要（与人工复盘同源：STATE 终态、runs 统计、alerts、ERROR 聚合）+ 可选 todo.md 全文，模板落 `agents/` 文件化体系（add-agent-prompt-files 的既有模式，缺失 fail-fast）。

**D3 状态文件 `.fenix/self_review_state.json`**（记 last_run_date）：轻量 JSON，与 admin_alerts 同目录同锁风格；不进 STATE.md（STATE 是 spec 状态表，混入调度元数据破坏语义）。

**D4 todo.md 写入后立即 commit + push**：worktree 从 main 分出，未提交文件对后续 agent 不可见——「新 agent 据此提出 spec」要求条目入库。提交仅含 todo.md，push 失败降级 WARNING（与归档自动提交同策略，run-lifecycle-hardening 的 1.x 任务先行落地则语义一致）。

**D5 自省失败静默降级为告警**：run 失败/超时（走 run_timeout_seconds 全局默认，不设 override）→ 记 admin WARNING 告警（含失败原因），不重试当日（防风暴），次日自然重试。

## Risks / Trade-offs

- 巡检间隔粒度使实际触发晚于 run_at（最多一个间隔）→ 可接受，语义锁定为「run_at 后首个巡检周期」
- 每日一条 todo.md commit 的噪音 → 单文件小 diff，价值大于噪音；与归档提交同机制不叠加
- Agent 回顾质量依赖 prompt 数据聚合的完整性 → 数据源清单在 spec 场景锁定（STATE/runs/alerts/ERROR 四源）

## Migration Plan

纯增量。enabled 缺省 false，零行为变化；用户在设置页开启后次日生效（或当日 run_at 前手动触发补跑路径——不提供手动触发按钮，Non-Goal）。

## Open Questions

- 无。
