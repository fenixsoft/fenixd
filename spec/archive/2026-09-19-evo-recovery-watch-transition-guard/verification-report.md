# 验证报告：evo-recovery-watch-transition-guard

> ⚠️ 本报告由框架于 2026-09-14T09:07:39Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-14T09:07:39.294628+00:00

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.23M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-all-transition-guard-tests | 运行 test_recovery_watch_transition_guard.py 全部26个用例，验证过渡窗口豁免+真实stale仍报+有界性+三态断言+mock回归+defer逻辑全部通过 | pass | 0/2 | - |
| cli-defer-positive-paths | 过渡窗口顺延正向路径：成功收工痕迹在60s buffer内→顺延不误报（3.1）；pending merge在grace内→顺延不误报；顺延后观察项持久化（防裸continue丢弃）；due未到期的观察项不受影响 | pass | 0/2 | - |
| cli-real-stale-still-reported | 真实stale仍被升级：无pending merge无succeed→正常报dispatch_stalled；pending merge但grace超时→回落报stale；年龄恰好=grace+1s→回落；succeed在60s外无pending→正常报stale | pass | 0/2 | - |
| cli-grace-boundedness | 有界性回落断言（1.4）：年龄10min>grace 5min→回落报stale；年龄起点取max(提交时间,succeed痕迹时间)（243s场景仍在grace内豁免）；succeed使grace_deadline从succeed起算 | pass | 0/2 | - |
| cli-pending-merge-3-states-and-prefix-guard | has_pending_merge三态（未合并=真/已合并=假/无分支=假）+前缀歧义守卫：spec a-b有a-b-c分支→返回False；verify-验证分支排除；非规范命名排除 | pass | 0/2 | - |
| cli-mock-substitute-regression-and-defer-logic | mock替身回归（3.4）：MagicMock has_pending_merge→is True判定为False→不豁免；MagicMock pending_merge_since→isinstance非数字→保守不豁免。_transition_defer_due辅助方法逻辑：各输入组合返回正确deferred值 | pass | 0/2 | - |
| cli-existing-tests-regression-free | 既有用例回归收口（3.4）：判据取(a)（impl run流mtime），tmpdir夹具无run流→不误命中既有4条；已跑6条全绿：test_watch_fails_when_still_fake_ready、test_watch_registered_implementing_rolled_back_to_ready_redispatches、test_watch_inplace_dispatch_blocked_by_budget_signals、test_recovery_patrol_redispatches_regressed_ready、test_defer_registers_watch_no_deadloop、test_watch_passes_when_spec_left_ready | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 7 个（第 1 轮）。

- 首轮写入 7 个场景

