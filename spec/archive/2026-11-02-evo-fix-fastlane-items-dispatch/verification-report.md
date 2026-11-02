# 验证报告：evo-fix-fastlane-items-dispatch

> ⚠️ 本报告由框架于 2026-10-30T12:46:49Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T12:46:48.591740+00:00+run-result@mtime1793364408655163995

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.23M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| fastlane-items-contract-tests-green | 契约测试全量：本 SPEC 交付的 tests/test_fastlane_items_dispatch.py 12 例全过——覆盖 items 白名单转单（1.2）、prompt 非空注入（1.1）、空清单告警去重（1.3）、冻结前分流先修后冻/不满足形态冻结/重验失败记账/承接互斥/车道熔断/告警根因注入（2.1/2.2/2.3）。命令只带 -v 不并 -q（pytest 9 中 -q 吞 PASSED 行），断言文案取自实测输出。出处：tests/test_fastlane_items_dispatch.py:1-489 | pass | 0/9 | - |
| items-transfer-whitelist-mapping | R1「派发携带非空条目」：build_fastlane_items 把失败场景按 _CODE_FIX_ITEM_FIELDS 白名单转单——场景 ID→item_id、根因行级定位（core/runner.py:123）→file/line、根因说明→description、severity high→major 归一，键名全部落白名单内；转单 detail 经 _build_code_fix_prompt 渲染为非空 items JSON（不再恒 '[]'）。出处：core/pm_engine/verification/fastlane.py:1086-1152、core/agent_runner/prompt_builder.py:76-79,2176-2191 | pass | 0/3 | - |
| empty-items-fastlane-warning-dedup | R1「空清单告警留痕」：items 为空但派发方经 detail 顶层键 has_failed_scenarios 声明存在待修失败场景时，prompt 构建出 WARNING 留痕（文案含「items 为空」），且同派发源第二次构建不再告警（进程级去重，恰 1 条）——消灭静默空转。出处：core/agent_runner/prompt_builder.py:84-110,2177-2185 | pass | 0/2 | - |
| non-fastlane-consumer-no-false-warning | R1 告警触发面收窄（异常路径防护）：code-review-fix 台账批（detail 仅 {"items": []}）与 maintenance 车道（detail 空字典）有意不带 items 属正常形态，构建 prompt 不得出空清单 WARNING（零误报）。出处：core/agent_runner/prompt_builder.py:91-96,2178 | pass | 0/2 | - |
| items-degrade-without-judge-verdict | R1 空状态：judge 裁决产物缺席（无 .fenix-run-result.json）时 _load_judge_bugs 返回空、items 退化为「场景 ID + 缺省 severity/category/title」仍非空（不空转），且分流判据按不满足保守回落（无根因证据宁可冻结不分流）。出处：core/pm_engine/verification/fastlane.py:1016-1046,1086-1152,1195-1228 | pass | 0/2 | - |
| pre-freeze-diversion-converge-no-budget-bump | R2「满足分流形态先修后冻」：_do_spec_bug_found 在冻结预算 2（阈值 MAX_VERIFY_FAIL_ROUNDS=3 临界）收到 bug-found 事件，失败场景数 ≤3 且根因行级定位 → 先派一轮 code-fix 定向修复（detail.items 非空）+ 子集重验收敛：状态 verified、_verify_fail_rounds 不递增（仍 2）、不冻结、无升级告警。出处：core/pm_engine/family.py:936-981、core/pm_engine/verification/fastlane.py:1259-1414 | pass | 0/2 | - |
| diversion-shape-not-matched-freeze-at-threshold | R2「不满足形态按原阈值冻结」（回归点：引入分流后原闸门语义不变）：根因非行级定位（无 file:line）→ 形态不满足、不派发任何 code-fix，沿 bump_counters 单点递增到 3 即 freeze_for_human，升级告警挂出。出处：core/pm_engine/verification/fastlane.py:1195-1228,1291-1301、core/pm_engine/family.py:1012-1047 | pass | 0/2 | - |
| diversion-reverify-fail-single-writepoint-budget | R2 记账纪律回归（单一写点）：分流先派定向修复但子集重验仍失败 → 沿 family bump_counters 单点递增 _verify_fail_rounds 到 3 并冻结，车道私有 _fastlane_fail_streak 保持 0 不被误记（禁碰约定）。出处：core/pm_engine/verification/fastlane.py:1269-1273,1395-1408、core/pm_engine/family.py:996-998 | pass | 0/2 | - |
| minor-defect-handled-event-no-double-dispatch | R2「承接已处置事件不重复分流」（双派发断言）：本失败事件已由 minor-defect fastlane 承接派发处置并回落（fastlane_decision.json stage=dispatch-failed、同 failed_id）→ 分流跳过、family 不再派第二次 code-fix，按既有记账路径递增到 1（<3）原地打回 implementer。出处：core/pm_engine/verification/fastlane.py:1231-1256,1303-1319 | pass | 0/2 | - |
| lane-circuit-break-skips-diversion | R2 守卫二（异常路径）：fastlane 车道熔断（_fastlane_fail_streak ≥ FASTLANE_MAX_CONSECUTIVE_FAILURES=2）期间不分流——同一 code-fix 载具已连续打转再派只白烧预算，直接按既有闸门路径递增到 3 并冻结。出处：core/pm_engine/verification/fastlane.py:75,1320-1341 | pass | 0/2 | - |
| diversion-exception-fails-open-to-gate | R2 异常路径：分流派发异常（agent_runner 抛错）≠ 修复失败——fail-open 回既有闸门路径（不收敛、bump_counters 单点递增到 3 并冻结），不重复记账也不绕过闸门。出处：core/pm_engine/family.py:953-970、core/pm_engine/verification/fastlane.py:1368-1379 | pass | 0/2 | - |
| diversion-boundary-3-vs-4-scenarios | R2 边界：失败场景数恰 3（阈值 FASTLANE_DIVERSION_MAX_FAILED_SCENARIOS=3 上界）且逐场景行级根因 → 形态满足、items 逐场景转单3 条；4 个失败场景超阈值 → 形态不满足、items 早退为空、reasons 记超阈值文案。出处：core/pm_engine/verification/fastlane.py:986,1195-1228 | pass | 0/3 | - |
| escalation-alert-root-cause-and-guidance | R3「告警携带根因」：升级闸门冻结分支的 recommended_action 含验证裁决产物行级根因（core/runner.py:123 + 根因说明）与「修复重验/豁免」裁决指引（manual_fixed_reverify/force_advance 等），既有结构化契约不变（signal_type=verify_fail_escalation、severity=major）。4 个失败场景超分流阈值逼入冻结分支。出处：core/pm_engine/family.py:733-801,1023-1047 | pass | 0/2 | - |
| escalation-alert-rootcause-fallback-guidance | R3 异常路径：裁决产物有 bugs 但无 root_cause 字段 → 根因收集返回空清单，recommended_action 落「请直接查阅 verification-report.md」查阅指引兜底，冻结主链不被阻断（告警照常挂出）。出处：core/pm_engine/family.py:760-771,787-795 | pass | 0/2 | - |
| adjacent-freeze-regression-suite-green | 回归点：分流/告警改动同面的邻接回归全绿——family_governor（33，闸门/冻结语义）+ dual_dispatch_and_freeze（25，bug-found 路由双派发面）+ agent_runner（22，code-fix detail 透传所在文件）。实测汇总 「80 passed」，只带 -q 不并 -v（与「N passed」断言形态配对）。出处：tests/test_family_governor.py、tests/test_dual_dispatch_and_freeze.py、tests/test_agent_runner.py | pass | 0/2 | - |
