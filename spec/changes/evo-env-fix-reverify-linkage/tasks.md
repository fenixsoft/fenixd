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
- [ ] 1.3 core/dashboard/data/adjudication_choices.py：为 blocked_stuck 注册裁决选项桶，沿用既有单选项桶的注册纪律（单选项收窄、requires_payload 载荷门），选项集为 manual_fixed_reverify——「同等」指注册纪律而非桶内容：verify_env_blocked 既有桶选项集是 _REVISE_SCENARIO_REVERIFY 且不含 manual_fixed_reverify，不得照搬既有桶内容；桶内精确匹配放行 spec 作用域动作
- [ ] 1.4 core/dashboard/data/admin_actions.py：VERIFY_CHAIN_SIGNAL_TYPES 白名单按注册桶同源补全——补 blocked_stuck（1.3 新注册桶）与 verify_env_blocked（既有注册桶，缺口三列举的另一未收录信号）；admin 链提示词的选项词表按信号桶生成，未注册信号不下发 spec 作用域词表

## 2. 回执落地校验

- [ ] 2.1 core/admin_monitor.py：为「闭环/复位/入队 verifier」类处置动作写可核验句柄（预期 spec 终态、预期 run 类型与 N 分钟判定窗），在处置终态回写与 chain-closed 事件后核验 STATE 迁移或对应类型 run 派发落地；未落地发升级告警并把处置标记无效，不记成功语义

## 3. 测试

- [ ] 3.1 tests/test_env_fix_reverify_linkage.py：覆盖链上闭环→testing 迁移并入队 verifier、互斥跳过登记待重评后下一巡检消费、blocked_stuck 桶内 manual_fixed_reverify 解析放行、判定窗内无落地发告警并标记处置无效四个场景
- [ ] 3.2 tests/test_env_fix_reverify_linkage.py：回归锚——frozen spec 既有解冻行为不变、非 blocked 态或非已修复处置不迁移、判定窗内落地成功时零告警