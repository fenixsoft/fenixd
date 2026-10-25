# 验证报告：evo-add-night-window-inflight-guard

> ⚠️ 本报告由框架于 2026-10-06T18:13:57Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T18:13:56.702200+00:00+run-result@mtime1791310436747840389

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.96M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| codefix-predicted-cross-defers | 预计跨窗顺延：窗前派出、同链近批实测均时长使预计结束时刻落入 04:15-04:45 静默窗 → 投递顺延到窗末（spec Scenario「窗前派出但预计跨窗」；判定实现在 core/code_fix.py:2886 _night_quiet_state，窗末基建 core/code_fix.py:2360）。验证 tests/test_code_fix_night_quiet_window.py::TestPredictedCrossWindow::test_predicted_cross_defers_to_window_end | pass | 0/2 | - |
| codefix-predicted-not-crossing-dispatches | 预计不跨窗照常投递：预计结束时刻早于窗起点（含恰好压线窗起点的左开边界）→ 按原时刻投递、不引入额外延迟（spec Scenario「预计不跨窗」；压线不拦语义 core/code_fix.py:2925 附近区间相交判定）。验证 tests/test_code_fix_night_quiet_window.py::TestPredictedCrossWindow::test_predicted_not_crossing_dispatches | pass | 0/2 | - |
| codefix-predicted-recent-n-sample-limit | 近批样本窗：时长估计只取同链最近 N 批 run_metrics duration_s 均值而非全历史，对慢批次保守自适应（design D1；样本上限 NIGHT_QUIET_DURATION_SAMPLE_LIMIT，均值实现 core/code_fix.py:2859 _chain_recent_duration_mean）。验证 tests/test_code_fix_night_quiet_window.py::TestPredictedCrossWindow::test_recent_limit_takes_last_n_batches | pass | 0/2 | - |
| codefix-no-valid-samples-fallback | 无近批时长样本回退：新链冷启动或历史 run_metrics 行未记 duration_s → 回退既有「仅判派发时刻落窗」判定、照常投递，不因缺样阻塞（spec Scenario「无近批时长样本回退」，fail-open 纪律 core/code_fix.py:2860 docstring）。验证 tests/test_code_fix_night_quiet_window.py::TestPredictedCrossWindow::test_no_valid_samples_falls_back_to_dispatch_time_check | pass | 0/2 | - |
| codefix-predicted-to-real-transition-no-rearm | 预测态→真实窗内态迁移不重复武装：预计跨窗态与真实窗内态共用窗次标识与武装告警语义（同窗次幂等，tasks 1.1），且预测拦截在窗末顺延释放走同一路径。验证 tests/test_code_fix_night_quiet_window.py::TestPredictedCrossWindow::test_predicted_to_real_transition_does_not_rearm 与 test_predicted_block_releases_at_window_end | pass | 0/3 | - |
| codefix-in-window-legacy-behavior-no-regression | 回归点：窗内派出的既有顺延行为不回归——窗内拦截并武装告警、四点边界（04:14:59 放行/04:15:00 拦截/04:44:59 拦截/04:45:00 放行）、窗末首个放行 checkpoint 补写解除并清窗次标识（spec Scenario「窗内派出的既有行为不回归」）。验证既有用例 test_in_window_blocks_and_arms、test_four_boundaries、test_window_end_release_once_and_marker_cleanup | pass | 0/4 | - |
| admin-frozen-state-skips-invocation | admin 瞬断冻结态不唤起：provider 处于瞬断冻结态（is_global_transient_break_active=True）且到达唤起时机 → 本轮跳过唤起、自动路径补 skipped 处置记录留痕跳过原因，下轮重新评估（spec Scenario「冻结期不唤起」；闸门实现 core/admin_monitor.py:5232 _night_dispatch_block_reasons，冻结探针复用 core/agent_runner/provider_circuit.py:1061）。验证 tests/test_admin_dispatch_window_avoidance.py 瞬断冻结参数分支 | pass | 0/3 | - |
| admin-night-window-skips-invocation | admin 断窗期不唤起：本地时区当前时刻落 04:15-04:45 静默窗内 → 本轮跳过唤起并留痕原因，跳过属非失败路径：MUST NOT 增 retry_count、MUST NOT 落升级告警（spec Requirement「admin 派发断窗避让」；窗配置单源复用 core/code_fix.py:2313，键 admin.code_review_fix.night_quiet_window）。验证 tests/test_admin_dispatch_window_avoidance.py 静默窗参数分支 | pass | 0/3 | - |
| admin-outside-window-invokes-normally | 窗外正常唤起不受影响：非冻结态且不在静默窗内照常唤起（零跳过记录）；窗配置 off 显式禁用则不避让；runner 替身缺冻结探针方法（半初始化实例）按未冻结 fail-open 照常唤起（spec Scenario「窗外正常唤起」；fail-open 语义 core/admin_monitor.py:5255 附近）。验证 test_outside_window_and_not_frozen_invokes_normally、test_window_disabled_config_invokes_normally、test_missing_freeze_probe_fails_open | pass | 0/4 | - |
| admin-manual-invoke-avoids-no-escalation | 人工显式触发同政策避让：夜间断窗期或瞬断冻结态内 invoke_manual 人工唤起 → 与自动路径同政策本轮跳过、仅日志留痕——不补处置记录、不增 retry_count、不落升级告警；窗外人工唤起照常（spec Scenario「人工显式触发同样避让」；design D2 与信号死法冷却同位政策，先例 core/code_fix.py:3210 手动授权仅越过 enabled 总开关）。验证 tests/test_admin_dispatch_window_avoidance.py::TestManualPathAvoidance 全部分支 | pass | 0/4 | - |
| runner-duration-s-both-metrics-sites | run_metrics 补记 duration_s：runner 归档行与日志侧 metric_type=run_metrics 行两处同源写入 run 墙钟时长（tasks 1.2；写入点 core/agent_runner/runner.py:6366 与 :6409），读取侧 code_fix 对历史行缺该字段/负值/非有限值一律剔除按缺样跳过（core/code_fix.py:495 _read_run_metrics、core/code_fix.py:2859 _chain_recent_duration_mean）。验证 tests/test_code_fix_night_quiet_window.py::TestRunMetricsDurationField::test_duration_s_written_at_both_metrics_sites | pass | 0/2 | - |
| probe-night-quiet-state-three-modes | 实现探针（独立于交付测试文件，直接驱动 _night_quiet_state，core/code_fix.py:2886）：真实窗内态返回 predicted=False；窗前派出 04:10 + 近批均值 1800s → 预测跨窗态 predicted=True 且 est_duration_s=1800；预计不跨窗 03:00+1800s、压线 04:10+300s（恰等窗起点）、无有效样本 → 均返回 None（fail-open）。run_metrics 样本写真实 .fenix/runs/<run_id>.jsonl 归档（core/code_fix.py:495 双路径读取的顶层路径），时钟注入 patch core.code_fix.time.localtime | pass | 0/10 | - |
| probe-admin-block-reasons-modes | 实现探针（独立于交付测试文件，直接驱动 _night_dispatch_block_reasons，core/admin_monitor.py:5232）：冻结态命中原因含「瞬断冻结」；断窗期 04:30 命中原因含「静默窗」；窗外 10:00、窗配置 off、runner 缺冻结探针方法（fail-open）均返回空（不避让）。AdminMonitor 最小替身装配与 tests/test_admin_dispatch_window_avoidance.py:70 _make_monitor 同构，时钟注入 patch core.admin_monitor.time.localtime | pass | 0/7 | - |
| guard-suite-full-regression | 守卫套件全量回归：tests/test_code_fix_night_quiet_window.py 与 tests/test_admin_dispatch_window_avoidance.py 两文件全量 pytest 零失败（32 passed + 14 subtests passed 基线，2026-10-07 实测 1.94s），防预计跨窗新判定破坏既有窗/冷却共存认知（tasks 3.1/3.2 整体回归点） | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

