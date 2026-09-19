# fix-blocked-freeze-classification — blocked 的「冻结（人该等）」与「阻塞（admin 可介入）」分类机械化

## Why

`blocked` 状态承载了两种语义完全不同的停摆，框架用结构化 `frozen` 字段区分：**冻结**（frozen=True，等人在场，admin agent 无杠杆——如人工暂停、预算耗尽、内容缺失）与**阻塞**（frozen 缺席，admin 有可操作杠杆——如环境阻塞、契约缺失、merge-back 冲突）。`admin_monitor._detect_blocked_stuck`（`admin_monitor.py:387`）据此豁免冻结类：对 frozen spec 不唤起 Administrator 巡检。dashboard 亦按此分成「冻结」「阻塞」两个标签。

但**分类没有被机械化**——每个 blocked 写入点各自手写标记，导致两类系统性缺陷：

1. **人该等的被丢给 admin（纯浪费）**。`spec_review.py:80/186/397`（评审否决 / 评审尝试耗尽）是全库唯一同时**不打 frozen、也不发人工告警**的 blocked 写入点。实测事故（2026-09-14 `evo-planner-port-alignment`）：spec-review-rejected 打成 blocked → 因无 frozen 被判「阻塞」→ 超时唤起 **17 分钟 admin run** → admin 结论「无需人工介入」把原封不动的 spec 弹回 reviewing → 下一轮评审**再次否决同一份 spec**。admin 对「方案被否」毫无杠杆，整轮纯烧 token。
2. **静默冻结的风险**。`state_machine.py:849`（重启重验超限）打了 frozen 却不发任何人工告警；`spec_review` 三处一旦补 frozen 而没有配套告警，将因 admin 豁免而**彻底静默**（现状它还能被人看到，全靠误走 admin 这条路）。即 frozen 与「人工告警」在代码里从未绑定，二者必须成对。

## What Changes

- **定义不变的 classify 契约**：每个写 `status=blocked` 的站点 MUST 显式归入两类之一——「冻结转人工」（frozen=True **且** 发人工升级告警）或「阻塞待 admin」（不写 frozen，由 admin 巡检介入）。禁止两者皆无的裸 blocked。
- **评审路径归入冻结转人工**：`spec_review.py` 三处（`rejected`、`incomplete` 尝试耗尽 ×2）改走 `freeze_spec()` 语义 + `_send_human_escalation_alert`。
- **补齐既有静默冻结**：`state_machine.py:849` 重启重验超限补人工升级告警。
- **机械化防漂移**：以一处 helper（如 `freeze_for_human(spec, signal_type, reason, ...)`）收敛「frozen + alert」成对写入，替换各站点手写的 `update_spec({status:blocked, frozen:True, error:...})`；评审路径同类。
- **文档**：在生命周期文档新增一节，讲清 blocked 的两种语义与各自的消费者（admin 豁免 / dashboard 标签 / 人工告警），使后续新增 blocked 写入点有据可依。

## Capabilities

### New Capabilities
- `blocked-disposition-classification`: blocked 停摆的分类契约——「冻结转人工」与「阻塞待 admin」二分的判据、机械化写入 helper、以及每一类的强制副作用（冻结 ⇒ 必须发人工告警；阻塞 ⇒ 由 admin 巡检）。

### Modified Capabilities
<!-- 无既有 capability 的 requirement 变更：spec-review 的 blocked 前置条件、重启重验超限的副作用属实现细节；状态机合法迁移表不变（仍为 blocked）。 -->

## Impact

- **代码**：
  - `core/pm_engine/spec_review.py`（3 处 blocked → 冻结 + 告警）
  - `core/state_machine.py`（重启重验超限补告警；或新增冻结 helper）
  - `core/pm_engine/budget.py` / `core/pm_engine/spec_integrity.py` / `core/pm_engine/verification.py`（改走统一 helper，行为不变）
- **测试**：`tests/test_spec_review_gate.py` / `tests/test_state_machine.py`（新增分类契约断言）。
- **文档**：`docs/help/03-lifecycle.md`（blocked 语义二分 + 消费者）。
- **行为**：评审否决 / 审批耗尽的 spec 从「触发 admin 巡检」变为「冻结并直接告警人」；重启重验超限增加告警；其余 blocked 站点行为不变。
- **不影响**：状态机合法迁移表（blocked 仍是唯一「等人工」态）、dashboard 现有双标签渲染、admin 对确有杠杆的阻塞类（env/契约/merge）的介入。
