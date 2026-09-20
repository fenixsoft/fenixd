# Tasks: fix-cr-correctness-524b59

## Deliverables

```yaml
- path: bin/fixture_scheduling_showcase.py
  kind: modify
- path: bin/fixture_scheduling_showcase.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/routes/settings_routes.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/QualityTab.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
```

## 1. 修复审查问题

- [ ] 1.1 `_git` never inspects `returncode`, and  — bin/fixture_scheduling_showcase.py:91
- [ ] 2.2 Non-atomic baseline writes. `Path.write_ — bin/fixture_scheduling_showcase.py:191
- [ ] 3.3 An explicitly configured `admin.shutdown — core/config.py:1068
- [ ] 4.4 Keep-alive body-drain gap on early retur — core/dashboard/routes/base.py:448
- [ ] 5.5 In-flight dedup matches the project name — core/dashboard/routes/settings_routes.py:375
- [ ] 6.6 Truncated/malformed `/proc/net/tcp` line — core/dashboard/server.py:206
- [ ] 7.7 SSE 分支是死代码：后端 watcher/sse 只广播 `refresh`  — core/dashboard/static/src/pages/projects/components/QualityTab.tsx:143
- [ ] 8.8 `item.summary ?? null` 把「summary 字段缺失/为  — core/dashboard/static/src/pages/projects/list.tsx:578
- [ ] 9.9 Tri-state read-back uses `=== undefined` — core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx:288
- [ ] 10.10 `loadConfig` has no cancellation/ignore  — core/dashboard/static/src/pages/settings/index.tsx:91
