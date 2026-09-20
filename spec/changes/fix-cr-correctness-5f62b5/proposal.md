## Why

代码审查发现问题修复 SPEC（由 code-review 台账选中条目机械生成）。

## What Changes

- 修复以下审查发现（SPEC `fix-cr-correctness-5f62b5`）：

  - [major] 'project-profile' is also a project-only（core/dashboard/static/src/pages/settings/index.tsx:100）
  - [major] `request()` unconditionally calls `res.j（core/dashboard/static/src/services/dashboard.ts:61）
  - [major] `tmp` is only bound inside the `try` aft（core/deliverables.py:701）
  - [major] `_known_specs` is a read-modify-write sn（core/event_bus.py:750）
  - [major] Ordering hazard: the *side-effect* budge（core/pm_engine/dispatch/rollback.py:127）
  - [major] Non-atomic persistence + silent-loss loa（core/pm_engine/recovery.py:106）
  - [major] 路径越界校验只看字符串前缀，`..` 未归一化，且未约束到**本 spec** （core/pm_engine/spec_review.py:638）
  - [major] _spec_from_run_id 对含 "-a" 子串的 spec 名解析错误（fenixd.py:2218）
  - [minor] `SPEC_NAMES` and the `BASELINE_STATE` co（bin/fixture_scheduling_showcase.py:44）
  - [minor] Inconsistent failure handling: only the （bin/fixture_scheduling_showcase.py:196）

## Capabilities

### New Capabilities

- 修复 code-review 台账中选中的代码质量问题。

## Impact

- 修改 `## Deliverables` 声明段所列文件。
