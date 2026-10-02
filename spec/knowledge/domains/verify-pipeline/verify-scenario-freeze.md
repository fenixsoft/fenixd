# 验证场景冻结
<!-- knowledge: capability=verify-scenario-freeze rev=1 sources=spec/archive/2026-09-06-add-verify-scenario-freeze -->

验证场景集的持久化冻结与受控增量：修复轮重验受冻结场景集约束，不以新场景集扩大验收范围。

## 现行规则

- 场景集持久化：首轮验证裁决产出场景集时，将 scenario_id 列表（含 description）持久化到 `.fenix/verify-progress/<spec>/scenarios.json`（记录轮次来源）；已有该文件时不无条件覆盖。
- 修复轮复用持久化集：spec 处于修复轮（存在 `_verify_fail_rounds` 或 tasks.md 含「验证修复」段）时，验证场景 planner 以持久化集为基准生成场景；新增场景仅允许覆盖修复段声明的新增交付范围，合并结果写回 scenarios.json（记录追加轮次）。
- 删减须有理由并留痕：planner 产出缺少持久化集中既有场景时必须提供理由（如对应用例代码已删除），并在验证报告「本轮移除的场景及理由」小节列出；无理由的缺场景按 planner 输出不完整处理——以持久化集补齐缺失场景后继续，不中断验证。
- 冻结边界：场景集冻结不改变裁决标准与报告格式。

## 溯源

- 史前复原（存量基线） — 验证场景集持久化冻结，修复轮重验受冻结场景集约束，不以新场景集扩大验收范围
- 2026-09-06 add-verify-scenario-freeze（spec/archive/2026-09-06-add-verify-scenario-freeze） — 固化持久化、修复轮受控增量与删减留痕契约（场景集曾每轮重新生成且只增不减，修复轮被迫面对膨胀后的全套场景，验收成本随轮次递增、终点线移动）
