# 裁决步骤失败证据派生

<!-- knowledge: capability=verdict-step-failure-evidence-derivation rev=1
     sources=spec/archive/2026-10-06-evo-add-verdict-step-failure-evidence-derivation -->

出题式验证判卷的步骤失败形态兜底：场景无引擎断言清单也无自申报清单而存在失败信号时，校验器机械派生缺省 failed_assertions 清单作为逐条归因核验基准——fail-closed 硬门不弱化，空表形态不再空转驳回。

## 规则

- 派生触发条件（triage_violation 漏条目检测③）：非 PASS 场景的 assertion_results 缺失/非列表/空表，且 evidence.failed_assertions 也无自申报条目，而场景存在失败信号时，校验器在判违规前由失败信号派生缺省 failed_assertions 清单，以派生清单为基准执行 triage 覆盖校验。
- 失败信号判定口径：step_results 任一条目 success=false，或 visual_results 存在 diff_detected/warning 驱动视觉结论；baseline_deferred/baseline_rejected 等非驱动视觉状态不构成失败信号。畸形条目（None/字符串/数字/空 dict）不构成失败信号也不致校验崩溃（空 dict 的 success 缺省 True）。
- 派生条目形态与判卷申报处方同构：step_results 失败条目派生 `type=step_error`（selector 为步骤可引用名：动作 + target/命令/URL/选择器 + 序号壳），visual_results 驱动结论派生 `type=screenshot_mismatch`（selector 带 `visual:` 前缀），两类均带 step_failure 标注；字段为 type/selector/expected/actual，actual 文本 ≤300 字。
- fail-closed 不弱化：triage 归因未逐条覆盖派生清单仍判违规，违规文案列出未覆盖的派生条目并要求逐条申报，不给「任一条合规 triage 即放行」留口；部分覆盖（多失败步骤只归因其一）同样违规。断言清单（检测①）与自申报清单（检测②）两条漏条目检测语义不变。
- 覆盖核对两级口径：归因条数少于派生条数 → 全部派生条目视为未覆盖；条数足够时，含专名标注（步骤 target/命令/URL、视觉名）的派生条目 MUST 被某条归因按名称提及——完整标注互不包含时专名子词、裸视觉名（剥 `visual:` 前缀别名）亦可对账；名称命中的较短方须 ≥4 字符；仅通用动作词标注（引擎未回传 target，无法对账）豁免名称核对，条数覆盖即为逐条归因落点。
- 防御兜底：场景有失败信号但畸形条目形态派生不出任何条目时，沿用「断言清单缺失、须逐条申报」违规文案，不放行。
- 重试轮注入：本形态判违规进入重试时，派生清单以 `derived_failed_assertions` 键附挂进裁决驳回清单落盘，重试 prompt 直接给出应申报条目而非再撞一次空表；report 缺席时违规清单原样返回（重合成等调用方幂等不受影响）；裁决重试次数与 blocked 推进逻辑不变。
- 提示词处方防漂移守卫：agents/planner-judge.md 保留「步骤失败型场景必填清单（强制）」处方小节（assertion_results 空/缺失但存在失败步骤或驱动视觉结论时 MUST 逐条自申报 failed_assertions），tests/test_agent_prompt_files.py 断言该处方逐字在场，缺失即测试失败。

## 溯源

- 2026-10-06 evo-add-verdict-step-failure-evidence-derivation（spec/archive/2026-10-06-evo-add-verdict-step-failure-evidence-derivation） — 新增步骤失败形态失败清单派生（检测③判违规前机械派生缺省清单、条数+名称对应两级覆盖核对）、重试轮派生清单附挂注入与 planner-judge 处方防漂移守卫
