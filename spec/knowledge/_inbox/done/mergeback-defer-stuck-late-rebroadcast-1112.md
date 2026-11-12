# mergeback_wip_defer_stuck 降级告警无成功收尾闭环消费者（迟到重投实证）

- 日期：2026-11-12
- 类型：排查结论（候选回填 worktree-vc 域 wip-defer-merge-retry 页「有界与降级」/「周期自动合回」段）
- 涉及能力：wip-defer-merge-retry（spec 车道 WIP 阻断延迟合回）

## 现象

consolidate-alerts-to-ops-page 于 2026-11-12T02:18 UTC 首阻（mergeback_wip_overlap，global.less 单文件 WIP 重叠，policy=escalate），周期消费者 6 轮 merge-only 重试后，02:41:27 UTC 窗口内成功合并（f91afe16d），成功收尾完整执行（推进 implemented→verifier 入队、_wip_gate_deferred/_merge_retry_count/_merge_retry_first_at 全清账、overlap 告警写 resolved 两条）。但降级路径此前/同期落盘的 `mergeback_wip_defer_stuck` 告警滞留 pending，02:47:10 被 AdminMonitor 周期扫描再次投递，唤起 admin 处置一个已事实闭环的困境（烧一条 admin run 配额）。

## 根因

wip-defer-merge-retry 页现行文本只要求成功收尾闭环「原 mergeback_wip_overlap major 告警」（stuck-signal 闭环范式），未覆盖降级时新发的 `mergeback_wip_defer_stuck` 告警——它没有成功路径消费者，会以 pending 形态被周期扫描反复重投。

## 处置配方（admin 人工通道，本次已执行）

1. 只读核实三件事：分支已是 HEAD 祖先且 `git diff HEAD...branch` 空；合并提交时刻在窗口内；STATE.md 条目等待标志全清账、error=null、状态已推进。
2. 零 git 动作、零状态改写（信号 recommended_action 是常量模板，其「复位 ready 重放 merge-back」前提在事实闭环后不成立，照做即重复破坏）。
3. 处置记录写 `result=resolved` 显式闭环（stuck-signal 闭环范式同型），登记 `suggested_choice=close_stale_mergeback_defer_signal` 供注册表演进。

## 补接线方向（供框架演进）

在 `_finalize_merge_success` / 周期消费者成功收尾块，把同 spec 的 pending `mergeback_wip_defer_stuck` 记录一并写 resolved（与 overlap 告警闭环同型），消除迟到重投。

## 溯源

- admin run admin-consolidate-alerts-to-ops-page-1794451630 处置记录（.fenix/admin_disposition-admin-consolidate-alerts-to-ops-page-1794451630.json）
- 关联记忆页：wip-defer-merge-retry、merge-back
