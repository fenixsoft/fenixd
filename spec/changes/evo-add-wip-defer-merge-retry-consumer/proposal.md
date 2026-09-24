# Proposal: WIP 阻断的延迟合回周期消费者

## 问题背景

spec 实现车道合回被 WIP 重叠闸门阻断时（core/pm_engine/dispatch/queue.py:1548-1553，同型 fast_track.py:552-554、repair_lane.py:573-575），现状只发一条 mergeback_wip_overlap major 告警即 early-return：不落任何等待载体（唯一现场标志是 error 文本）、不排 merge-only 重试定时器（既有定时器链显式排除 wip 形态）、_merge_retry_pending 无运行期消费者、恢复期 re-merge 仅 daemon boot 消费。2026-09-23 实证一次完整代价：add-code-review-sharded-out 卡 implementing+error 18 分钟，烧掉一条 major 信号与一轮 admin 处置 run（48 轮、约 16.9 分钟）才由人工合并解锁；若无人处置，15 分钟后还会叠加一条 orphaned_state major（该载体不在豁免内）——现状兜底是「两次 admin 召唤」。

## 方案概述

1. **落载体**：_report_mergeback_wip_overlap 在写 error 的同次 update_spec 增写结构化等待标志（布尔 + 重试计数 + 首阻时刻），登记进 STATE.md 布尔往返清单；三处阻断站点自动受益。
2. **周期消费者**：daemon 主循环加独立计时器（60-300 秒节拍，参照 orphan_ready_check_ts 既有模式），复查带标志的 spec：重叠文件已干净即在主树锁内执行 merge-only 重试，成功走既有 _finalize_merge_success（implemented 推进 + 标志清账 + 告警显式闭环）。
3. **状态守卫**：重试仅认「implementing 且带等待标志」条目——人工/admin 已合并推进的 spec 跳过并清账，杜绝迟到重试对已合并 spec 重复合并。
4. **有界降级**：复用 _merge_retry_count 记账，超窗口（90 分钟，对齐 code-fix defer 范式）/超轮数（6 次）即停止自动重试、降级为人工处置告警。
5. **顺序保证**：周期消费者节拍远短于 orphaned_state 的 15 分钟阈值，自动合回先于孤儿探测生效。

## 影响范围

- 修改 core/pm_engine/dispatch/rollback.py：阻断点落结构化载体
- 修改 core/pm_engine/dispatch/queue.py：_retry_merge_back_only 状态守卫、周期复查与重试实现
- 修改 core/state_machine.py：新标志布尔往返登记与清账（含 boot 恢复两个复位写点）
- 修改 core/admin_monitor.py：orphaned_state 探测对带标志未超限条目的豁免（对齐 _repair_awaiting_remerge 先例）
- 修改 fenixd.py：主循环周期计时器
- 新增 tests/test_wip_defer_merge_retry.py：消费者回归

## 非目标

- 不改 WIP 重叠闸门本体与 escalate 拦截语义（evo-merge-back-wip-overlap-gate 交付面不动）。
- 不动 code-fix 车道既有 defer 台账及其链边界消费者（fix-codefix-wipgate-defer 交付面不动）。
- 不做主树 WIP 的自动 stash/提交——WIP 属人工会话产物，超限后仍交人工。
