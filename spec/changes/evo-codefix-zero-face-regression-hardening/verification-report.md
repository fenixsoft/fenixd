# 验证报告：evo-codefix-zero-face-regression-hardening

> ⚠️ 本报告由框架于 2026-10-08T17:51:29Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-08T17:51:28.261729+00:00+run-result@mtime1791481888290903716

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.78M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| anomaly-judge-matrix | 回归异常判据矩阵（SPEC 1.1）：_is_regression_anomaly 对「timeout 且无可用失败用例明细」必须判定为异常（修复前恒 False，2026-10-08 三批 6 轮 timeout 全部绕过计数器的根因），而 timeout 携带可用明细、passed、以及既有 parse_error/failed 无明细/failed 有明细各形态判定不回归；同时验证分形态熔断阈值查表 _anomaly_breaker_threshold（timeout=1、parse_error/failed=2，1.2 单源）。探针以 SimpleNamespace 直接调判据函数与阈值函数，stdout 输出一行 JSON 判定矩阵。出处 core/code_fix.py:1139-1152、:1120-1136 | pass | 0/10 | - |
| timeout-first-record-stop-wiring | timeout 零失败面首记即收口的批 worker 接线（SPEC 1.2）：首轮全量回归计数点（core/code_fix.py:5773 if attempt == 1 分支）必须在派发定向 run（:5800 _preset_run_id）之前具备短路终止接线——阈值达标时显式置 breaker_triggered/exhausted 再 break（for-else 语义），过时注释「无需在此短路」同步移除；timeout 首记阈值常量 ANOMALY_BREAKER_TIMEOUT_THRESHOLD=1、parse_error/failed 既有常量 REGRESSION_ANOMALY_BREAKER_THRESHOLD=2 均不回归。行为面由 anomaly-budget-unit-tests-green 场景（任务 2.1 单测）闭环。出处 core/code_fix.py:5765-5800、:1113-1136 | pass | 0/8 | - |
| anomaly-budget-unit-tests-green | 任务 2.1 单测验收：tests/test_codefix_anomaly_redispatch_budget.py 扩展后须全绿（基线 6 用例，扩展后 12 用例），新覆盖 timeout-无明细判 anomaly（test_timeout_zero_face_judged_anomaly）、分形态阈值查表（test_breaker_threshold_per_form）、timeout 首记即收口不派定向 run（test_timeout_first_hit_stops_batch_without_targeted_run）、定向轮 timeout 立即 break（test_timeout_in_targeted_round_breaks_immediately）、parse_error/failed 阈值仍为 2（test_parse_error_threshold_stays_two/test_failed_zero_detail_threshold_stays_two），且 reg_form 分档与一次性降档告警既有用例不回归。出处 spec/changes/evo-codefix-zero-face-regression-hardening/tasks.md 任务 2.1 | pass | 0/5 | - |
| detail-file-retains-long-tests | 明细档留存慢测试进度（SPEC 1.3 正向路径）：回归快照含 long_tests（timeout/total=0 形态，items 映射不出、fallback_full=true）时，_ingest_failure_round 须把 long_tests 规整（{name,time}，字段缺失条目跳过）透传进 write_fix_reg_failures 明细档新增可选键，保留用例名+耗时与 source_run_id，使 worktree 清理（_safe_cleanup 物理销毁快照与 junit.xml.log）后毒化源仍可定位——2026-10-08 事故定位全靠根治提交事后自述的实证缺口。出处 core/code_fix.py:1040-1082、:1085-1110、:850-888 | pass | 0/7 | - |
| detail-file-tolerates-missing-long-tests | 明细档字段缺失容错（SPEC 1.3 异常路径）：旧快照无 long_tests 键、以及 long_tests 形态畸形（非列表字符串）时，_ingest_failure_round/write_fix_reg_failures 不报错，明细档保持现形态（items/source_run_id/created_at/fallback_full 完整、fallback_full=true），向后兼容不破坏旧消费方（证据不在场不写空键）。出处 core/code_fix.py:1056-1082（容错归约）、:868-877（可选键仅在证据在场时写入） | pass | 0/5 | - |
| detail-file-junit-log-tail-fallback | 明细档次选证据源（SPEC 1.3）：快照 long_tests 缺失时，_collect_reg_progress_evidence 须以 junit.xml.log 尾段（逐用例进度日志，路径由快照 output 相对 exec_root 推导、XML 同名 + .log，取尾部 REG_PROGRESS_LOG_TAIL_BYTES=8192 窗口）作为次选证据，write_fix_reg_failures 以 progress_log_tail 可选键并入明细档——worktree 清理前落盘，清理后仍可回收。探针在临时 exec_root 植入含唯一标记的 junit.xml.log，断言标记出现在明细档文本中。出处 core/code_fix.py:1069-1081、:1033-1036、core/regression.py:818-873 | pass | 0/3 | - |
| detail-file-items-consumers-unaffected | 既有消费方不受新增可选键影响（SPEC 1.3 回归点）：可映射失败明细（classname 主导 nodeid 重构）与 long_tests 并存时，_ingest_failure_round 返回 mapped=true 与正确 nodeid（tests/test_probe_mod.py::test_a），明细档 items/fallback_full 既有键语义不变（定向重试按 items 注入子集），long_tests 作为新增键与其共存。探针在临时 exec_root 落真实模块文件以满足模块边界在盘判定。出处 core/code_fix.py:891-910（classname 主导重构）、:1095-1110（并存透传） | pass | 0/6 | - |
| verify-yaml-timeout-margin-review | 复核项（proposal 随本 spec 核实、design 决策 4「1800 秒墙钟不调」）：.fenix/verify.yaml 回归 timeout_seconds 必须维持 1800 不被顺手调参；余量结论按修后基线 8077 用例/449.59 秒（.fenix/regression/last-run.json，2026-10-09 00:11）约为 4 倍（≥2 倍即安全），结论由本场景输出留档供 verification 记录，同时确保实现未借机改动墙钟配置。出处 .fenix/verify.yaml:116 | pass | 0/4 | - |
| code-fix-test-suite-green | 任务 2.2 单测验收与回归安全网：tests/test_code_fix.py 扩展（TestRegressionProgressEvidence：test_detail_includes_long_tests_name_and_time/test_missing_long_tests_falls_back_to_junit_log_tail/test_no_evidence_keeps_current_shape/test_malformed_long_tests_entries_tolerated/test_mapped_round_keeps_items_semantics_alongside_new_key）后须全绿——该文件 125 用例是 _map_junit_failures_to_nodeids/write_fix_reg_failures/_ingest_failure_round 等被改路径的既有回归安全网，扩展与改动不得打破任何既有用例。出处 spec/changes/evo-codefix-zero-face-regression-hardening/tasks.md 任务 2.2 | pass | 0/5 | - |
