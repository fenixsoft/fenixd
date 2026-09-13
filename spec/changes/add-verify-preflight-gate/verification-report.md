# 验证报告：add-verify-preflight-gate

> ⚠️ 本报告由框架于 2026-09-11T12:55:58Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.32M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| preflight-resolve-entry-forms | D1 resolve_entry_path 脚本型运行时命令解析：node+单脚本→Path、deno run→Path、bun run/script→None、复合命令→None、非node→None、引号不配对→None。纯函数零IO，六种典型形态一轮验证。出处：core/verify_contract.py:888-930 | pass | 0/7 | - |
| preflight-entry-missing-with-candidates | D1 entry_preflight_error 入口不存在→错误含路径全文+同名目录index.js候选+同目录*.js候选。候选提示源自 _entry_candidates（D1同源），add-web-ui事故修复路径。出处：core/verify_contract.py:933-978 | pass | 0/6 | - |
| preflight-entry-exists-pass | D1 entry_preflight_error 入口存在→返回None放行，预检零开销。出处：core/verify_contract.py:969-970 | pass | 0/3 | - |
| preflight-selfcheck-static-valid-passes | D2 selfcheck_contract_light 合法static契约（root存在）→返回None+写入contract_selfcheck.json快照（含mtime_ns）。出处：core/verify_contract.py:986-1078 | pass | 0/4 | - |
| preflight-selfcheck-snapshot-hit-zero-overhead | D2 selfcheck_contract_light mtime快照门：契约未变（mtime_ns一致）→第二轮读快照即放行，零开销（serve段不重检）。出处：core/verify_contract.py:1016-1022 | pass | 0/3 | - |
| preflight-selfcheck-static-root-missing | D2 selfcheck_contract_light serve.kind=static但root指向不存在目录→返回错误串含'serve.root 不存在'，不写快照（下轮自动重证）。出处：core/verify_contract.py:1051-1057 | pass | 0/4 | - |
| preflight-selfcheck-mtime-change-retrigger | D2 selfcheck_contract_light 契约mtime变化后首验轮重触发：首次通过写快照→修改为非法契约(mtime变化)→重新自证失败且快照mtime不变（失败不覆写），确保下轮仍能重证。出处：core/verify_contract.py:1016-1078 | pass | 0/4 | - |
| preflight-selfcheck-command-empty-cmd | D2 selfcheck_contract_light serve.kind=command但cmd为空串→返回错误串含'cmd 为空'。出处：core/verify_contract.py:1058-1060 | pass | 0/3 | - |
| preflight-selfcheck-no-contract-pass | D2 selfcheck_contract_light 无verify.yaml契约→返回None跳过自证，不阻断。出处：core/verify_contract.py:1009-1010 | pass | 0/2 | - |
| preflight-bootlog-capture-and-tail | D3 boot.log证据捕获：验证spec的boot.log落盘至.fenix/verify-serving/<spec>-boot.log，_read_boot_log_tail读取尾部≤2KB含启动即死错误原文（Cannot find module）。出处：core/pm_engine/verification.py:982-1017 | pass | 0/4 | - |
| preflight-scan-contract-entry-missing | D4 scan_contract serve_entry_missing规则：serve.cmd入口不存在→findings含rule_id=serve_entry_missing/severity=high/evidence含候选提示。出处：core/verify_engine/scenario_static_check.py:458-472 | pass | 0/4 | - |
| preflight-scan-contract-vs-start-mismatch | D4 scan_contract serve_entry_vs_start_mismatch规则：serve.cmd入口≠package.json start入口→findings含rule_id=serve_entry_vs_start_mismatch/severity=info。出处：core/verify_engine/scenario_static_check.py:473-489 | pass | 0/4 | - |
| preflight-scan-contract-healthy-empty | D4 scan_contract 契约正确（入口存在+start一致+{port}注入）→返回空findings数组。出处：core/verify_engine/scenario_static_check.py:430-510 | pass | 0/3 | - |
| preflight-write-findings-overwrite | D4 write_contract_findings 覆盖写contract_findings.json：首次写入N条→再次写入空数组→文件内容为空数组（覆盖而非追加）。出处：core/verify_engine/scenario_static_check.py:513-534 | pass | 0/4 | - |
| preflight-prompt-injection-with-findings | D4 _contract_findings_section admin处置prompt注入：contract_findings.json含serve_entry_missing→渲染情报段含'契约静态检查情报'/'机械检出'/'修正契约是你的职责'。出处：core/agent_runner/prompt_builder.py:293-324 | pass | 0/6 | - |
| preflight-prompt-injection-missing-zero | D4 _contract_findings_section 无findings文件→返回空串，admin prompt与现状逐字节一致（零注入）。出处：core/agent_runner/prompt_builder.py:306-313 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

