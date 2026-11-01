# fix-fasttrack-wip-defer-branch-anchor — tasks

> 全部任务完成后逐项勾选（`- [x]`）；fast-track scale 预检按未勾选任务条数估算。

## 1. 锚点统一提前落盘

- [ ] 1.1 `core/pm_engine/dispatch/fast_track.py` `_reconcile_and_merge`：branch 非空时把 `branch` + `implementer_run` 并入既有 `_ocr_base_commit` 的 merge 前 `update_spec`（fast_track.py:669 一带，对齐 full 车道同构写点 queue.py:2399-2406）；写入失败非阻塞（WARNING），MUST NOT 新增清锚点。
- [ ] 1.2 确认成功收口写点（fast_track.py:958-988）与失败三岔（rehearsed/WIP/spec_dir_inflight）不触碰锚点的既有约定不变；不改 `_retry_merge_back_only`、`_defer_merge_back`、`_recheck_wip_deferred_merges`。

## 2. 回归测试

- [ ] 2.1 tests/ 新增用例：fast-track run 成功 + merge-back WIP 阻断 → STATE 含 branch/implementer_run 锚点；触发 `_recheck_wip_deferred_merges` 单拍 → merge-only 成功走 `_finalize_merge_success`，无 `mergeback_branch_anchor_missing` 告警。
- [ ] 2.2 tests/ 新增用例：fast-track merge-back 撞 spec_dir_inflight → `_defer_merge_back` 顺延后按 STATE 锚点执行 merge-only 重试成功（不再回锚点缺失出口）。
- [ ] 2.3 既有测试回归：tests/test_wip_defer_merge_retry.py 与 fast-track 既有用例（含 `test_fast_track_verify_branch_no_fallback`）全绿；full 车道测试不回归。

## 3. 验收对账

- [ ] 3.1 对照 proposal 验收两条（单测断言 + 实证路径不再出现 `mergeback_branch_anchor_missing` 告警）逐条留痕。
