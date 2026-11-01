# fix-fasttrack-wip-defer-branch-anchor — design

## 根因（代码实证，spec-review 评审复核）

- **阻塞写点不落锚点**：`rollback._report_mergeback_wip_overlap`（rollback.py:702）的 `_wip_overlap_updates`（rollback.py:745-770）仅写 `error` / `_wip_gate_deferred` / `_merge_retry_first_at`，`branch` 参数只进告警 evidence（rollback.py:785），不进 STATE。
- **消费链从 STATE 读锚点**：`_retry_merge_back_only`（queue.py:3734）`branch = entry.get("branch")`（queue.py:3781），缺失即 `mergeback_branch_anchor_missing` 告警出口（queue.py:3789-3814）。
- **fast-track 在飞无写点**：`_reconcile_and_merge`（fast_track.py:654）merge 前仅写 `_ocr_base_commit`（fast_track.py:669），`branch` 只是局部变量（fast_track.py:660）；唯一 `branch` STATE 写点在成功收口（fast_track.py:962）。full 车道对应写点在 merge 前统一落（queue.py:2399-2406，日志「锚点已提前落盘」）——两车道锚点契约不一致是缺陷本质。

## 受影响的消费链（不止 WIP 一条，评审实测修正 proposal 边界）

1. WIP 阻断 → `_recheck_wip_deferred_merges`（queue.py:3895）→ `_retry_merge_back_only`；
2. spec_dir_inflight 顺延 → `_defer_merge_back`（queue.py:3271）→ `_schedule_merge_retry` Timer → `_retry_merge_back_only`。`_defer_merge_back` docstring「保留 branch/implementer_run 锚点」的前提正是锚点已在 STATE——fast-track 在飞没落，该前提不成立；fast_track.py:706-708 注释「`_retry_merge_back_only` 天然覆盖 fast-track 车道」是乐观错误注释，无锚点时该实现恰是本缺陷现场；
3. 归档残留自愈重放 → `_retry_merge_back_only`（queue.py:3467，经 `_defer_merge_back` 超限分支，fast-track 同样可达）。

三条链共用同一 STATE 读锚点出口，锚点供给点越早覆盖越全。

## 方案选型

| 候选 | 覆盖链 | 取舍 |
|---|---|---|
| A. 仅 `wip_gate_blocked` 分支返回前落锚点 | 仅 WIP | 最小改动；spec_dir_inflight 链继续裸奔 |
| B. 并入 `_wip_overlap_updates`（run_id 新增传参） | 仅 WIP | 单次原子写，覆盖面同 A |
| **C. 统一提前落点（采用）** | 三条链全覆盖 | `_reconcile_and_merge` branch 非空处与 `_ocr_base_commit` 同批 `update_spec` |

采用 C 的理由：

- 与 full 车道同构（queue.py:2399-2406 一次写 `branch`/`implementer_run`/`_ocr_base_commit`），消除两车道锚点契约不对称（proposal 目标 D1 原文）；
- 失败三岔注释「三岔对 branch/implementer_run 均**不触碰**」「MUST NOT 在此新增清锚点（merge 失败不代表 stale 锚点）」（fast_track.py:682-686）的语义前提正是「锚点已在」——C 使该前提首次在 fast-track 成立；
- `mergeback_branch_anchor_missing` 出口（queue.py:3782 `if not branch`）降级为最后兜底，不再被 fast-track 正常失败链触发。

## 边界与风险

- **幂等**：成功收口（fast_track.py:958-988）重写同值，无冲突语义（proposal 第 3 点）。
- **锚点在飞窗口**：提前落盘后在飞期间两个接手消费者均按标志守卫（`_wip_gate_deferred` / `_merge_retry_pending`），新在飞 spec 无标志不动作；成功收口既有清账字段集（fast_track.py:982-986）已覆盖窗口收口。
- **重派清理**：ready 降级重派沿用既有入口清锚点机制（queue.py:1766、1854；「锚点清除见 _run_agent_worker 入口」queue.py:2386），提前落点不改变清锚点时机。
- **boot 复位**：`TestBootResetClearsFlag`（tests/test_wip_defer_merge_retry.py:364-402）清锚点语义不变。
- **repair 通道无同型缺口**：repair 链 branch 一路显式传参（`_direct_rehearsed_to_repair` fast_track.py:694 → `_run_repair_worker` / `_handle_remerge_failure` repair_lane.py:1027），不消费 STATE 锚点，不受本缺陷影响、也不被本修复改变。

## Non-Goals

- 不改 WIP 重叠闸门阻塞与告警语义（`mergeback_wip_overlap` 告警保留）；
- 不动 full 车道既有锚点写点；
- 不改 `_retry_merge_back_only`、`_defer_merge_back`、`_recheck_wip_deferred_merges` 本体逻辑。
