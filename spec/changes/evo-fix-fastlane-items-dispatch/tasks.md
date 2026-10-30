## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/verification/fastlane.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: tests/test_fastlane_items_dispatch.py
  kind: new
```

## 1. fastlane 载具修复条目注入

- [ ] 1.1 core/agent_runner/runner.py：_execute_agent 对 code-fix 车道与 repair 同样透传 detail（items 随调用方注入），使 fastlane 派发的 code-fix 不再拿到空清单
- [ ] 1.2 core/pm_engine/verification/fastlane.py：派发前把失败场景（场景 ID/涉及文件/根因行号）转单为 items 传入 _execute_agent
- [ ] 1.3 core/agent_runner/prompt_builder.py：items 为空且该 spec 存在失败场景时 WARNING 留痕（进程级去重），替换静默空回退

## 2. 冻结前定向修复分流

- [ ] 2.1 core/pm_engine/family.py：_do_spec_bug_found 在达到 MAX_VERIFY_FAIL_ROUNDS 前，对「失败场景数 ≤3 且根因行级定位」形态先派一轮 fastlane 定向修复并子集重验，仍失败才计入冻结计数
- [ ] 2.2 core/pm_engine/family.py：freeze_for_human 组装 recommended_action 时注入验证报告行级根因与裁决指引，保留既有 4 个结构化 choices
- [ ] 2.3 core/pm_engine/family.py：分流判据与在途 fix-verify-loop-convergence 的打回闸门互斥（同一失败事件只走一条路由），以注释与实现落空

## 3. 测试

- [ ] 3.1 tests/test_fastlane_items_dispatch.py：断言 fastlane 派发 code-fix 时 prompt 含非空 items；items 空且有失败场景时出 WARNING
- [ ] 3.2 tests/test_fastlane_items_dispatch.py：分流单测——满足形态时不冻结先派修复、不满足形态仍按原阈值冻结；告警 recommended_action 含根因文本