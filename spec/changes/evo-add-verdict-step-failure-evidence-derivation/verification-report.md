# 验证报告：evo-add-verdict-step-failure-evidence-derivation

> ⚠️ 本报告由框架于 2026-09-27T18:56:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-27T18:56:54.645401+00:00

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.78M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| derive-step-failure-two-state | 证据派生主路径（spec Requirement 1 / Acceptance Scenario 1+2）：进程内构造「assertion_results 空表 + step_results success=false」形态调 triage_violation 验两态——归因未覆盖派生清单时判违规且违规文案列出派生条目（含失败步骤标识 probe-step-alpha，驱动有内容的重试而非同形态空转）；归因以失败步骤名逐条覆盖派生清单时合规（返回 None）。fail-closed 语义保留：只消除空表死循环。出处：core/verdict_check.py triage_violation 检测③（:231-243）、_scenario_has_failure_signal（:146-160）、design D1 | pass | 0/2 | - |
| derive-failclosed-partial-coverage | fail-closed 不弱化（spec Acceptance Scenario 2）：两个失败步骤（probe-step-alpha/probe-step-beta）只归因覆盖其一（alpha）时，triage_violation MUST 仍判违规，且文案列出未覆盖的派生条目（beta）——派生 SHALL NOT 弱化逐条归因硬门。出处：core/verdict_check.py 检测③（:231-243）、design D1 风险节 | pass | 0/2 | - |
| derive-visual-diff-two-state | 驱动视觉结论作为失败信号的派生路径：visual_results 含 status=diff_detected 条目（probe-visual-gamma）且 assertion_results 空表时，归因未覆盖→违规并列出该视觉派生条目；归因覆盖→合规。与 step_results 路径同规则。出处：core/verdict_check.py _scenario_has_failure_signal（:157-159）、design D1（派生 helper 覆盖两类失败信号） | pass | 0/2 | - |
| non-driving-visual-no-failure-signal | 非驱动视觉状态不构成失败信号（回归守卫）：visual_results 仅含 baseline_deferred / baseline_rejected 条目、无失败步骤、triage 合规在场时，triage_violation 返回 None——派生逻辑 MUST NOT 把非驱动视觉结论误当失败信号触发违规（检测③口径与 has_only_non_driving_visual_indicators 同源不回退）。出处：core/verdict_check.py _scenario_has_failure_signal（:146-160）docstring 判定口径 | pass | 0/2 | - |
| malformed-signal-entries-robust | 异常路径·畸形失败信号条目鲁棒性：step_results/visual_results 含 None、字符串、数字、空 dict 等畸形条目时不崩溃，且畸形条目不构成失败信号（空 dict success 缺省 True）；混入一个真实失败步骤时派生与覆盖校验照常工作（覆盖→合规、未覆盖→违规含步骤标识）。出处：core/verdict_check.py _scenario_has_failure_signal（:154-159）isinstance 守卫 | pass | 0/2 | - |
| retry-prompt-carries-derived-list | 重试轮注入派生清单端到端（spec Requirement 2 / Acceptance Scenario 3）：①步骤失败形态（assertion 空表+失败步骤 probe-step-delta+归因缺失）经 validate_report 产出 triage 缺失违规（该形态派生清单不走 reason 文本）；②归因在场未覆盖形态违规 reason 列出派生条目（检测③）；③_write_verdict_violations 传 report 落盘 verdict_violations.json 并附挂 derived_failed_assertions（含 probe-step-delta）；④_verdict_rejection_section 渲染重试段（含场景 ID 与 probe-step-delta）；⑤空态返回空串不注入——重试 judge 直接拿到应申报条目而非再撞空表。2026-09-28 裁决原地修复：原 probe evidence 桩缺三要件被判「evidence 为空」即中止，且对归因缺失形态断言 reason 含派生条目属接缝建模错误（真实链路经附挂键携带，_write_verdict_violations 须传 report）——按产品契约修正接缝，断言意图不弱化。出处：core/verdict_check.py validate_report（:514-592）/检测③（:401-429）、core/pm_engine/verification/verdict_evidence.py _write_verdict_violations（:493-531）/_attach_derived_failed_assertions（:457-490）、core/agent_runner/prompt_builder.py _verdict_rejection_section（:2092-2174）、design D2 | pass | 0/2 | - |
| guard-test-verdict-step-failure-shape-passes | 守卫测试文件通过（spec tasks 2.1 / design D3）：tests/test_verdict_step_failure_shape.py（新建）仿 TestMultiKindTriageRequirement 风格的进程内两态用例全部通过——空表+失败步骤+归因未覆盖→违规含派生条目；逐条覆盖→合规。出处：tests/test_verdict_step_failure_shape.py（tasks.md Deliverables new）、design D3 | pass | 0/2 | - |
| guard-test-agent-prompt-files-passes | 提示词文件守卫测试全量通过（spec tasks 2.2）：tests/test_agent_prompt_files.py（既有文件新增处方在场断言）全量通过，含新增「步骤失败型必填清单」处方小节断言用例。出处：tests/test_agent_prompt_files.py（tasks.md Deliverables modify）、design D3 | pass | 0/2 | - |
| prescription-section-and-guard-present | 提示词处方在场 + 守卫防漂移（spec Requirement 3 / Acceptance Scenario 4）：agents/planner-judge.md 含「步骤失败型」必填清单自申报处方小节（fe612841 处方未漂移丢失）；tests/test_agent_prompt_files.py 中存在针对该处方小节的存在性断言守卫（引用 planner-judge 模板并断言处方标记在场——缺失该小节时该测试失败）。出处：agents/planner-judge.md:85、spec.md Requirement 提示词处方防漂移守卫 | pass | 0/2 | - |
| regression-multi-kind-triage-unchanged | 回归·检测①②语义不动：tests/test_verify_verdict_multi_kind.py 全量通过——cli/api 失败场景缺 triage 判违规、triage 合规放行、product-bug 拦截豁免、证据形态中立等既有不变量不被派生逻辑改写。出处：tests/test_verify_verdict_multi_kind.py、proposal 非目标（不改检测①②语义） | pass | 0/2 | - |
| regression-verdict-retry-chain-unchanged | 回归·裁决重试链既有行为不动：tests/test_verdict_dedup_resynthesis.py + tests/test_judge_efficiency.py 全量通过——驳回清单落盘/清退、重合成闭环、重试 prompt 注入段渲染、轮内记账等既有链路不受 _write_verdict_violations 改动影响；重试次数与 blocked 推进逻辑不变。出处：core/pm_engine/verification/verdict_evidence.py（design D2 非目标）、tests/test_verdict_dedup_resynthesis.py、tests/test_judge_efficiency.py | pass | 0/2 | - |
