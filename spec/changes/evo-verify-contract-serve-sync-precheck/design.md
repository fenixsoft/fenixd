## Context

2026-11-11 web-browser-client：出题 run（planner-plan-web-browser-client-1794393480-a1，本地 18:38 派发）把场景集从纯 cli 扩为 api/cli/web（32 条：cli 20/web 11/api 1），契约 .fenix/verify.yaml 仍为 96a21df（11-08）起草的纯 cli 形态（serve/ready 以「省略」注释留档）；实现合并消费期 13:46:58.999Z 才被 serve 一致性门打回（fenixd.log:10072），1 个 admin run（admin-web-browser-client-1794404819，857.21s/128 轮）代起草 serve/ready（b959617，21:59:20 +0800），验证推迟约 13 分钟（打回到 verifier 重派 14 分 19 秒）。该族缺口 4 天三度：①11-08 契约模板态、②11-09 regression 段事后补记（f3b577e）、③本次 serve 段。

## 关键代码事实（已回源核实）

以下行号为 2026-11-16 评审复核快照，定位以符号名为准（活跃仓库行号会漂移）：

- 交叉规则本体已存在：core/verify_engine/scenario_static_check.py（SERVE_MISSING_RULE_ID="serve_missing_for_scenario_kinds"，复核行号 989；SERVE_REQUIRED_KINDS={api,web}、start_fallback_valid 占位哨兵判定，复核行号 992）。
- 消费期入口唯一：_run_contract_static_check（core/pm_engine/verification/scenario_gate.py，复核起点行号 1001），scan_contract 全库仅此一处调用（同文件内）；挂点 pipeline.py `_run_contract_static_check` 调用两处（复核行号 3621 消费前统一挂点，覆盖冻结复用与并行产物短路路径；3819 出题验收后），命中即打回+信号+return（不 replan）。
- 写盘/验收路径无契约感知：场景文件写端 write_scenarios_array（core/verify_engine/scenarios.py，复核行号 2134，planner 产物收编写端）、验收 load_scenarios（同文件，复核行号 2041；pipeline.py 内 5 处调用均仅有 schema/形状校验，零契约感知）。
- 周期预检盲区：core/admin_monitor.py 契约周期预检（复核行号 4371-4373）只判 contract_file_unresolvable（模板态/损坏态），合法 YAML 缺段不可见。

## 方案

把交叉规则校验抽成可独立调用入口（scenario_gate.py），前挂产物写盘点与验收点（pipeline.py）；信号复用 _write_verify_contract_missing 通道，实现期语义与在途 add-provider-validation-alert-governance/specs/verify-contract-precheck-noise-reduction（info 一次性，机制已在主树落地：admin_monitor.py 契约周期预检段 severity=info + store.has_unhandled_signal 持久去重 + 只沉淀不召唤）兼容。

通道落地面（评审复核 2026-11-16）：_write_verify_contract_missing 现硬编码 severity="major" 且 docstring 语义为「直接派发召唤 Administrator」——前置信号复用该通道 MUST 顺带把 severity 参数化（默认值保持 major，消费期既有调用点零变化），前置挂点传 info；一次性去重复用既有判据 store.has_unhandled_signal(spec, "verify_contract_missing")（判据持久化随告警账本、daemon 重启不重发、处置 handled 后复位允许再次提示，口径同周期预检降噪实现）。前置信号的 info 级判定不沿用周期预检的 ready/implementing 状态机窗口（出题产物挂点由验证流水线派发，spec 可处于 testing 或并行出题时 implementing）：凡出题产物写盘/验收挂点命中一律 info 级一次性——该挂点语境是代起草情报提示，不是验证拦截；进入验证期未补段仍由消费期门按 major 打回（最后防线行为不变）。契约起草职责变更不在本 SPEC 范围：契约代起草现归 admin/code_fix 车道且有自证门（bin/fenix_verify_contract.py），让 planner 代起草需改 prompt 契约情报段语义并给工具，成本高于检出收益，收敛为后续评估项。

## Risks

- 写盘点高频调用必须 fail-open（契约缺失/解析失败不阻断出题）。
- 双门并存（前置信号+消费期门）须同缺口去重，防重复信号——去重只约束前置信号自身（写盘点/验收点跨挂点同 spec 同缺口单条，复用 has_unhandled_signal 既有判据）；消费期门行为不变（major 打回+召唤为最后防线，不受去重抑制）。
- 前置信号不改变消费期门为最后防线的兜底语义。