# 验证报告：evo-add-scenario-serve-consistency-preflight

> ⚠️ 本报告由框架于 2026-10-10T19:27:45Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-10T19:27:44.468730+00:00+run-result@mtime1791660464501736374

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.77M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| serve-consistency-new-tests-green | 交付物 tests/test_scenario_serve_consistency.py 存在且全部用例通过（tasks 3.1/3.2/3.3 三组测试的汇总绿门）：静态检查交叉规则、挂载路径、前置探测收紧的实现对自身测试全绿（tasks.md 交付清单第 4 项） | pass | 0/3 | - |
| scan-webapi-kinds-no-serve-report-finding | scan_contract 交叉规则正向：契约无 serve 段且场景 kind 集含 api/web（api+web、仅 api、仅 web 三形态）时报 serve 缺失 finding（proposal 变更 1；出处 core/verify_engine/scenario_static_check.py:624 scan_contract、现 :654 serve-None 早退对该规则解除屏蔽） | pass | 0/2 | - |
| scan-pure-cli-no-serve-stays-legal | 纯 cli 兜底不回归：场景 kind 集全为 cli 且契约无 serve 段时不报 serve 缺失（cimbar-airgap-transfer 历史形态合法，proposal 变更 4）；同时缺省调用 scan_contract(root)（不传 kind 集，兼容既有 caller core/pm_engine/verification/scenario_gate.py:862 形态）亦零误报 | pass | 0/2 | - |
| scan-serve-present-existing-rules-unchanged | serve 段存在时既有三条规则行为不变（tasks 3.1 第三句）：serve.cmd 入口缺失 + 与 package.json start script 不一致 + 无端口注入三 finding 全命中（rule_id: serve_entry_missing/serve_entry_vs_start_mismatch/serve_entry_no_port_injection）；规范 serve（{port} 注入、python3 -m 形态入口不可静态解析）时 findings 为空（出处 core/verify_engine/scenario_static_check.py:654-745 既有规则表） | pass | 0/2 | - |
| gate-helper-kind-aware-findings-written | 契约静态检查挂点 helper 行为面（task 1.2 各挂载路径共同漏斗）：对含 api 场景的 spec 产物执行 _run_contract_static_check 后 contract_findings.json 落盘且含 serve 缺失 finding；对全 cli 场景的 spec 不报 serve 缺失（出处 core/pm_engine/verification/scenario_gate.py:847、落盘路径 .fenix/verify-progress/<spec>/contract_findings.json） | pass | 0/2 | - |
| pipeline-mount-covers-frozen-parallel-paths | 挂载补全源码面（task 1.2）：pipeline.py 中契约静态检查（_run_contract_static_check/scan_contract）调用点不止新鲜出题验收路径（现 core/pm_engine/verification/pipeline.py:3059 单点）一处——冻结场景复用（_load_frozen_or_escalate 消费分支）与并行出题产物消费（_consume_parallel_plan_product 短路分支）路径的产物同样过检查 | pass | 0/2 | - |
| preprobe-capability-gap-not-satisfied | 前置探测收紧·能力缺口侧（task 2.1，spec.md Scenario「契约可解析但能力未补」）：P1 契约可解析但无 serve 段 + commands.start 为占位 echo + 在途场景含 api/web → _preprobe_signal_satisfied 判不满足（信号保持 open 不 auto-resolve）；P5 契约文件缺失（load 返回 None）→ 维持 False 既有行为（出处 core/admin_monitor.py:2949 _preprobe_signal_satisfied、OR 关系见 design D3） | pass | 0/2 | - |
| preprobe-capability-restored-satisfied | 前置探测收紧·能力补齐侧（task 2.1，spec.md Scenario「契约补齐后免唤起恢复」）：P2 契约补齐 serve 段（start 仍占位，验证 OR 关系而非 AND，design D3 实证形态） + 在途 api/web → 判满足；P3 无 serve + commands.start 非占位 + 在途全 cli → 判满足；P4 无 serve + start 非占位 + 在途含 api/web → 判满足（commands.start 兜底覆盖非 cli kind，出处 core/verify_contract.py:97 语义要点） | pass | 0/2 | - |
| existing-contract-preflight-regression | 既有行为回归门：契约静态检查/前置探测/并行车道的既有测试文件在本 SPEC 改动后全绿（tasks 1.1 既有三规则不回归、1.2 新鲜出题验收路径既有行为不回归、2.1 免唤起既有语义一致）——test_verify_preflight_gate.py（scan_contract 机制） + test_signal_preprobe_handled_writeback.py（前置探测闭环） + test_verify_contract_template_preflight.py（模板态前置检出） + test_verify_lane_throughput.py（并行出题产物消费） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

