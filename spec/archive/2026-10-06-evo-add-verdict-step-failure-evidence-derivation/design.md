# design: add-verdict-step-failure-evidence-derivation

## D1 派生 helper 放校验器内

core/verdict_check.py：在 _scenario_has_failure_signal（:146-160）旁新增派生 helper——从 step_results（success=false）与 visual_results（diff_detected/warning）生成缺省 failed_assertions 条目（步骤/断言名 + 步骤失败型标注）。triage_violation（:178）检测③（:231-242）返回违规前先派生：有派生清单时，违规文案从「清单缺失」改为「未逐条覆盖」并列出派生条目；检测①②语义不动。

## D2 重试注入点

core/pm_engine/verification/verdict_evidence.py 的 _write_verdict_violations（:455）把派生清单写进重试提示（既有重试链：_verify_verdict_evidence :244 首轮违规→重试一次 :314-344，二次违规→cause=violations :398-403）；重试次数与 blocked 推进逻辑（verification/pipeline.py:661）不动。

## D3 守卫测试

- tests/test_verdict_step_failure_shape.py（新建）：仿 tests/test_verify_verdict_multi_kind.py 的 TestMultiKindTriageRequirement 风格，进程内构造「assertion_results 空表 + step_results success=false」场景调 triage_violation，断言两态：归因未覆盖派生清单→违规且文案含派生条目；逐条覆盖→合规。
- tests/test_agent_prompt_files.py（既有）：断言 agents/planner-judge.md 含「步骤失败型必填清单」处方小节。

## D4 冻结回归场景的落位

「冻结回归场景」按框架惯例由本 spec 自身 verify 轮产出（seed + 进程内装配出题；冻结集在 .fenix/verify-progress/<spec>/，属验证链车道职责且被 gitignore 不入库）。实现者交付物是触发该形态的派生代码与单测；SPEC 交付路径按仓库记法只写 core/ 与 tests/。

## 非目标

检测①②、blocked-env 推进、重试次数、planner-judge 判卷流程均不动。

## 风险

派生清单（步骤级）与 judge 实际归因（断言级）的粒度差可能造成二次驳回：派生条目标注「步骤失败型」形态，triage 覆盖校验允许以步骤名对应归因条目，避免驳回-重试换一种形态复发。