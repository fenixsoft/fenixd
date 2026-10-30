## Context
- 派发链（2026-10-30 评审实测行号）：core/pm_engine/verification/fastlane.py:783 `fix_result = _execute_agent(spec_name, "code-fix", run_id)`（不传 detail）→ core/agent_runner/runner.py:3467-3475 仅对 agent_type=repair 传 `detail=conflict_summary or {}` → core/agent_runner/prompt_builder.py:2146 `items = detail.get("items") or []` 恒空。
- 升级闸门：core/pm_engine/family.py _do_spec_bug_found（def 731），fail_rounds>=MAX_VERIFY_FAIL_ROUNDS(=3) 即 freeze_for_human（冻结分支 893-933，`_verify_fail_rounds` 计数单一写点 bump_counters 877-879）；告警已带 4 个结构化 choices（continue_auto_fix/manual_fixed_reverify/force_advance/abandon，adjudication_choices.py:199-216）。
- 现状：fastlane 子集重验失败会把计数推过阈值（本例 _fastlane_fail_streak=1、_verify_fail_rounds=3）。

## Goals / Non-Goals
- Goals：code-fix 载具拿到真实修复条目；冻结前定向修复分流；告警根因注入。
- Non-Goals：不改冻结闸门本身的防烧钱语义；不改 judge 车道；不处理 env/infra 失败（归 evo-verify-infra-retry-lane 辖区）。

## Design
- items 转单：fastlane 派发前从验证报告/失败场景集构造 items（场景 ID、涉及文件、根因行号），经 _execute_agent 新参传入；runner 对 code-fix 与 repair 同样透传 detail。条目字段 MUST 按 prompt_builder._CODE_FIX_ITEM_FIELDS 白名单（prompt_builder.py:76-79：item_id/file/line/severity/category/title/description/suggestion）映射——场景 ID→item_id、涉及文件→file、根因行号→line、根因说明→description；白名单外键名在序列化时整键剔除（prompt_builder.py:2147-2150），注入会被静默架空。
- 空回退告警：prompt_builder 发现 items 空且派发方声明存在待修失败场景（fastlane 经 detail 顶层键注入失败上下文标记；_CODE_FIX_ITEM_FIELDS 只约束 items 条目、不约束 detail 顶层键）时 WARNING（进程级去重），消灭静默空转。触发面以 fastlane 派发为限——其余 code-fix 消费面（code-review-fix 台账批、maintenance 车道）有意不带 items 属正常形态，不得误报。
- 分流判据：失败场景数 ≤3 且 judge 结论含行级根因（复用验证报告 bugs[].root_cause 字段）→ 冻结前先派一轮 fastlane 定向修复+子集重验；仍失败才回落 _do_spec_bug_found 按 bump_counters 单点递增 `_verify_fail_rounds` 后冻结（冻结预算单一写点 family.py:877-879；`_bump_fail_streak` 是 fastlane 车道私有 streak、禁碰该字段——fastlane.py:693-708 单一写点约定，code-review item 96cd9f5a32d2）。与既有 minor-defect 承接互斥：失败场景数=1 且承接 eligible 的失败事件在本事件内已由承接派发过 code-fix（pipeline.py:1369-1376），MUST NOT 再进入分流重复派发。与在途 fix-verify-loop-convergence 的打回闸门互斥：同一次失败事件只走一条路由。
- 告警增强：freeze_for_human 组装 recommended_action 时注入报告根因行与裁决指引文案。

## Risks / Trade-offs
- 分流会延后冻结时刻、多烧一轮修复预算——以「≤3 场景+行级根因」收窄触发面控制成本。
- 与在途 fix-verify-loop-convergence 判据体系须对齐，避免同一失败被两套机制重复处置。