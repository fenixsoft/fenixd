# 设计 — fix-blocked-freeze-classification

## Context

`blocked` 是唯一「等人工」态，承载两种语义：

- **冻结转人工**（frozen=True）：需人在场，admin agent 无杠杆。`admin_monitor._detect_blocked_stuck`（`:387`）对 frozen 直接 `continue`，不唤起 admin。
- **阻塞待 admin**（无 frozen）：admin 有可操作杠杆（改环境 / 起草契约 / 清 git 状态）。

现有 14 处 `status=blocked` 写入点（审计见下）标记不齐：

| 站点 | 语义 | frozen | alert |
|---|---|---|---|
| `budget.py:365` 预算耗尽 | 冻结转人工 | ✅ | ✅ |
| `spec_integrity.py:101` 内容缺失 | 冻结转人工 | ✅ | ✅ |
| `verification.py:3566` env 阻塞≥2 轮（`_escalate_env_blocked`）| 冻结转人工 | ✅（阈值）| ✅（阈值）|
| `state_machine.py:849` 重启重验超限 | 冻结转人工 | ✅ | **❌ 静默** |
| `spec_review.py:80/186/397` 评审否决/耗尽 | **冻结转人工** | **❌** | **❌** |
| `family.py:497` 升级闸门 | 阻塞待 admin | — | ✅ |
| `verification.py:369/2385/2432/2516/3253/3290/4036` | 阻塞待 admin | — | ✅ |
| `dispatch.py:898/1954/2129` 交付物守卫终审 | 阻塞待 admin | — | —（打回通道）|
| `dispatch.py:1069/2529/2943` merge-back 熔断 | 阻塞待 admin | — | —（依赖兜底）|

（`spec_gen.py:205` 是 artifact 状态，非 spec status，排除。）

根因：分类是每个站点手写 `update_spec({...})` 时各自记得（或忘了）打 frozen / 发 alert，**无机械化约束**。

## Goals / Non-Goals

**Goals:**
- 建立「blocked 二分类」的显式契约与机械化写入 helper。
- 评审路径（3 处）归入冻结转人工并补告警。
- 补齐 `state_machine.py:849` 的静默冻结（补告警）。
- 文档化二分类与消费者。

**Non-Goals:**
- 不新增第三个 spec 状态（保留 blocked，复用 frozen 标记——已有多处消费者）。
- 不改动语义上本属「阻塞待 admin」的站点（merge-back / env / 契约 / 交付物守卫）。
- 不改 dashboard 渲染与状态机合法迁移表。

## Decisions

### D1 分类判据：单一问题「admin agent 对这类停摆有可操作杠杆吗？」

- 无（需人在场/决策：改方案、撤案、改配置、判是否值得再跑）→ **冻结转人工**：`frozen=True` + 人工升级告警。
- 有（可自动修复：改环境、起草契约、清 git 状态）→ **阻塞待 admin**：不写 frozen，admin 巡检介入。

判据不依赖文案，只看杠杆归属。本次按此判据把 `spec_review` 归冻结（admin 无法改方案），既有 env/merge/契约类维持阻塞（admin 有杠杆）。

### D2 机械化：统一 helper 成对写「frozen + alert」

新增单一入口（StateMachine 侧，如 `freeze_for_human(spec_name, *, signal_type, severity, description, evidence, recommended_action, error)`），一次调用完成：

1. `status=blocked` + `frozen=True` + 规范 error 前缀；
2. `_send_human_escalation_alert(...)`。

**为何放 StateMachine 侧并成对**：frozen 与 alert 若分两处，历史已证会漏（`:849` 有 frozen 无 alert）。成对封装让「冻结必然告警」，从结构上消除静默冻结。既有 `budget.py` / `spec_integrity.py` 改写为调用该 helper（行为不变，仅去手写）；`_escalate_env_blocked` 已自身成对（阈值门内同时 frozen+alert），可保留或收敛到 helper（同语义）。

**关于 alert 发送者的可达性**：`_send_human_escalation_alert` 现挂在 PM engine 侧；helper 需能触达。若置于 StateMachine 会跨越现有依赖边界——**实现时以最小依赖倒置解决**（helper 接收一个 alert 回调/发送器，或置于 PM engine 侧由 StateMachine 方法调用），设计不预设具体接线，要求「成对、单一入口」这一不变式即可。

### D3 评审路径的 alert 内容

`spec-review-rejected`：severity major，描述「方案被评审否决，需人工修订方案或撤销」，evidence 附 blocking findings 摘要与评审 run id。
`spec-review-incomplete`（尝试耗尽）：severity major，描述「评审器连续失败（模型链/配置问题），需人工排查」，evidence 附失败原因。

### D4 静默冻结补齐

`state_machine.py:849` 重启重验超限冻结是**恢复路径内部**发生的。此处若直接发告警须注意：恢复遍历可能对多个 spec 触发，告警应逐 spec 触发、不聚合丢失。该点语义确属「人该等」（反复重启仍无法收敛，需人判根因）→ 补 `_send_human_escalation_alert`（signal_type 建议 `verify_redo_exhausted`，severity major）。

### D5 文档

`docs/help/03-lifecycle.md`「冻结与解冻」邻域新增**「blocked 的两种语义：冻结 vs 阻塞」**小节：定义二分类、判据（admin 杠杆）、各类消费者（admin 豁免 / dashboard 标签 / 人工告警），并列明本轮归类的站点清单。**若该章节已有合适落点则就地扩写，否则在 03-lifecycle.md 内新建小节**（不新建独立文档文件——blocked 语义属生命周期核心内容）。

## Risks / Trade-offs

- **[把某类误归冻结 → admin 不再介入，可能漏掉本可自动修复的]** → 本次仅把「评审否决/耗尽」归冻结；这两类 admin 从无实际修复动作（本次 17min run 结论即「无需介入」）。其余保持阻塞，改动保守。
- **[helper 跨依赖边界]** → 以回调/参数注入解耦，不硬引 PM engine。
- **[恢复路径多发告警]** → 逐 spec 触发，不聚合；与既有 `_send_human_escalation_alert` 幂等/节流行为一致。
- **[误改既有行为]** → budget/spec_integrity 改写为调用 helper 时须保持 error 文案与 severity 不变（仅换写法）。

## Migration Plan

无数据迁移。存量 blocked 条目：分类由 frozen 字段决定（已存在），本变更不回溯改写历史条目；仅新发生的 blocked 按新契约写入。

## Open Questions

- helper 的最终落点（StateMachine vs PM engine）与告警回调接线方式，留实现阶段按最小依赖倒置决定（不改变「成对、单一入口」不变式）。
