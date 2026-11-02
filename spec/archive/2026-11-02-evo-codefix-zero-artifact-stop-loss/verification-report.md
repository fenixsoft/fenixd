# 验证报告：evo-codefix-zero-artifact-stop-loss

> ⚠️ 本报告由框架于 2026-10-30T13:04:55Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T13:04:54.329323+00:00+run-result@mtime1793365494379058568

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.07M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| breaker-envelope-category-tests | 结构化失败类别透出（SPEC Requirement 1）：运行交付的信封单测组 TestEnvelopeFailureCategory，验证硬门零产物失败信封携带 failure_category=artifact_missing 且 conn_error=False、非硬门失败（api_error/异常路径）failure_category 保持缺省空串、CodeFixResult 新字段带缺省值（未走硬门构造点零触碰）。命令：python3 -m pytest tests/test_codefix_zero_artifact_breaker.py::TestEnvelopeFailureCategory -v --tb=short（交付物 tests/test_codefix_zero_artifact_breaker.py:117-173，硬门置类别 core/agent_runner/maintenance_runs.py:3810-3823，字段定义 core/agent_runner/result_gate.py:489） | pass | 0/4 | - |
| dispatch-contract-template-anchor | 契约模板字面锚定独立复核（回归点）：不经交付测试文件、直接以 grep 对 agents/code-fix.md 做三个字面子串存在性检查（回合结束 = run 终止 / run_in_background: false / MUST NOT 以「等待完成通知」），与场景 breaker-dispatch-contract-test 互为双保险——交付测试被误删或被改弱时本场景仍可独立暴露模板漂移（agents/code-fix.md:52-56 实文取证） | pass | 0/2 | - |
| stoploss-state-machine-probe | 止损状态机独立探针（超出交付测试的独立复核）：不经测试夹具、直接构造 CodeFixOrchestrator 实例驱动 _record_artifact_missing_failure/_stop_loss_item_ids——阈值常量 ARTIFACT_MISSING_BREAKER_THRESHOLD==2；空指纹不计数（空输入异常路径）；单次失败仅计数（跳过集空、无 WARNING）；同指纹第 2 次失败触发止损（跳过集入集、恰发一条 WARNING 且文案含「零产物止损」「连续 2 次」、指纹条目与最后失败 run id）；_stop_loss_item_ids 展开为条目 id 集供选批排除；其他指纹不受止损影响；api_timeout/空类别/conn_error 均不计入（core/code_fix.py:1191-1199 常量、4041-4077 状态机、4027-4039 展开） | pass | 0/2 | - |
| artifact-gate-envelope-probe | 产物硬门与信封缺省值独立探针：直接调 CodeFixResult 与 _check_code_fix_artifact 验证——信封缺省构造 failure_category==空串且 conn_error/api_timeout/exit_code 既有缺省逐位不变；带 failure_category=artifact_missing 构造成功；硬门 fail-closed 判定矩阵：out 文件缺失→「产物缺失」文案、零字节文件→「零有效行」、全无效行（非 JSON/缺 item_id/非法 status）→「零有效行」、有效 fixed/skipped 行→门通过返回 None、空清单→不判定返回 None（core/agent_runner/result_gate.py:476-502 构造器、core/agent_runner/maintenance_runs.py:3530-3580 硬门判据） | pass | 0/2 | - |
| breaker-stoploss-state-machine-tests | 同指纹零产物止损状态机（SPEC Requirement 2 四场景）：运行交付的止损单测组 TestArtifactMissingBreaker——单次失败仍瞬态重试（chain_skipped 语义逐位不变）、同指纹连败 2 次止损（指纹入跳过集+恰一条 WARNING 留痕）、其他失败类别不计数、止损不影响其余指纹、止损跳过集展开并入选批排除并集。命令：python3 -m pytest tests/test_codefix_zero_artifact_breaker.py::TestArtifactMissingBreaker -v --tb=short（交付物 tests/test_codefix_zero_artifact_breaker.py:175-301，状态机 core/code_fix.py:4041-4077，选批并集 core/code_fix.py:4978-4991） | pass | 0/6 | - |
| breaker-dispatch-contract-test | 派发契约测试（SPEC Requirement 3）：运行交付的契约单测组 TestCodeFixDispatchContract，按字面子串断言 agents/code-fix.md 含同步派发契约条款「回合结束 = run 终止」「run_in_background: false」「MUST NOT 以「等待完成通知」」——模板漂移删除/改写任一子串即测试失败。命令：python3 -m pytest tests/test_codefix_zero_artifact_breaker.py::TestCodeFixDispatchContract -v --tb=short（交付物 tests/test_codefix_zero_artifact_breaker.py:302-322，契约实文 agents/code-fix.md:48-56） | pass | 0/2 | - |
| existing-codefix-suite-regression | 既有 code-fix 链路测试回归点：止损改动落点在 core/code_fix.py 首轮 run 失败收尾块与选批排除并集，须保证既有链路测试（含 chain_skipped 瞬态重试、失败档案、选批、合回核销等 125 项）零回归。命令：python3 -m pytest tests/test_code_fix.py -q（该文件同时是交付测试 tests/test_codefix_zero_artifact_breaker.py:25-33 的夹具来源 _FakeRunner/_make_project_root 等） | pass | 0/2 | - |
