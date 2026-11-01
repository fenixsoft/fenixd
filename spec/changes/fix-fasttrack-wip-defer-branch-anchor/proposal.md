# fix-fasttrack-wip-defer-branch-anchor

## 背景与问题

2026-11-01T05:15Z，fast-track 车道 spec `add-arbiter-quality-display` 实现 run 成功（7 commits 落在分支 `fenix/add-arbiter-quality-display-1793508579`），随后 fast-track merge-back 被主树 WIP 重叠闸门阻塞（主树 `restart_request` 未提交删除与分支同文件改动重叠，policy=escalate）。阻塞路径 `rollback._report_mergeback_wip_overlap` 只写 `error` / `_wip_gate_deferred=True` / `_merge_retry_first_at`，然后周期消费者 `_recheck_wip_deferred_merges`（120s 节拍）接手，调 `_retry_merge_back_only`，后者**从 STATE 读 `branch` 锚点**——

**根因**：fast-track 车道在飞期间从不在 STATE 写 `branch` 锚点（仅 merge 成功后的收口写点 `fast_track.py:962` 才写 `branch: result.branch`；full 车道在 `queue.py:2402` 有对应写点）。于是 `_retry_merge_back_only` 读到 `branch=None`，走 `mergeback_branch_anchor_missing` 出口：每 120 秒打一条 ERROR「merge 重试 '...' 无分支锚点」+ 写一条同名 admin 告警，spec 永远悬置 implementing。admin_monitor 的 daemon_errors 同指纹熔断（≥2 次/10 分钟窗口）随之触发，烧掉一个 admin 会话（admin-global-1793510428）。

对照：full 车道同样被 WIP 重叠阻塞时，run 成功路径已在 STATE 落了 `branch`/`implementer_run` 锚点（queue.py:2402），周期消费者能正常 merge-only 重试——两车道对「WIP 阻断后等待重试」这一状态的锚点契约不一致，是缺陷本质。

证据链（fenixd.log 2026-11-01）：
- 05:15:11.042 `WIP overlap precheck ... ['restart_request']`（阻塞）
- 05:15:11.149 `Updated SPEC ... {"error": "mergeback wip overlap blocked...", "_wip_gate_deferred": true, ...}`（无 branch 写点）
- 05:15:12 / 05:17:12 / 05:19:13 / 05:21:14 每 120s `无分支锚点` ERROR + `mergeback_branch_anchor_missing` 告警

admin 侧处置（本次）：手工经 `StateMachine.update_spec` 补写真实锚点（branch + implementer_run），下一拍周期消费者即走正常 merge-only 重试成功合回——证明缺的只是锚点落盘，不是合并通道本身。

## 目标（D1）

fast-track 车道 merge-back 被 WIP 重叠闸门阻塞（`wip_gate_blocked=True`）时，与 full 车道同契约：**在 STATE 落 `branch` + `implementer_run` 锚点**，使 `_recheck_wip_deferred_merges` 周期消费者的 merge-only 重试可直接工作，消除 `mergeback_branch_anchor_missing` 死循环告警与 daemon_errors 同指纹熔断误触发。

## 方案（D2）

1. `fast_track.py` 的 `wip_gate_blocked` 分支（调用 `_report_mergeback_wip_overlap` 处）：在阻塞返回前经 `state_machine.update_spec(spec_name, {"branch": result.branch, "implementer_run": result.run_id})` 落锚点（与 `_wip_overlap_updates` 的 error/记账同一窗口写入或紧随其后，非阻塞包裹）。
2. 或等价方案：把锚点并入 `rollback._report_mergeback_wip_overlap` 的 `_wip_overlap_updates`（需把 branch/run_id 传参进来），单次原子写入更优。
3. 成功收口（`fast_track.py:962` 一带）的既有锚点写点保持不变（幂等重写同值无害）。
4. 回归测试：fast-track run 成功 + merge-back WIP 阻断 → 断言 STATE 落 branch/implementer_run 锚点、模拟周期消费者重试可走通 merge-only；full 车道既有测试不回归。

## 边界（D3/D4）

- 不改变 WIP 重叠闸门本身的阻塞语义与告警（`mergeback_wip_overlap` 告警保留）。
- 不动 full 车道已正确的锚点写点。
- spec_dir_inflight 顺延路径（`_defer_merge_back`）不受影响（该路径显式传 branch，本就可用）。

## 验收

1. 单测：fast-track WIP 阻断后 STATE 含 branch 锚点；周期消费者单拍内完成 merge-only 成功路径（mock）。
2. 实证复现路径不再出现 `mergeback_branch_anchor_missing` 告警。
