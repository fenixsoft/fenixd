## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/pm_engine/verification/judge_gate.py
  kind: modify
- path: tests/test_judge_repair_budget_alignment.py
  kind: new
```

## 1. 修复通道受理门（无修复纯归因模式）

- [ ] 1.1 `core/pm_engine/verification/pipeline.py` scenario-repaired 申报受理处：`_scenario_repair_exhausted_rounds >= 1` 时拒收修复（场景文件不改写、不触发场景重执行重入），裁决产物照常落盘（test-defect 仅记录），WARNING「修复预算已耗尽，转纯归因」留痕；字段键名与 escalation.py 既有读写严格一致
- [ ] 1.2 单测（tests/test_judge_repair_budget_alignment.py 新建，与 Deliverables 声明一致）：①耗尽态 judge 申报 scenario-repaired → 拒收、场景文件未被改写、裁决产物含 test-defect 记录；②未耗尽 → 既有修复路径逐位不变

## 2. 耗尽状态跨重启持久

- [ ] 2.1 审计 `_scenario_repair_exhausted_rounds` 的全部写入点：确认 daemon 恢复 / admin 处置复位 / 排程重验触发等路径均不清除该字段（唯一清零点 = verified + 人工解冻，state_machine.py:628-634 口径）；发现误清路径就地修正并留痕
- [ ] 2.2 单测：①耗尽 → 模拟 daemon 重启（新 pipeline 实例读 STATE）→ 受理门仍拒收；②admin 处置复位 → 字段不变；③人工解冻 → 清零、受理门放行

## 3. 硬上限告警附修复预算上下文

- [ ] 3.1 `core/pm_engine/verification/judge_gate.py` `_judge_hard_cap_freeze`：告警 evidence 拼入修复耗尽字段值与最近一次修复申报摘要（场景 id 级截断）；recommended_action 按耗尽与否分叉（耗尽 → 指向人工修复/归因豁免路径）
- [ ] 3.2 单测：触顶冻结时告警字段含修复上下文；无修复历史时文案退化到既有形态不报错

## 4. 回归

- [ ] 4.1 既有 judge 预算/修复相关用例全绿（未耗尽路径的修复-重执行-验收链路逐位一致）
