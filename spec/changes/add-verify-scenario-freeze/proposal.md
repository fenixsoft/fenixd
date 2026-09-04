# Proposal: add-verify-scenario-freeze

## Why

验证场景集每轮重新生成且只增不减：v2-config-page 第 1 轮验证 11 个场景，修复后第 2 轮变 17 个——修复轮只需修已注入的 bug，却要面对膨胀后的全套场景，验收成本随轮次递增（复盘改进点 3）。终点线移动使「修复→验证」循环更难收敛。

## What Changes

- 首轮验证的场景集（scenario_id 列表）持久化到 `.fenix/verify-progress/<spec>/scenarios.json`
- 修复轮验证默认复用持久化场景集；仅当修复段（tasks.md「验证修复」）声明了新增交付范围时，planner 才允许为**新增范围**追加场景
- planner 的重规划产出与持久化集 diff：只增 scenario_id 时合并写回；删减既有场景 MUST 提供理由（场景对应用例已删除等），并在验证报告标注
- 场景集冻结不改变裁决标准与报告格式

## Capabilities

### New Capabilities
- `verify-scenario-freeze`: 验证场景集的持久化、修复轮复用与受控增量

### Modified Capabilities

（无——场景生成入口与报告格式不变，只增加集的持久化与 diff 约束）
