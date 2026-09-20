## Why

代码审查发现问题修复 SPEC（由 code-review 台账选中条目机械生成）。

## What Changes

- 修复以下审查发现（SPEC `fix-cr-correctness`）：

  - [critical] 全仓核销的空集保护取了 agent 不产出的 `observed` 字段（core/agent_runner/maintenance_runs.py:879）
  - [critical] SSE cleanup 未重置 `patchTimerRef` 致增量刷新停摆（core/dashboard/static/src/pages/projects/list.tsx:593）
  - [critical] 切换项目未重置 `activeAgent` 致提示词写错文件（core/dashboard/static/src/pages/settings/components/PromptsPanel.tsx:50）
  - [critical] `_queue_lock` 非可重入导致审查中查询自死锁（core/pm_engine/dispatch/queue.py:176）
  - [critical] 边界类失败回流 `consume_review_result` 致无限递归（core/pm_engine/spec_review.py:814）

## Capabilities

### New Capabilities

- 修复 code-review 台账中选中的代码质量问题。

## Impact

- 修改 `## Deliverables` 声明段所列文件。
