# Design: unfreeze-retry-counter-reset

## Context

unfreeze_spec（core/state_machine.py:2543-2790）与 _RETRY_COUNTER_RESETS（core/dashboard/data/admin_actions.py:1745-1781）是两处既有清零集，2026-11-10-fix-unfreeze-judge-counter-reset 已为 judge 补过两键（admin_actions.py:935/:1025 有同键复位先例）；冻结文案构造在 core/pm_engine/dispatch/queue.py:2600/3150 与 fast_track.py:1291/2385，硬编码 max_r/max_r；approve_push 在 core/pm_engine/engine.py:3387。

## Goals / Non-Goals

- Goals：解冻=完整新预算（含重试计数）；冻结陈述与真实计数一致；人工重推记账显式、达上限信号去重。
- Non-Goals：不改变「先递增后比较 + >=」的冻结判定语义（现行恰好允许 3 次，语义正确）；不改变自动 push 重试上限与退避（在途 fix-push-credential-env-and-retry-rearm 范围）；不禁止人工重推本身。

## Design

1. **清零集补键**：unfreeze_spec updates 增补 _retry_count 置 0；_RETRY_COUNTER_RESETS 增补 _retry_count: 0——与 judge 两键先例同构，改动为各加一行。
2. **文案数据源**：冻结文案构造处把 used 从硬编码 max_r 改为读取真实计数（该值在冻结路径已在手）；越限形态（used>max）如实显示。
3. **人工重推**：approve_push 放行前不设上限门（保持人工自由度），但计入计数时记录 source=manual；达上限后同一 spec 的重复 push_failed 信号在告警面去重（按 spec+指纹窗口去重），防 daemon_errors 升级链重复烧配额。
4. **测试**：单测模拟「3/3 冻结→解冻→首轮失败」断言计数 1/3 不冻结；复位键集合断言；文案计数一致性断言；人工重推去重断言。

## Risks / Trade-offs

- 解冻清零重试计数会放宽收敛速度（解冻后又给 3 轮）——这正是解冻语义本意（与 judge 先例一致）；反复解冻-失败循环由人工裁决面兜底。
- 文案如实显示 4/3 形态可能让人工困惑——保留上限值展示并在文案注明「已越限」，语义更诚实。

## Migration

无数据迁移；清零集补键即时生效于下一次解冻/复位。