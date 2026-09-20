# Spec Delta: correctness

## ADDED Requirements

### Requirement: 修复选中的代码审查问题

系统 SHALL 修复以下 code-review 台账选中的问题：

- `bin/fixture_scheduling_showcase.py:91` — `_git` never inspects `returncode`, and 
- `bin/fixture_scheduling_showcase.py:191` — Non-atomic baseline writes. `Path.write_
- `core/config.py:1068` — An explicitly configured `admin.shutdown
- `core/dashboard/routes/base.py:448` — Keep-alive body-drain gap on early retur
- `core/dashboard/routes/settings_routes.py:375` — In-flight dedup matches the project name
- `core/dashboard/server.py:206` — Truncated/malformed `/proc/net/tcp` line
- `core/dashboard/static/src/pages/projects/components/QualityTab.tsx:143` — SSE 分支是死代码：后端 watcher/sse 只广播 `refresh` 
- `core/dashboard/static/src/pages/projects/list.tsx:578` — `item.summary ?? null` 把「summary 字段缺失/为 
- `core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx:288` — Tri-state read-back uses `=== undefined`
- `core/dashboard/static/src/pages/settings/index.tsx:91` — `loadConfig` has no cancellation/ignore 

#### Scenario: 修复完成

- **WHEN** 修复提交
- **THEN** 对应问题不再出现在 code-review open 列表
