# ADR-041：验证场景集跨轮冻结——修复轮只增不减，确定性校验器补齐

date: 2026-09-06
status: accepted

## Context

planner 每轮独立重读 SPEC 文档生成场景、无跨轮记忆，实证修复轮的验收面反而扩大（11 → 17 场景）：修复成本随轮数不收敛，回归语义被稀释。

## Decision

- 场景集持久化在 `.fenix/verify-progress/<spec>/scenarios.json`；「修复轮」判定复用既有信号（`_verify_fail_rounds > 0` 或 tasks.md 含「## 验证修复」段），不引入新状态机状态。
- 修复轮 planner prompt 注入基准集：必须覆盖全部既有场景；仅当修复段声明新增交付时可为该范围追加场景；移除既有场景必须给出理由。
- 场景写回只发生在确定性校验器（纯 Python，读 planner 输出 + scenarios.json + 修复段文本）通过之后：缺既有场景且无理由 → 直接以持久化集补齐（等效忽略 planner 的删减）并在报告标注。校验器独立于 planner，不可被输出文本绕过。
- 既有场景每轮全量重跑（回归语义的正确代价），不缓存场景执行结果；多 spec 并行验证各有独立 verify-progress 目录，无共享状态。

## Consequences

- 验收面跨轮单调稳定，修复轮成本收敛到 O(增量交付) + 全量重跑的固定执行成本。
- planner 对「新增范围」的边界判断可能偶发超范围追加 → 报告列明新增场景所属范围，人工可纠偏，不做硬拦截。
