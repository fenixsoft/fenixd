## Context

2026-11-11 web-browser-client：出题 run（planner-plan-web-browser-client-1794393480-a1，本地 18:38 派发）把场景集从纯 cli 扩为 api/cli/web（32 条：cli 20/web 11/api 1），契约 .fenix/verify.yaml 仍为 96a21df（11-08）起草的纯 cli 形态（serve/ready 以「省略」注释留档）；实现合并消费期 13:46:58.999Z 才被 serve 一致性门打回（fenixd.log:10072），1 个 admin run（admin-web-browser-client-1794404819，857.21s/128 轮）代起草 serve/ready（b959617，21:59:20 +0800），验证推迟约 13 分钟（打回到 verifier 重派 14 分 19 秒）。该族缺口 4 天三度：①11-08 契约模板态、②11-09 regression 段事后补记（f3b577e）、③本次 serve 段。

## 关键代码事实（已回源核实）

- 交叉规则本体已存在：core/verify_engine/scenario_static_check.py:662（SERVE_MISSING_RULE_ID、SERVE_REQUIRED_KINDS={api,web}、start_fallback_valid 占位哨兵判定）。
- 消费期入口唯一：_run_contract_static_check（core/pm_engine/verification/scenario_gate.py:1009-1100），scan_contract 全库仅此一处调用；挂点 pipeline.py:3370（冻结/并行产物消费前）与 :3568（出题验收后），命中即打回+信号+return（不 replan）。
- 写盘/验收路径无契约感知：pipeline.py:1565 写点、:2394 验收、:3092 消费入口仅有 schema/形状校验。
- 周期预检盲区：core/admin_monitor.py:4029 只判 contract_file_unresolvable（模板态/损坏态），合法 YAML 缺段不可见。

## 方案

把交叉规则校验抽成可独立调用入口（scenario_gate.py），前挂产物写盘点与验收点（pipeline.py）；信号复用 _write_verify_contract_missing 通道，实现期语义与在途 add-provider-validation-alert-governance/specs/verify-contract-precheck-noise-reduction（info 一次性）兼容——前置信号落在实现期即受其降噪语义约束，进入验证期未补段仍由消费期门按 major 打回。契约起草职责变更不在本 SPEC 范围：契约代起草现归 admin/code_fix 车道且有自证门（bin/fenix_verify_contract.py），让 planner 代起草需改 prompt 契约情报段语义并给工具，成本高于检出收益，收敛为后续评估项。

## Risks

- 写盘点高频调用必须 fail-open（契约缺失/解析失败不阻断出题）。
- 双门并存（前置信号+消费期门）须同缺口去重，防重复信号。
- 前置信号不改变消费期门为最后防线的兜底语义。