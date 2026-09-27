# proposal: add-verdict-step-failure-evidence-derivation

## 背景

planner-judge（出题式验证的判卷车道）产出的裁决证据要过校验器（core/verdict_check.py triage_violation）的 fail-closed 校验。其中「漏条目检测③」（:231-242）要求：场景存在失败信号（step_results success=false 或 visual_results diff_detected/warning）时，judge 必须在 evidence.failed_assertions 逐条自申报失败清单，否则驳回。

而验证引擎的步骤语义是「任一步骤原语失败即跳过断言执行」（verify_engine 的 cli_runner.py:80-91、api_runner.py:113-123、web_runner.py:243-279），因此「步骤失败型场景」的 assertion_results 必然为空表——判卷提示词若只教「从 assertion_results 摘未通过断言」，该形态下首轮漏 triage、重试轮摘出空表，fail-closed 驳回-重试死循环。

## 问题现场

add-knowledge-atlas-maintenance 验证收口（2026-09-27）：12:57/12:59 两轮判卷 2.30+0.63 美元连败（首轮 triage 缺失、重试轮 failed_assertions 空表）→ 阻断推进为 blocked-env → 13:42 达重验上限 3 暂停自动重验等人工；验证侧白跑约 7.8 美元、收口延迟半天。

处方已由 fe612841 修复（agents/planner-judge.md:85 补「步骤失败型场景必填清单（强制）」自申报指导），但残余敞口仍在：

- 检测③分支连一个单测都没有（tests/test_verify_verdict_multi_kind.py 现有 triage 用例均不构造该形态）；
- 无任何冻结回归场景固化「assertion_results 空表 + 失败步骤在场」形态；
- 提示词处方是 LLM 行为约束，无防漂移守卫，后续改写可静默丢失；
- 重试轮仍靠 judge 自觉补报，框架没有把失败信号机械映射为缺省清单的兜底。

## 目标

- 校验器在判违规前由失败信号派生缺省 failed_assertions 清单，triage 覆盖校验改对派生清单核验——fail-closed 语义保留（逐条归因仍必须覆盖清单），只消除空表死循环。
- 重试轮注入派生清单，judge 直接拿到应申报条目而非再撞一次空表。
- 单测固化该形态 + planner-judge.md 处方防漂移守卫。

## 非目标

- 不改检测①②语义与 blocked-env 推进语义。
- 不改 planner-judge 判卷流程、重试次数与验证轮编排。
- 冻结回归场景由本 spec 自身 verify 轮产出（验证链车道职责，冻结集不入库），不列入实现者交付物。