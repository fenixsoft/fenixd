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
- [ ] 1.2 core/pm_engine/verification/fastlane.py：派发前把失败场景（场景 ID/涉及文件/根因行号）转单为 items 传入 _execute_agent；条目键名按 _CODE_FIX_ITEM_FIELDS 白名单映射（场景 ID→item_id、文件→file、行号→line、根因→description），MUST NOT 使用白名单外键名（否则序列化整键剔除、注入被静默架空）
- [ ] 1.3 core/agent_runner/prompt_builder.py：items 为空且派发方经 detail 顶层键声明存在待修失败场景时 WARNING 留痕（进程级去重），替换静默空回退；触发面以 fastlane 派发为限，其余 code-fix 消费面（code-review-fix 台账批、maintenance 车道）不带 items 属正常形态不得误报

## 2. 冻结前定向修复分流

- [ ] 2.1 core/pm_engine/family.py：_do_spec_bug_found 在达到 MAX_VERIFY_FAIL_ROUNDS 前，对「失败场景数 ≤3 且根因行级定位」且本失败事件未经 fastlane 承接派发处置的形态，先派一轮 fastlane 定向修复并子集重验；仍失败才经 bump_counters 单点递增 _verify_fail_rounds 计入冻结预算（单一写点 family.py:877-879，不得经 _bump_fail_streak 记账）
- [ ] 2.2 core/pm_engine/family.py：freeze_for_human 组装 recommended_action 时注入验证报告行级根因与裁决指引，保留既有 4 个结构化 choices
- [ ] 2.3 core/pm_engine/family.py：分流判据与在途 fix-verify-loop-convergence 的打回闸门互斥（同一失败事件只走一条路由），以注释与实现落地；注意 MERGE-NOTES.md 硬依赖——fix-verify-loop-convergence 现为孤儿在途（STATE 无条目不派发），其落地前本条以守卫注释形式存在

## 3. 测试

- [ ] 3.1 tests/test_fastlane_items_dispatch.py：断言 fastlane 派发 code-fix 时 prompt 含非空 items；items 空且有失败场景时出 WARNING
- [ ] 3.2 tests/test_fastlane_items_dispatch.py：分流单测——满足形态时不冻结先派修复、不满足形态仍按原阈值冻结；承接已派发过的失败事件不再触发分流（双派发断言）；告警 recommended_action 含根因文本