## Context
- 派发链：core/pm_engine/verification/fastlane.py:766 `_execute_agent(spec_name, "code-fix", run_id)` → core/agent_runner/runner.py:3468-3471 仅对 agent_type=repair 传 detail → core/agent_runner/prompt_builder.py:2148 `items = detail.get("items") or []` 恒空。
- 升级闸门：core/pm_engine/family.py _do_spec_bug_found（def 731），fail_rounds>=MAX_VERIFY_FAIL_ROUNDS(=3) 即 freeze_for_human（857-894）；告警已带 4 个结构化 choices（continue_auto_fix/manual_fixed_reverify/force_advance/abandon）。
- 现状：fastlane 子集重验失败会把计数推过阈值（本例 _fastlane_fail_streak=1、_verify_fail_rounds=3）。

## Goals / Non-Goals
- Goals：code-fix 载具拿到真实修复条目；冻结前定向修复分流；告警根因注入。
- Non-Goals：不改冻结闸门本身的防烧钱语义；不改 judge 车道；不处理 env/infra 失败（归 evo-verify-infra-retry-lane 辖区）。

## Design
- items 转单：fastlane 派发前从验证报告/失败场景集构造 items（场景 ID、涉及文件、根因行号），经 _execute_agent 新参传入；runner 对 code-fix 与 repair 同样透传 detail。
- 空回退告警：prompt_builder 发现 items 空且存在失败场景时 WARNING（进程级去重），消灭静默空转。
- 分流判据：失败场景数 ≤3 且 judge 结论含行级根因（复用验证报告 bug 定位字段）→ 冻结前先派一轮 fastlane 定向修复+子集重验；仍失败才 _bump_fail_streak 走冻结。与 fix-verify-loop-convergence 的打回闸门互斥：同一次失败事件只走一条路由。
- 告警增强：freeze_for_human 组装 recommended_action 时注入报告根因行与裁决指引文案。

## Risks / Trade-offs
- 分流会延后冻结时刻、多烧一轮修复预算——以「≤3 场景+行级根因」收窄触发面控制成本。
- 与在途 fix-verify-loop-convergence 判据体系须对齐，避免同一失败被两套机制重复处置。