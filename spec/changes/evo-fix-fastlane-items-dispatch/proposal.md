## Why
fenix-prototype 交付实质完成仍被升级闸门冻结悬置（核查时刻约 7.7 小时、输入 token 约 116 万、白跑 2 个载具 run），同闸门历史冻结已 4 次。核查定位到结构性单因：fastlane 经 _execute_agent(spec_name, "code-fix") 派发时，runner 只对 agent_type=repair 传 detail，code-fix 载具恒拿空修复清单（run 归档 thinking 自证「The items list is empty: []」），注定 0 items 收尾并把失败计数推过冻结阈值。

## What Changes
1. 修复 fastlane→code-fix 的修复条目注入：派发前把失败场景转单为 items，prompt 构建空回退加告警留痕。
2. 升级闸门冻结前对「失败场景数少且 judge 根因行级定位」形态先派一轮定向修复并重验，修不过再冻结。
3. 升级告警 recommended_action 注入验证报告行级根因，降低人工核对成本。

## Impact
- core/agent_runner/runner.py、core/pm_engine/verification/fastlane.py、core/agent_runner/prompt_builder.py、core/pm_engine/family.py
- 新增契约测试 tests/test_fastlane_items_dispatch.py
- 与在途 fix-verify-loop-convergence 同改 bug-found 路由面，实现时须对齐判据避免双触发