# 验证报告：evo-review-empty-product-redispatch

> ⚠️ 本报告由框架于 2026-10-30T14:00:34Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T14:00:32.925073+00:00+run-result@mtime1793368832988259141

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.40M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cr-gate-zero-valid-fail-face | 硬门零有效行拦截失败面：审查 run 产物为零有效行时，结果信封在 error 文案之外携带可机器消费的结构化失败面摘要（run id、manifest 计数、零有效行变体）（出处 core/agent_runner/result_gate.py:1141 _check_repo_code_review_artifact、core/agent_runner/maintenance_runs.py:2291 gate_err 分支、design.md 变体透出条款） | pass | 0/5 | - |
| cr-gate-missing-variant-distinct | 硬门变体可区分：产物缺失/零有效行/读取失败三形态的失败面互异且均点名 run id 与 manifest 计数，缺失变体带「缺失」标注（出处 spec repo-code-review-chain「拦截失败面外露」Requirement、core/agent_runner/result_gate.py:1216-1231、design.md unreadable 名单 vs 纯零行文案） | pass | 0/6 | - |
| cr-gate-empty-manifest-passes | 回归：空 manifest、主产物有效行、仅分片有效行（聚合口径）均放行；垃圾行仍拦（防写满垃圾行骗门）（出处 core/agent_runner/result_gate.py:1141 判据、tests/test_code_review.py:1213 TestRepoCodeReviewArtifactGate 同口径） | pass | 0/6 | - |
| cr-redispatch-first-zero-product | 首次零产物自动重派：周期审查 run 硬门拦截后自动重派恰 1 次并在 admin_monitor 日志记录重派事件；重派产物有效则成功收场、不发升级告警；完成行携带首次 run 失败面（出处 core/admin_monitor.py:1758 _run_code_review_checkpoint、spec「首次零产物自动重派」Scenario） | pass | 0/8 | - |
| cr-redispatch-still-zero-escalate | 重派仍零有效行：经既有 admin 升级记录通道发升级信号（.fenix/admin_alerts.json 记录携带 run id/manifest 计数/零有效行变体），且不再自动重派（派发总数恒 2）；完成行携带失败面（出处 spec「重派仍失败升级信号」「完成行携带失败面」Scenario、core/admin_store.py:246 AdminStore） | pass | 0/6 | - |
| cr-clean-run-no-redispatch | 回归：硬门通过（产物含有效结果行）的审查 run 恰派发 1 次，不触发零产物重派、不留重派事件、不发升级告警（出处 core/admin_monitor.py:1758 检查点守卫语义） | pass | 0/6 | - |
| cr-empty-manifest-no-dispatch | 空状态：窗口内无变更文件（manifest 空）时按 no_files 跳过，零派发、零重派、零升级告警（出处 core/admin_monitor.py:1859 空 manifest 分支、design Risk「空场景白洗」） | pass | 0/6 | - |
| cr-channel-mutex-no-double-dispatch | 双通道互斥：零产物通道已对同一 run 链重派后，重派 run 的 429 限流重派意图不再叠加调度（派发总数恒 2，含 300s 冷却窗观察期）（出处 design.md 双通道重派配额约束、core/admin_monitor.py:2177 _schedule_ratelimit_redispatch） | pass | 0/4 | - |
| cr-escalation-latches-redispatch | 升级后全停：admin 升级信号发出后，新 run 链（重置同日防重）再遭硬门拦截时两通道均不再自动重派（链 2 恰派发 1 次、总派发恒 3）（出处 design.md「升级信号发出后两通道均不再自动重派」） | pass | 0/6 | - |
| cr-prompt-tool-selfrescue-section | 审查提示词自救指引段：agents/code-review.md 预注工具自救纪律三要素（基础工具直调 / select: 精确名探测 / TOOLFACE-MISSING fail-fast）+「No matches 属按设计」+ 禁止凭检索空推断工具缺失并放弃；code-review 车道渲染链路携带该段、模板映射不漂移（出处 core/agent_runner/prompt_builder.py:67 AGENT_PROMPT_FILES、tasks.md 2.1、spec「提示词含自救指引」） | pass | 0/6 | - |
| cr-error-wrapup-conclusion-rescue | error 收场抢救终局结论行：审查 run error 收场（429 中途死亡）时，终局消息中的结论行被抢救留痕（日志或 .fenix 落盘，转录本体除外）；红线：不触发全仓快照核销（预置 open 条目保持 open、无 resolved_at）、不激活 code-fix 检查点（出处 core/agent_runner/maintenance_runs.py:2491 error 收场抢救段、tasks.md 5.1、spec「error 收场抢救终局结论行」） | pass | 0/6 | - |
| cr-run-metrics-toolface-fields | run_metrics 工具面留痕：真实 _log_run_metrics 收尾行在既有回归字段（run_id/terminal/agent_type）之外携带工具面字段（预检结果/TOOLFACE-MISSING 分类等）；runner.py 存在 spawn 后写工具面预检落点，失败面/车道收尾消费工具面预检结果（出处 core/agent_runner/runner.py:9132 _log_run_metrics、tasks.md 4.1/6.1、spec「工具面预检留痕」） | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

