# 验证完成门
<!-- knowledge: capability=verification-completion-gate rev=3 sources=spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate,spec/archive/2026-09-02-improve-verify-adjudication,spec/archive/2026-09-05-add-inplace-bug-repair -->

SPEC 推进 done/pushed 前的三层放行门禁：进度完成度、场景结论质量、结果文件 fail-closed——跑不完不放行，跑完但有失败也不放行。

## 现行规则

- 进度门禁：验证流程已启动（存在该 SPEC 的 verifier 运行记录或 `.fenix/verify-progress/<spec>.json` 进度文件）的 SPEC，推进到 `done`/`pushed` 前必须校验验证进度 `done == total`（进度文件缺失或无法解析视同未完成）；未全量完成时阻止推进，保留在验证相关状态（`verified`/`testing`），并在状态记录中写入未完成原因（`done`/`total` 数值与最近一次 `current` 场景描述）。验证流程尚未启动的 SPEC 不受此限。
- 场景结论质量闸门：进度门禁之外额外解析 `.fenix/verify-progress/<spec>/report.json` 的场景级结论——全部场景 `pass` → 该层放行（最终放行仍取决于其它门禁）；存在 `fail` → 阻止推进并按分流规则处置；report.json 缺失或不可解析而验证流程确已启动 → fail-closed 阻止推进，不得仅凭进度计数放行。
- 失败场景噪音与缺陷分流：对质量闸门拦截到的失败场景区分两类——工具噪音（step_results 存在 `success: false` 如步骤缺失 target 中断，或 assertion_results 为空即断言从未执行）不能证明产品行为错误，不触发打回、写入人工升级告警交 Administrator 修正 `test_scenarios.json` 后重跑验证；真实产品缺陷（assertion_results 中存在实际执行的失败断言）执行原地打回处置——递增父 SPEC 失败轮数、重置回 `implementing`、在 tasks.md 追加「验证修复」任务段（修复依据为 verification-report.md 及其携带的失败断言证据），不创建 fix-* 子 SPEC。
- verifier 结果文件 fail-closed：`.fenix-run-result.json` 缺失、JSON 无法解析或 status 不在白名单（verified / bug-found / plan-ready）内时，不视为 verified 放行——SPEC 保留原状态、异常原因写入 error 字段，并发人工升级告警交 Administrator 裁决；不以任何默认值代替结论、不误读其他 agent 残留的状态码。
- 耗时列真实性断言：验证 SPEC 表格「耗时」列时区分两种「—」——无任何运行记录的 SPEC 显示「—」为合法占位；有运行记录的 SPEC 耗时列显示「—」或 0 判定为缺陷并报告（运行记录存在但 `duration_seconds` 聚合为 0 说明时长计算异常）。验证报告记录被检查的 SPEC 及其 run 数量、判定依据。

## 溯源

- 2026-09-02 fix-dashboard-duration-and-verify-gate（spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate） — 建立进度门禁（done==total 才可推进）与耗时列真实性断言规则
- 2026-09-02 improve-verify-adjudication（spec/archive/2026-09-02-improve-verify-adjudication） — 叠加场景结论质量闸门、噪音/真缺陷分流与结果文件缺口 fail-closed（取代「解析失败视为 verified」的 fail-open 行为）
- 2026-09-05 add-inplace-bug-repair（spec/archive/2026-09-05-add-inplace-bug-repair） — 真实产品缺陷处置由派生 fix SPEC 改为原地打回父 SPEC（保留全部上下文，噪音分流与 fail-closed 语义不变）
