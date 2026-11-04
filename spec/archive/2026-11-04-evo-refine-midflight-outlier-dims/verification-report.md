# 验证报告：evo-refine-midflight-outlier-dims

> ⚠️ 本报告由框架于 2026-10-31T17:12:32Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-31T17:12:31.111309+00:00+run-result@mtime1793466751158917779

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.11M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dilution-batch-window-shape-not-flagged | R1 正向：复刻 2026-10-17 两窗形态的批量 code-fix run（修 9 条、cost 3.401011、521.22 秒、turns 45）对单条目小 run 组（cost 中位 0.483、duration 中位 146.85），绝对口径下必标 7.05×/3.55×，按台账条目数摊薄后（0.378/条、57.9s/条）不标离群——摊薄口径实现点 core/self_review.py MIDFLIGHT_DILUTED_DIMS(:966) 与 _collect_metrics_outliers 摊薄分支(:1354-1371)，条目数来源 core/run_task_track.py parse_tasks_md len(all)(:163)，行为由 shipped 测试锁定。出处：tests/test_self_review_midflight.py:809 TestBatchLaneDilution::test_batch_run_not_flagged_after_dilution | pass | 0/2 | - |
| dilution-real-outlier-per-task-entry | R1 正向：摊薄后仍显著超基线的 run 依然标离群，且离群 entry 携带摊薄前后两对数字与分母（baseline_kind=per_task_median、value=15/条、median=1.05/条、raw_value=30.0、raw_median=1.05、task_count=2）——摘要行人工对账用键，实现点 core/self_review.py :1410-1423 判定与 :1465-1492 _outlier_dim_text 渲染。出处：tests/test_self_review_midflight.py:841 TestBatchLaneDilution::test_diluted_outlier_still_flagged_with_per_task_entry | pass | 0/2 | - |
| dilution-missing-entry-whole-dim-fallback | R1 异常路径：组内任一 run 条目数不可得（其 spec 无 tasks.md → parse_tasks_md 返回空 → _run_task_entry_count 为 None，core/self_review.py:1154-1175）→ cost_usd 维整组回退绝对口径（单一基线不混口径），大批 run 按 7.05× 绝对倍数标出且 entry 无 baseline_kind 注记（value=3.401011、median=组中位 0.4865）。出处：tests/test_self_review_midflight.py:878 TestBatchLaneDilution::test_missing_entry_count_whole_dim_falls_back_absolute | pass | 0/2 | - |
| dilution-single-entry-absolute-parity | R1 回归点：单条目 run 行为与现状一致（摊薄后等于原值，摊薄不改变单条目判定与呈现，仅基线标签注记为摊薄组中位）——保证归一改动对非批量小 run 零行为漂移。出处：tests/test_self_review_midflight.py:911 TestBatchLaneDilution::test_single_entry_run_behaves_as_absolute | pass | 0/2 | - |
| dilution-independent-e2e | R1 独立端到端验证（不经 shipped 测试，fresh 临时夹具项目直驱 _collect_metrics_outliers）：①两窗形态批量 run（修 9 条）摊薄后全组零离群；②摊薄 15/条 对组摊薄中位 1.05/条 的真离群仍标出且携带 per_task_median/raw_value/raw_median/task_count 全键、duration 维摊薄后不标；③组内任一 run spec 无 tasks.md 时 cost 维整维回退绝对口径（大批 run 以绝对值 3.401011 标出、无 baseline_kind）。实现出处：core/self_review.py:1354-1371（摊薄启用与整维回退）、:1410-1423（判定与 entry 键）。夹具为临时目录直写指标行，不经 Registry 探针注册，不产生 admin 告警面 | pass | 0/14 | - |
| text-turns-high-ratio-flagged | R2 正向：turns=204、text_turns=125（2026-10-17 窗形态，占比 61.3%）→ 标纯文本轮占比离群，entry 全键（baseline_kind=text_turn_ratio、value=125/204、median=0.5 占比阈值、text_turn_count=125、turns_count=204）——无 API 停滞的轮次通胀可观测。双条件判定实现点 core/self_review.py _text_turn_ratio_outlier(:1227-1250)，取数用 context metrics 行原始值 _read_context_metrics_row(:1186-1224)。出处：tests/test_self_review_midflight.py:1002 TestTextTurnRatioDim::test_high_turns_high_ratio_flags | pass | 0/2 | - |
| text-turns-baseline-shape-clear | R2 回归点：基线批形态 turns=104、text_turns=22（占比 21%）→ 不标——正常批不得因新维度误报（proposal 实测基线批 22/104=21%）。出处：tests/test_self_review_midflight.py:1018 TestTextTurnRatioDim::test_baseline_batch_shape_not_flagged | pass | 0/2 | - |
| text-turns-low-turns-guard | R2 异常路径（小 run 噪音防护）：低轮数高占比（4 轮中 3 轮纯文本，占比 75% 超阈值但 turns=4 ≤ 100）→ 不标——绝对轮数条件挡小 run 高占比噪音（design 取舍）。出处：tests/test_self_review_midflight.py:1027 TestTextTurnRatioDim::test_low_turns_high_ratio_not_flagged | pass | 0/2 | - |
| text-turns-ratio-boundary-strict | R2 边界：占比恰等于阈值（200 轮中 100 轮纯文本，恰 50%）不标；严格超阈值（101/200）才标——双条件均为严格大于。出处：tests/test_self_review_midflight.py:1036 TestTextTurnRatioDim::test_ratio_boundary_strictly_above | pass | 0/2 | - |
| text-turns-missing-field-skip | R2 异常路径（缺样不入组）：context metrics 行缺 text_turns 字段（dsh 通道/历史行形态）→ 该 run 该维跳过，不产假离群（_read_context_metrics_row 两字段须同一条行且均为数值，任一缺失返回 None）。出处：tests/test_self_review_midflight.py:1051 TestTextTurnRatioDim::test_missing_text_turns_field_skipped | pass | 0/2 | - |
| text-turns-threshold-constants | R2 阈值常量收口断言：MIDFLIGHT_TEXT_TURNS_MIN_TURNS=100、MIDFLIGHT_TEXT_TURNS_RATIO_THRESHOLD=0.5（与 MIDFLIGHT_OUTLIER_* 同处 core/self_review.py:974-975 常量区收口），且摊薄维清单 MIDFLIGHT_DILUTED_DIMS=[cost_usd,duration_seconds]（:966）、判定倍数 MIDFLIGHT_OUTLIER_MULTIPLIER=3（:940）——阈值漂移即离群口径漂移，常量直查锁定 | pass | 0/6 | - |
| text-turns-independent-e2e | R2 独立端到端验证（不经 shipped 测试，fresh 临时夹具项目直驱）：①turns=204/text_turns=125 标出且 entry 全键与占比精确吻合；②基线批 104/22 不标；③4 轮中3 轮纯文本不标；④恰等阈值（100/200）不标；⑤行缺 text_turns 字段跳过；⑥空窗口返回空清单不抛（空状态）；⑦指标行 model 原值原样附着离群记录（R3 联动）。实现出处：core/self_review.py:1424-1429（text_turns 维挂接）、:1438-1442（model 附带） | pass | 0/13 | - |
| model-context-metrics-rows-carry-model | R3 正向：run 收尾的 context metrics 两行均落实际 --model 值——转录行 （type=run_metrics，core/agent_runner/runner.py:7616）与日志侧行（metric_type=run_metrics，:7664）原样记录不归一。出处：tests/test_self_review_midflight.py:1172 TestRunMetricsModelField::test_context_metrics_rows_carry_model | pass | 0/2 | - |
| model-terminal-row-writes-model | R3 正向：终态 _log_run_metrics 接通既有休眠形参 model（core/agent_runner/runner.py:9741 定义、:9824 落 metric_ctx）——有值原样落行、None（未观测）也恒落键保持行形态稳定。出处：tests/test_self_review_midflight.py:1199 TestRunMetricsModelField::test_terminal_log_run_metrics_writes_model | pass | 0/2 | - |
| model-terminal-row-independent-e2e | R3 独立端到端验证（不经 shipped 测试）：最小 AgentRunner 直驱真实 Logger 落盘 _log_run_metrics——带 model 调用原样记录（deepseek-v4-flash）、model=None 调用model 键仍在（未观测语义恒落键）、terminal/agent_type 字段不受改动影响，逐行解析 .fenix/logs/fenixd.log 的 metric_type=run_metrics 行核对。实现出处：core/agent_runner/runner.py:9805-9830 | pass | 0/6 | - |
| midflight-summary-rendering | 摘要渲染回归（tasks 1.1 摘要行 + 1.2 渲染 + 2.2）：第六节自省摘要在有 model 时行头附带 model=<值>，摊薄行同时给摊薄前后两对数字（cost_usd=15/条（摊薄组中位 1.05/条，分母 2；原值 30.0 对 组中位 1.05，成功收尾）），纯文本轮行给计数形态（text_turns=125/204（占比 61.3%，阈值 turns>100 且占比>50%，成功收尾））。实现出处：core/self_review.py _outlier_dim_text(:1465-1492) 与第六节渲染。出处：tests/test_self_review_midflight.py:942 test_diluted_and_model_rendered_in_summary、:1060 test_text_ratio_and_model_rendered_in_summary | pass | 0/3 | - |
| midflight-suite-full-regression | 全量回归：tests/test_self_review_midflight.py 45 用例全绿（含存量中途信号采集、车道分组 P90 基线、救回痕迹归集、第六节渲染等未被单点场景覆盖的回归面）——改动面（core/self_review.py、core/agent_runner/runner.py）回归零破坏。以 -q 安静档运行并以「45 passed」摘要行仲裁（不与 -v 并列） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景

