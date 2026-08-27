# Tasks: improve-scheduling-noise-governance

## 1. 验证环境健全性门（design D1/D2/D5）

- [x] 1.1 verify_engine 增加后置分类函数：识别「mock_api 存在 + 纯 Locator/wait_for 等待类断言错误」组合并触发环境探针（dashboard `/api/state` 连通+推流检查）；补单元测试（探针通/断两分支）
- [x] 1.2 场景结算接入 blocked-env 分类与 summary.blocked_env 统计；报告字段与既有 schema 向后兼容（旧 report 无该字段读为 0）；补单测
- [x] 1.3 verdict 换算接入：有效失败=failed-blocked_env；全批 blocked-env 判 inconclusive → 保持 testing 重派；inconclusive 轮次不累计 repeated_failures（信号抑制标记传递到 admin store）；补单测四例（含今日 fixture 期望值断言）
- [x] 1.4 今日真实 report 脱敏入库 `tests/fixtures/report_0827_noise.json`，回归断言：≥12 场景转 blocked-env、整体 inconclusive

## 2. 派发队列老化（design D3）

- [x] 2.1 _run_queue 条目结构加 enqueued_at；_process_queue/_on_spec_ready 比较改用 effective_priority 计算（config: pm.dispatch.aging.*，默认 enabled=false）；补单测（P6 饿死案例获得窗口 / 未达阈值零行为差异 / floor 封顶）
- [x] 2.2 同级稳定序保障与活动任务不老化；daemon 重启语义（重建队列从零计时）注释与单测

## 3. fix 族谱收敛（design D4）

- [x] 3.1 族谱度量函数（深度=fix- 前缀层数、宽度=同父未完成兄弟数，基于 read_all 全量）；_on_spec_bug_found 创建前接线拦截；补单测（四层请求拦截 / 宽度第二拦截 / 历史命名不追溯）
- [x] 3.2 family_explosion 信号接入 admin store 与 disposition 流程；「放行一次」豁免位 `_family_waiver` 设置/消费/复位；补单测（信号产生 / 放行单次通行 / 未放行持续拦截）
- [x] 3.3 config.yaml 增补 pm.family 与 pm.dispatch.aging 注释默认值；dashboard 无需改动的前提下确认 family_explosion 在既有 activity view 可见（手动冒烟）

## 4. 回归与核验

- [x] 4.1 全量 pytest 通过（重点 tests/test_core.py、verify 相关及新增用例），无既有用例回归
  - 结果：`pytest tests/` 全量 544 pass、0 fail、0 error（preserve+ci 亦通过），无既有用例回归。
  - 新增用例：test_env_sanity_gate.py 37 例、test_dispatch_aging.py 10 例、test_family_governor.py 24 例。
- [x] 4.2 对照三个 capability spec 的全部 Scenario 逐条核对实现覆盖并记录结论
  - **verify-environment-sanity-gate**（5 Scenario）：
    - S1 mock 断链下的 UI 超时被降级 → `test_candidate_mock_plus_wait_timeout` + `test_probe_down_candidate_degrades` + `test_probe_down_classifies_candidates_only` ✓
    - S2 探针健康时维持真失败 → `test_probe_healthy_keeps_fail`（finalize 与 engine 后置分类两处）✓
    - S3 全批环境性失联触发重验 → `test_all_blocked_inconclusive_reenqueues` + `test_attempts_exhausted_holds_backoff` + `test_fixture_noise_round_overall_inconclusive`（14 场景 fixture 13/14 转 blocked-env）✓
    - S4 连续 inconclusive 不唤醒 Administrator → `test_two_consecutive_inconclusive_rounds_no_signal` + 对照组 `test_control_error_runs_still_detect` ✓
    - S5 环境恢复后的真失败照常晋级 → `test_probe_healthy_keeps_fail` + `test_genuine_failure_not_inconclusive` + 旧报告兼容 `test_legacy_report_without_blocked_env_field_is_compatible` ✓
  - **dispatch-queue-aging**（4 Scenario）：
    - S1 P6 条目获得窗口 → `test_starved_p6_gets_window_under_constant_p4`（P4 常驻时饿死 P6 老化后获得派发窗口）✓
    - S2 未达阈值行为完全不变 → `test_disabled_by_default_returns_zero` + `test_below_initial_wait_no_aging` + `test_control_p6_starved_without_aging`（关闭/未达阈值为零行为差异）✓
    - S3 持久运行的 P4 不会被降级 → `test_active_set_records_base_priority_not_effective`（活动集记录 base 而非 effective）✓
    - S4 同级顺序稳定 → `test_same_effective_fcfs_order_stable`（effective 相等保 FCFS 稳定序）✓
    - 补充：`test_floor_levels_cap` / `test_effective_never_negative`（floor 封顶）、`test_enqueue_records_timestamp_for_zerotimer_restart`（daemon 重启从零计时）✓
  - **fix-family-convergence-governor**（3 组 Scenario）：
    - S1 深度上限：四层嵌套（fix-fix-fix-fix-x）请求被拦截 → `test_four_layer_request_intercepted` + `test_four_layer_intercepted_writes_signal` ✓
    - S1 宽度上限：同根未完成第二兄弟被拦截 → `test_width_second_sibling_intercepted` + `test_width_intercepted_writes_signal` + `test_width_below_limit_allowed`（未越界放行）✓
    - S2 越界转人工处置：拦截产生 family_explosion signal → `test_signal_picked_up_and_administrator_invoked` + `test_picked_up_even_without_in_progress_specs` + `test_same_record_not_reinvoked_next_tick`（escalated 去重）✓
    - S2 人工放行单次通行 → `test_waiver_allows_exactly_one_then_resets` + `test_waiver_reset_after_usage_then_reblocked` + `test_admin_waiver_sets_family_waiver_on_spec` + `test_waiver_via_text_token` + 未放行持续拦截 `test_non_waiver_does_not_set_family_waiver` + `test_non_waiver_continuously_intercepted` ✓
    - S3 计数口径与既有数据兼容 → `test_historical_four_layer_names_evaluated_by_current_value` + `test_width_excludes_done_and_pushed` + `test_depth_not_fooled_by_name_containing_fix`（done 祖先不追溯）+ `family_waiver` 豁免消费 `test_waiver_consumed_even_when_below_limit` / `test_family_waiver_consumed_once_only` ✓
  - 结论：三 capability 全部 Scenario 均有实现 + 单测覆盖，无未覆盖缺口。
