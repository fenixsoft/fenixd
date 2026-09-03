# Tasks: fix-repair-lane-dedup

## 1. 同根度量与活跃判定助手

- [x] 1.1 抽取/复用族谱同根判定：`_same_root_siblings(spec_name)` 返回同根非终态兄弟列表（排除自身）；`_sibling_repair_active(spec_name)` 判定兄弟 actionable（implementing / ready且队列含实现器 / 活跃 agent 存活探测复用）；补单测四例
- [x] 1.2 判定 `is_fix_spec`（fix- 前缀）与"子 fix 非终态存在"检查，供两守卫共用；补单测

## 2. 三守卫接线（design D1）

- [x] 2.1 守卫一：_do_spec_bug_found reset 路径前置守卫——fix spec 且有非终态子 fix → 保持 bug-found + error 注明承载方 + 不派发；补单测（抑制/子终态解封两例）
- [x] 2.2 守卫二：judge 判定 bug-found 派生路径前置守卫——被验对象为 fix spec 且 ready/implementing → 跳过派生 + error 注明在飞承载；补单测（跳过/照常派生两例）
- [x] 2.3 守卫三：_process_queue 派发 fix spec 实现器前同根互斥检查（含队列条目与活跃 agent 判定，仅 ready 无条目不阻塞）；补单测（双 ready 不重复派发 / 僵死 ready 不阻塞两例）

## 3. 回归与核验

- [x] 3.1 全量 pytest 通过（重点 tests/test_core.py pm_engine 相关及新增用例），无既有用例回归；正常单链路径零行为差异对照测试
- [x] 3.2 对照 capability spec 全部 Scenario 逐条核对实现覆盖并记录结论

### 3.2 Capability Scenario 覆盖结论

| Requirement / Scenario | 实现点位 | 单测 |
|---|---|---|
| 守卫一·有非终态子 fix 时重置被抑制 | `_do_spec_bug_found` 守卫一（`_is_fix_spec` + `_has_non_terminal_child_fix`） | TestGuardOneResetSuppression::test_suppresses_reset_when_child_fix_active |
| 守卫一·子终态后解封 | 同上，子 done/pushed 时 `_has_non_terminal_child_fix` 返回空串，守卫不生效 | TestGuardOneResetSuppression::test_no_suppression_when_child_terminal |
| 守卫二·重实现在飞时跳过派生 | judge 派生路径（`_run_three_stage_verification` / `_run_legacy_verification`）`_is_fix_spec` + status∈{ready,implementing} | TestGuardTwoSpawnSuppression::test_suppresses_spawn_when_fix_spec_implementing |
| 守卫二·非在飞时照常派生 | 同上，非 fix 前缀或无在飞时原路径不变 | TestGuardTwoSpawnSuppression::test_no_suppression_when_not_fix_spec |
| 守卫三·双 ready 历史现场不重复派发 | `_process_queue` 守卫三：`_sibling_repair_active` 检测 implementing/队列条目 | TestGuardThreeDispatchMutex::test_skips_dispatch_when_sibling_implementing |
| 守卫三·僵死 ready 不阻塞 | 同上：仅 ready 无队列条目且无活跃 agent 不计 actionable | TestGuardThreeDispatchMutex::test_no_block_when_sibling_ready_no_queue |
| 零行为差异回退保证 | 三守卫均先判 `_is_fix_spec` / 无同根非终态兄弟 / 子终态后自动失效 | TestZeroBehaviorDiffFallback（4 例） |

全部 Scenario 已实现覆盖并通过单测；全量 pytest 690 例无回归。
