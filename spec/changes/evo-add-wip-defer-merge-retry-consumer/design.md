# Design: WIP 阻断的延迟合回周期消费者

## 现状与关键事实

- 阻断站点：queue.py:1548-1553（wip_gate_blocked → _report_mergeback_wip_overlap → return），fast_track.py:552-554、repair_lane.py:573-575 同型；可重试分类（queue.py:1557-1573）显式排除 wip 形态。
- 载体缺失：rollback.py:346/:381 只写 error 文本（「mergeback wip overlap blocked (policy=block): files=...」，policy 字样为硬编码模板）；spec 状态无任何结构化等待标志。
- 既有可复用件：_retry_merge_back_only（queue.py:2082，merge-only 重试，分支缺失有兜底 :2095-2100、预算闸门保留 :2103）、_finalize_merge_success（queue.py:2238，含 implemented 推进与 _merge_retry_pending 清账 :2278-2281）、_merge_retry_count/_merge_retry_first_at 记账（queue.py:1973-2040）、主树锁 _main_tree_lock。
- 消费缺口：_merge_retry_pending 无读取点；_repair_awaiting_remerge 仅 boot 消费（state_machine.py:1745 ← fenixd.py:548）；orphaned_state（admin_monitor.py:1699，阈值缺省 15 分钟）对 wip 载体无豁免、只报不驱动。
- 主循环计时器先例：orphan_ready_check_ts（fenixd.py:633 声明、771-777 触发，60 秒粒度、try/except 不中断主循环）。

## 设计

1. **载体**：_report_mergeback_wip_overlap 同次 update_spec 增写 _wip_gate_deferred=True + 复用 _merge_retry_count/_merge_retry_first_at；标志登记进 state_machine.py:384-392 布尔往返清单，_finalize_merge_success 与 boot 清空路径（state_machine.py:1814/1836）同步清除。
2. **消费者**：fenixd.py 主循环独立计时器（120 秒节拍，常量先行不新增配置面）调用 pm_engine 新方法：扫 STATE.md 中 implementing+带标志条目 → 逐个在 _main_tree_lock 内调 _retry_merge_back_only（前置补 status 守卫：仅 implementing+带标志）→ 成功走 _finalize_merge_success 并显式 resolve 对应 mergeback_wip_overlap 告警；失败仍 wip 阻断则计数 +1。
3. **降级**：等待超 90 分钟或重试超 6 次（对齐 code-fix defer D6 范式）→ 停止自动重试，走 rollback.py:432 同型降级告警，现场标志保留供人工。
4. **顺序**：120 秒节拍远短于 orphaned_state 15 分钟阈值，自动合回先于孤儿探测；admin 巡检（5 分钟）亦晚于本检查。

## 风险与边界

- 与人工 merge 并发：_main_tree_lock 串行化，人工先行则状态守卫跳过。
- 分支被删/rebase：_retry_merge_back_only 已有分支缺失兜底（queue.py:2095-2100）；重试即重跑 merge_back_from_branch（mergeback.py:47），预演闸与 WIP 闸全在锁内、主树零污染语义不变。
- 真冲突（分支与主树内容冲突而非 WIP 重叠）：merge 失败走既有失败路径计数，超限降级人工——不尝试自动解决内容冲突。
