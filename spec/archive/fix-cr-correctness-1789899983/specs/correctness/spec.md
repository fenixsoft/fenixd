# Spec Delta: correctness

## ADDED Requirements

### Requirement: 修复选中的代码审查问题

系统 SHALL 修复以下 code-review 台账选中的问题：

- `core/agent_runner/maintenance_runs.py:879` — 全仓核销的空集保护取了 agent 不产出的 `observed` 字段
- `core/dashboard/static/src/pages/projects/list.tsx:593` — SSE cleanup 未重置 `patchTimerRef` 致增量刷新停摆
- `core/dashboard/static/src/pages/settings/components/PromptsPanel.tsx:50` — 切换项目未重置 `activeAgent` 致提示词写错文件
- `core/pm_engine/dispatch/queue.py:176` — `_queue_lock` 非可重入导致审查中查询自死锁
- `core/pm_engine/spec_review.py:814` — 边界类失败回流 `consume_review_result` 致无限递归

#### Scenario: 修复完成

- **WHEN** 修复提交
- **THEN** 对应问题不再出现在 code-review open 列表
