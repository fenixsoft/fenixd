# 验证报告：evo-review-night-window-resume-hardening

> ⚠️ 本报告由框架于 2026-10-30T13:00:36Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T13:00:35.374742+00:00+run-result@mtime1793365235429888076

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.18M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| night-defer-suite-max-estimator-green | 回归：顺延守卫测试套件全绿（估计器均值改 max 后既有断言同步修正）——跑 tests/test_code_review_night_defer.py 全量 16 例，钉住 test_max_not_mean_upward_trend_defers（10893/12500/5338 样本估计取 12500 判顺延）与 test_partial_samples_take_available_max（不足 3 样本取已有样本 max）两关键例 PASSED。出处：core/admin_monitor.py:2199-2278（_code_review_archive_duration_mean max 化）、tests/test_code_review_night_defer.py:192/216 | pass | 0/5 | - |
| estimator-takes-max-not-mean-probe | 行为探针：_code_review_archive_duration_mean 直调——合成归档样本 10893/12500/5338 秒估计须取 max=12500（而非均值 9577.2，输出不得出现 9577.2）；删至 2 样本（10893/12500）取已有样本 max=12500；零样本返回 None（回退仅判派发时刻落窗）。出处：core/admin_monitor.py:2275-2278（max(samples)）、:2273-2274（空样本 None） | pass | 0/6 | - |
| night-window-defer-crossing-probe | 行为探针：上行趋势下 01:00 派发按 max 估计判穿窗顺延——近 3 轮样本 max=12500s、窗配置 04:15-04:45、派发时刻 01:00:00，预计结束 04:28 落窗 → checkpoint 返回 reason=night_quiet_window_deferred、不派 run、同日防重未写；顺延日志含「实测最大时长」（文案自「实测均时长」同步改）且不含旧文案；对照：样本换 max=5338s（预计结束 02:28 未触及 04:15）→ 正常派发 reason=scheduled。出处：core/admin_monitor.py:1934-1941（顺延分支）、:2340（sample_note 实测最大时长）、:2326-2339（相交判定） | pass | 0/9 | - |
| night-resume-suite-anchor-redispatch-green | 回归：锚驱动剃余续审测试套件全绿——跑新建 tests/test_code_review_night_resume.py 全量 5 例，钉住剩余清单组装（test_resume_dispatches_remaining_with_redispatch_of）、无锚行为不变（test_no_anchor_dispatches_full_manifest_without_redispatch）、链式覆盖完整核销清锚（test_chain_full_coverage_unlocks_and_clears_anchor）、部分覆盖锁死保锚（test_chain_partial_coverage_locks_and_keeps_anchor）、空剩余跳派（test_empty_remaining_skips_dispatch）全 PASSED。出处：tests/test_code_review_night_resume.py:156-390（tasks 2.3 三例+两补充例） | pass | 0/7 | - |
| anchor-resume-dispatch-probe | 行为探针：writeoff-pending 锚驱动剃余续审派发（生产 checkpoint 路径）——锚存在（死 run code-review-900 抢救落账覆盖 a/b，全量清单 a/b/c/d）时仅派剩余 c/d、run_code_review 收到 redispatch_of=code-review-900（复用既有形参，未另起新形参）、结构化日志含 reason=writeoff_resume、resume_of=code-review-900、剩余 2/4 文件、死 run 已落分片计数；无锚时全量清单派发、redispatch_of=None、无 writeoff_resume 日志（行为不变回归）。出处：core/admin_monitor.py:1988-2068（锚读取与剃余派发）、:2091-2096（redispatch_of 透传） | pass | 0/10 | - |
| resume-empty-remaining-skip-probe | 行为探针（空状态）：剩余清单为空（抢救落账已覆盖全量清单全部文件）时锚驱动续审跳过派发不空跑——checkpoint 返回 reason=writeoff_resume_no_remaining、run_code_review 零调用、writeoff-pending 锚保持原样（核销解锁交由收尾覆盖守卫判定，本路径不触碰核销红线）。出处：core/admin_monitor.py:2031-2052（空剩余跳派分支） | pass | 0/5 | - |
| night-quiet-keyword-contract-probe | 回归契约：night_quiet 关键字缺席契约不破——跑 tests/test_code_fix_night_quiet_window.py::TestSingleEntryInvariant::test_four_trigger_sites_share_single_entry，并独立源码核验 core/agent_runner/maintenance_runs.py 与 core/event_bus.py 均不含 night_quiet_window（本 SPEC 改动不得触碰该契约）、core/code_fix.py 保有该键、两文件均保有 .checkpoint() 单点汇入、core/admin_monitor.py 含 writeoff_resume 落点、core/agent_runner/maintenance_runs.py 保有 redispatch_of 形参。出处：tests/test_code_fix_night_quiet_window.py:518-541（契约断言） | pass | 0/12 | - |
| scope-config-interface-compat-regression | 回归：派发接口扩展的相邻兼容——run_code_review 增加锚驱动续审标注（redispatch_of 形参既有化使用）后，钉派发 kwargs 的相邻测试 tests/test_code_review_scope_config.py 全量 13 例仍全绿（实现轮已同步补 redispatch_of: None 断言）。出处：core/agent_runner/maintenance_runs.py:2082-2088（run_code_review redispatch_of 形参） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

