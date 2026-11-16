## Deliverables

```yaml
- path: core/pm_engine/escalation_chain.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: tests/test_env_fix_reverify_linkage.py
  kind: new
```

## 1. 链上闭环接续复位

- [ ] 1.1 core/pm_engine/escalation_chain.py：_close_chain_success 对环境阻塞族信号（verify_env_blocked、verify_env_inconclusive、blocked_stuck）且处置结果为已修复语义时，复用 admin_monitor 既有复位直通道（transition_gate(testing) + 清 error + 入队 verifier）完成 blocked→testing 迁移与重验派发；frozen spec 的既有解冻语义保持不变
- [ ] 1.2 core/admin_monitor.py：复位因处置在飞互斥被跳过时登记 spec 维度待重评标记，互斥解除后的下一巡检周期重评消费并完成迁移；标记消费后清除，不得再依赖 60 分钟 blocked_stuck 阈值兜底
- [ ] 1.3 core/dashboard/data/adjudication_choices.py：为 blocked_stuck 注册与 verify_env_blocked 同等的裁决选项桶（含 manual_fixed_reverify），桶内精确匹配放行 spec 作用域动作
- [ ] 1.4 core/dashboard/data/admin_actions.py：VERIFY_CHAIN_SIGNAL_TYPES 白名单补 blocked_stuck（与 1.3 同源收窄），admin 链提示词的选项词表按信号桶生成，未注册信号不下发 spec 作用域词表

## 2. 回执落地校验

- [ ] 2.1 core/admin_monitor.py：为「闭环/复位/入队 verifier」类处置动作写可核验句柄（预期 spec 终态、预期 run 类型与 N 分钟判定窗），在处置终态回写与 chain-closed 事件后核验 STATE 迁移或对应类型 run 派发落地；未落地发升级告警并把处置标记无效，不记成功语义

## 3. 测试

- [ ] 3.1 tests/test_env_fix_reverify_linkage.py：覆盖链上闭环→testing 迁移并入队 verifier、互斥跳过登记待重评后下一巡检消费、blocked_stuck 桶内 manual_fixed_reverify 解析放行、判定窗内无落地发告警并标记处置无效四个场景
- [ ] 3.2 tests/test_env_fix_reverify_linkage.py：回归锚——frozen spec 既有解冻行为不变、非 blocked 态或非已修复处置不迁移、判定窗内落地成功时零告警