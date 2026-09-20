# Spec Delta: correctness

## ADDED Requirements

### Requirement: 修复选中的代码审查问题

系统 SHALL 修复以下 code-review 台账选中的问题：

- `core/dashboard/static/src/pages/settings/index.tsx:100` — 'project-profile' is also a project-only
- `core/dashboard/static/src/services/dashboard.ts:61` — `request()` unconditionally calls `res.j
- `core/deliverables.py:701` — `tmp` is only bound inside the `try` aft
- `core/event_bus.py:750` — `_known_specs` is a read-modify-write sn
- `core/pm_engine/dispatch/rollback.py:127` — Ordering hazard: the *side-effect* budge
- `core/pm_engine/recovery.py:106` — Non-atomic persistence + silent-loss loa
- `core/pm_engine/spec_review.py:638` — 路径越界校验只看字符串前缀，`..` 未归一化，且未约束到**本 spec** 
- `fenixd.py:2218` — _spec_from_run_id 对含 "-a" 子串的 spec 名解析错误
- `bin/fixture_scheduling_showcase.py:44` — `SPEC_NAMES` and the `BASELINE_STATE` co
- `bin/fixture_scheduling_showcase.py:196` — Inconsistent failure handling: only the 

#### Scenario: 修复完成

- **WHEN** 修复提交
- **THEN** 对应问题不再出现在 code-review open 列表
