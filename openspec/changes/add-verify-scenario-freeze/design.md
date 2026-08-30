# Design: add-verify-scenario-freeze

## Context

验证链：planner-plan（生成场景）→ 场景执行 → planner-judge（裁决）。planner 每轮独立重读 SPEC 文档生成场景，无跨轮记忆。v2-config-page 实证：11 → 17 场景，修复轮的验收面反而扩大。`.fenix/verify-progress/<spec>/` 已有 report.json 等产物目录，scenarios.json 落点自然。

## Goals / Non-Goals

- Goals：场景集跨轮稳定；修复轮只对新增交付扩容；删减留痕；不中断验证（缺场景自动补齐）
- Non-Goals：不改变场景内容质量标准；不缓存场景执行结果（每轮全量重跑既有场景——保证回归语义）；不做场景级去重/合并的智能逻辑

## Decisions

### D1 判定「修复轮」复用既有信号
`_verify_fail_rounds > 0` 或 tasks.md 含「## 验证修复」段即为修复轮（与原地打回机制同源，不引入新状态）。首轮验证（无信号）正常重规划并写 scenarios.json。

### D2 planner prompt 注入基准集
修复轮时 planner-judge prompt 附加持久化集：明确「必须覆盖以下 N 个既有场景；仅当修复段声明新增交付时可为该范围追加场景；移除既有场景必须给出理由」。生成后由确定性校验器（非 LLM）diff：缺既有场景且无理由 → 直接以持久化集补齐（等效于忽略 planner 的删减），报告标注。

### D3 校验器独立于 planner（不可被绕过）
diff 校验在 `.fenix/core/` 纯 Python 实现（读取 planner 输出 JSON + scenarios.json + 修复段文本），planner 无法通过输出文本绕过。写回 scenarios.json 的操作只发生在校验通过后。

### D4 与并行验证的关系
多 spec 并行验证各自有独立 verify-progress 目录，无共享状态；场景执行器不感知本变更。

## Risks / Trade-offs

- 既有场景每轮全量重跑，修复轮成本仍为 O(既有集) → 这是回归语义的正确代价；增量式（只跑修复相关）会丢回归保障，明确不做
- planner 对「新增范围」的边界判断靠 prompt + 修复段文本约束，可能偶发超范围追加 → 报告可见（新增场景列明所属范围），人工可纠偏；P 级场景不做硬拦截

## Migration Plan

1. scenarios.json 读写模块 + diff 校验器 + planner prompt 注入（一次提交）
2. 存量 spec：已有 verify-progress 目录的（config 等）在下次验证时按首轮逻辑补写 scenarios.json
无配置变更。

## Open Questions

（无）
