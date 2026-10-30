# 验证报告：evo-review-empty-product-redispatch

> ⚠️ 本报告由框架于 2026-10-30T12:45:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T12:43:07.093013+00:00+run-result@mtime1793364343431927796

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 6/12 场景通过，6 失败，0 错误（5 个真实产品 Bug）**

12 场景：6 PASS / 6 FAIL，6 个非 PASS 均判 product-bug（failed），无 test-defect/flaky/env。失败集中于 repo-code-review 零产物重派链的五处产品缺口：①信封缺结构化失败面；②缺失变体与零有效行变体失败面同文；③重派仍失败不发 admin 升级信号（2 场景同根因，系统性）；④error 收场结论行抢救缺失；⑤run_metrics 工具面字段未接线（收尾行未落盘）。派发计数、锁存、完成行失败面、空 manifest 跳过、双通道互斥、提示词自救段等既有语义均验证通过。证据全部引自 probe 确定性输出（exit 0、observed_parallel=1），免复现。

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 6 |
| 错误 | 0 |
| 产品 Bug | 5 |
| 本链增量 Token（输入） | 0.40M |
| 本链增量 Token（输出） | 0.12M |


## 真实产品 Bug

### BUG-01（severity=major）· json_output

- 关联场景：cr-gate-zero-valid-fail-face
- 描述：repo-code-review 硬门零有效行拦截时，结果信封未在 error 文案之外携带独立的结构化失败面摘要（run id、manifest 计数、零有效行变体），只有人类可读文案，无法机器消费
- 根因：core/agent_runner/result_gate.py 拦截分支（_check_repo_code_review_artifact）与 maintenance_runs gate_err 分支只组装 error 文案，未在信封上落结构化失败面字段
- 证据（场景 cr-gate-zero-valid-fail-face 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "selector": "probe.pass", "expected": true, "actual": false}, {"type": "json_output", "selector": "probe.structured_fail_face", "expected": true, "actual": false}]
  - screenshots: []
  - first_failed_step: 步骤2 probe：零有效行拦截时信封仅有 error 文案（run code-review-179100000 manifest 2 个文件文案齐备），但 structured_fail_face=false，无独立于文案的机器可消费结构化失败面

### BUG-02（severity=major）· json_output

- 关联场景：cr-gate-missing-variant-distinct
- 描述：硬门失败面变体不可区分：产物缺失变体未标注「缺失」，与零有效行变体文案同文（剔除 run id 后逐字相同）；读取失败变体已正确标注，唯缺失形态未区分
- 根因：result_gate 对「manifest 声明但文件不存在」形态复用零有效行文案路径，未按 design.md 缺失/零行/读取失败三形态分别组装失败面
- 证据（场景 cr-gate-missing-variant-distinct 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "selector": "probe.pass", "expected": true, "actual": false}, {"type": "json_output", "selector": "probe.missing_variant_marked", "expected": true, "actual": false}, {"type": "json_output", "selector": "probe.variants_distinct", "expected": true, "actual": false}]
  - screenshots: []
  - first_failed_step: 步骤2 probe：产物缺失变体（out-code-review-179200000.jsonl 不存在）与零有效行变体文案同文，仅 run id 不同；剔除 run id 后失败面不可区分，missing 未标注「缺失」

### BUG-03（severity=major）· json_output

- 关联场景：cr-redispatch-still-zero-escalate、cr-escalation-latches-redispatch
- 描述：系统性问题：重派仍零有效行后 admin 升级信号通道未接线——.fenix/admin_alerts.json 无携带 run id+manifest 计数+零有效行变体的记录；升级后两通道全停语义因前置信号缺失无法完整成立（重派计数恒 2/3 与完成行失败面本身正确）
- 根因：core/admin_monitor.py 审查检查点重派失败分支未调用 AdminStore 写升级记录，重派链终止但升级路径静默缺失
- 证据（场景 cr-redispatch-still-zero-escalate 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "selector": "probe.pass", "expected": true, "actual": false}, {"type": "json_output", "selector": "probe.escalation_present", "expected": true, "actual": false}]
  - screenshots: []
  - first_failed_step: 步骤2 probe：链 1 两次派发均零有效行（179600000/179600001）后，.fenix/admin_alerts.json 匹配升级记录 0 条，升级信号未发出；派发数恒 2 与完成行失败面均正确

