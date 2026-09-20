# Tasks: fix-cr-correctness

## Deliverables

```yaml
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/PromptsPanel.tsx
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/spec_review.py
  kind: modify
```

## 1. 修复审查问题

- [ ] 1.1 全仓核销的空集保护取了 agent 不产出的 `observed` 字段 — core/agent_runner/maintenance_runs.py:879
- [ ] 2.2 SSE cleanup 未重置 `patchTimerRef` 致增量刷新停摆 — core/dashboard/static/src/pages/projects/list.tsx:593
- [ ] 3.3 切换项目未重置 `activeAgent` 致提示词写错文件 — core/dashboard/static/src/pages/settings/components/PromptsPanel.tsx:50
- [ ] 4.4 `_queue_lock` 非可重入导致审查中查询自死锁 — core/pm_engine/dispatch/queue.py:176
- [ ] 5.5 边界类失败回流 `consume_review_result` 致无限递归 — core/pm_engine/spec_review.py:814
