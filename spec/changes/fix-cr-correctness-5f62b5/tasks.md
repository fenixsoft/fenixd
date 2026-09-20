# Tasks: fix-cr-correctness-5f62b5

## Deliverables

```yaml
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/deliverables.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/pm_engine/dispatch/rollback.py
  kind: modify
- path: core/pm_engine/recovery.py
  kind: modify
- path: core/pm_engine/spec_review.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: bin/fixture_scheduling_showcase.py
  kind: modify
- path: bin/fixture_scheduling_showcase.py
  kind: modify
```

## 1. 修复审查问题

- [ ] 1.1 'project-profile' is also a project-only — core/dashboard/static/src/pages/settings/index.tsx:100
- [ ] 2.2 `request()` unconditionally calls `res.j — core/dashboard/static/src/services/dashboard.ts:61
- [ ] 3.3 `tmp` is only bound inside the `try` aft — core/deliverables.py:701
- [ ] 4.4 `_known_specs` is a read-modify-write sn — core/event_bus.py:750
- [ ] 5.5 Ordering hazard: the *side-effect* budge — core/pm_engine/dispatch/rollback.py:127
- [ ] 6.6 Non-atomic persistence + silent-loss loa — core/pm_engine/recovery.py:106
- [ ] 7.7 路径越界校验只看字符串前缀，`..` 未归一化，且未约束到**本 spec**  — core/pm_engine/spec_review.py:638
- [ ] 8.8 _spec_from_run_id 对含 "-a" 子串的 spec 名解析错误 — fenixd.py:2218
- [ ] 9.9 `SPEC_NAMES` and the `BASELINE_STATE` co — bin/fixture_scheduling_showcase.py:44
- [ ] 10.10 Inconsistent failure handling: only the  — bin/fixture_scheduling_showcase.py:196