### BUG-04（severity=major）· json_output

- 关联场景：cr-error-wrapup-conclusion-rescue
- 描述：审查 run 429 error 收场时，终局消息中的结论行未被抢救留痕（日志与 .fenix 落盘均无 MARKER 命中，转录本体除外）；全仓快照核销与 code-fix 激活两条红线守住
- 根因：core/agent_runner/maintenance_runs.py error 收场抢救段未实现结论行提取落盘，标记行随转录丢弃
- 证据（场景 cr-error-wrapup-conclusion-rescue 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "selector": "probe.pass", "expected": true, "actual": false}, {"type": "json_output", "selector": "probe.conclusion_salvaged", "expected": true, "actual": false}]
  - screenshots: []
  - first_failed_step: 步骤2 probe：run 以 429 error 收场后，终局消息结论行 REVIEW-CONCLUSION-MARKER-9d27 日志命中=False、.fenix 文件命中=[]，抢救留痕未发生；两条红线（不核销 open 条目、不激活 code-fix）均守住

### BUG-05（severity=major）· json_output

- 关联场景：cr-run-metrics-toolface-fields
- 描述：run_metrics 工具面留痕未落地：真实 _log_run_metrics 收尾行（metric_type=run_metrics）未落盘，预检结果/TOOLFACE-MISSING 分类等工具面字段无从记录；runner.py 源码已有工具面/预检标记与失败面接线，但未接到 metrics 收尾输出
- 根因：core/agent_runner/runner.py 工具面预检写点与 _log_run_metrics 收尾行之间接线缺失，被测路径不产生 run_metrics 记录
- 证据（场景 cr-run-metrics-toolface-fields 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "selector": "probe.pass", "expected": true, "actual": false}, {"type": "json_output", "selector": "probe.metrics_toolface_present", "expected": true, "actual": false}, {"type": "output_match", "selector": "combined contains 'metric keys:'", "expected": "metric keys:", "actual": "probe stdout 未输出 metric keys 行"}]
  - screenshots: []
  - first_failed_step: 步骤2 probe：真实 _log_run_metrics 收尾行未落盘（metric_type=run_metrics 缺失），toolface 字段无从谈起；runner.py 源码含工具面/预检标记（runner_precheck_marker=true）但运行时未接线到 metrics 行


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cr-gate-zero-valid-fail-face | 硬门零有效行拦截失败面：审查 run 产物为零有效行时，结果信封在 error 文案之外携带可机器消费的结构化失败面摘要（run id、manifest 计数、零有效行变体）（出处 core/agent_runner/result_gate.py:1141 _check_repo_code_review_artifact、core/agent_runner/maintenance_runs.py:2291 gate_err 分支、design.md 变体透出条款） | failed（已修正） | 2/5 | product-bug |
| cr-gate-missing-variant-distinct | 硬门变体可区分：产物缺失/零有效行/读取失败三形态的失败面互异且均点名 run id 与 manifest 计数，缺失变体带「缺失」标注（出处 spec repo-code-review-chain「拦截失败面外露」Requirement、core/agent_runner/result_gate.py:1216-1231、design.md unreadable 名单 vs 纯零行文案） | failed（已修正） | 3/6 | product-bug |
| cr-gate-empty-manifest-passes | 回归：空 manifest、主产物有效行、仅分片有效行（聚合口径）均放行；垃圾行仍拦（防写满垃圾行骗门）（出处 core/agent_runner/result_gate.py:1141 判据、tests/test_code_review.py:1213 TestRepoCodeReviewArtifactGate 同口径） | pass | 0/6 | - |
| cr-redispatch-first-zero-product | 首次零产物自动重派：周期审查 run 硬门拦截后自动重派恰 1 次并在 admin_monitor 日志记录重派事件；重派产物有效则成功收场、不发升级告警；完成行携带首次 run 失败面（出处 core/admin_monitor.py:1758 _run_code_review_checkpoint、spec「首次零产物自动重派」Scenario） | pass | 0/8 | - |
| cr-redispatch-still-zero-escalate | 重派仍零有效行：经既有 admin 升级记录通道发升级信号（.fenix/admin_alerts.json 记录携带 run id/manifest 计数/零有效行变体），且不再自动重派（派发总数恒 2）；完成行携带失败面（出处 spec「重派仍失败升级信号」「完成行携带失败面」Scenario、core/admin_store.py:246 AdminStore） | failed（已修正） | 2/6 | product-bug |
| cr-clean-run-no-redispatch | 回归：硬门通过（产物含有效结果行）的审查 run 恰派发 1 次，不触发零产物重派、不留重派事件、不发升级告警（出处 core/admin_monitor.py:1758 检查点守卫语义） | pass | 0/6 | - |
| cr-empty-manifest-no-dispatch | 空状态：窗口内无变更文件（manifest 空）时按 no_files 跳过，零派发、零重派、零升级告警（出处 core/admin_monitor.py:1859 空 manifest 分支、design Risk「空场景白洗」） | pass | 0/6 | - |
| cr-channel-mutex-no-double-dispatch | 双通道互斥：零产物通道已对同一 run 链重派后，重派 run 的 429 限流重派意图不再叠加调度（派发总数恒 2，含 300s 冷却窗观察期）（出处 design.md 双通道重派配额约束、core/admin_monitor.py:2177 _schedule_ratelimit_redispatch） | pass | 0/4 | - |
| cr-escalation-latches-redispatch | 升级后全停：admin 升级信号发出后，新 run 链（重置同日防重）再遭硬门拦截时两通道均不再自动重派（链 2 恰派发 1 次、总派发恒 3）（出处 design.md「升级信号发出后两通道均不再自动重派」） | failed（已修正） | 2/6 | product-bug |
| cr-prompt-tool-selfrescue-section | 审查提示词自救指引段：agents/code-review.md 预注工具自救纪律三要素（基础工具直调 / select: 精确名探测 / TOOLFACE-MISSING fail-fast）+「No matches 属按设计」+ 禁止凭检索空推断工具缺失并放弃；code-review 车道渲染链路携带该段、模板映射不漂移（出处 core/agent_runner/prompt_builder.py:67 AGENT_PROMPT_FILES、tasks.md 2.1、spec「提示词含自救指引」） | pass | 0/6 | - |
| cr-error-wrapup-conclusion-rescue | error 收场抢救终局结论行：审查 run error 收场（429 中途死亡）时，终局消息中的结论行被抢救留痕（日志或 .fenix 落盘，转录本体除外）；红线：不触发全仓快照核销（预置 open 条目保持 open、无 resolved_at）、不激活 code-fix 检查点（出处 core/agent_runner/maintenance_runs.py:2491 error 收场抢救段、tasks.md 5.1、spec「error 收场抢救终局结论行」） | failed（已修正） | 2/6 | product-bug |
| cr-run-metrics-toolface-fields | run_metrics 工具面留痕：真实 _log_run_metrics 收尾行在既有回归字段（run_id/terminal/agent_type）之外携带工具面字段（预检结果/TOOLFACE-MISSING 分类等）；runner.py 存在 spawn 后写工具面预检落点，失败面/车道收尾消费工具面预检结果（出处 core/agent_runner/runner.py:9132 _log_run_metrics、tasks.md 4.1/6.1、spec「工具面预检留痕」） | failed（已修正） | 3/6 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

场景集与持久化集一致，无变更。

