## Why

代码审查发现问题修复 SPEC（由 code-review 台账选中条目机械生成）。

## What Changes

- 修复以下审查发现（SPEC `fix-cr-correctness-524b59`）：

  - [major] `_git` never inspects `returncode`, and （bin/fixture_scheduling_showcase.py:91）
  - [major] Non-atomic baseline writes. `Path.write_（bin/fixture_scheduling_showcase.py:191）
  - [major] An explicitly configured `admin.shutdown（core/config.py:1068）
  - [major] Keep-alive body-drain gap on early retur（core/dashboard/routes/base.py:448）
  - [major] In-flight dedup matches the project name（core/dashboard/routes/settings_routes.py:375）
  - [major] Truncated/malformed `/proc/net/tcp` line（core/dashboard/server.py:206）
  - [major] SSE 分支是死代码：后端 watcher/sse 只广播 `refresh` （core/dashboard/static/src/pages/projects/components/QualityTab.tsx:143）
  - [major] `item.summary ?? null` 把「summary 字段缺失/为 （core/dashboard/static/src/pages/projects/list.tsx:578）
  - [major] Tri-state read-back uses `=== undefined`（core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx:288）
  - [major] `loadConfig` has no cancellation/ignore （core/dashboard/static/src/pages/settings/index.tsx:91）

## Capabilities

### New Capabilities

- 修复 code-review 台账中选中的代码质量问题。

## Impact

- 修改 `## Deliverables` 声明段所列文件。
