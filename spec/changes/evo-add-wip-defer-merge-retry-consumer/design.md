# Design: WIP 阻断的延迟合回周期消费者

## 现状与关键事实

- 阻断站点：queue.py:1548-1553（wip_gate_blocked → _report_mergeback_wip_overlap → return），fast_track.py:552-554、repair_lane.py:573-575 同型；可重试分类（queue.py:1557-1573）显式排除 wip 形态。
- 载体缺失：rollback.py:346/:381 只写 error 文本（「mergeback wip overlap blocked (policy=block): files=...」，policy 字样为硬编码模板）；spec 状态无任何结构化等待标志。
- 既有可复用件：_retry_merge_back_only（queue.py:2082，merge-only 重试，分支缺失有兜底 :2095-2100、预算闸门保留 :2103）、_finalize_merge_success（queue.py:2238，含 implemented 推进与 _merge_retry_pending 清账 :2278-2281）、_merge_retry_count/_merge_retry_first_at 记账（queue.py:1973-2040）、主树锁 _main_tree_lock。
- 消费缺口：_merge_retry_pending 无读取点；_repair_awaiting_remerge 仅 boot 消费（state_machine.py:1745 ← fenixd.py:548）；orphaned_state（admin_monitor.py:1699，阈值缺省 15 分钟）对 wip 载体无豁免、只报不驱动。
- 主循环计时器先例：orphan_ready_check_ts（fenixd.py:633 声明、771-777 触发，60 秒粒度、try/except 不中断主循环）。

## 设计

1. **载体**：_report_mergeback_wip_overlap 同次 update_spec 增写 _wip_gate_deferred=True + 复用 _merge_retry_count/_merge_retry_first_at；标志登记进 state_machine.py:384-392 布尔往返清单，并在以下三类写点同步清除：_finalize_merge_success 清账块（queue.py:2278-2281 同块增写）、boot 恢复**保留续做复位写点**（state_machine.py:1989-2007，implementing→READY，增写 _wip_gate_deferred=False）、boot **清空重建复位写点**（state_machine.py:1724-1741，对齐 :1734 清 _repair_awaiting_remerge 先例）。注意 state_machine.py:1814/1836 是 _repair_awaiting_remerge 的消费清点、非本标志复位写点——漏清保留续做写点会让重启后陈旧标志在恢复 run 在飞期间触发 merge-only 重试（把半成品分支过早合入主树，并与在飞 run 收尾竞态）。
2. **消费者**：fenixd.py 主循环独立计时器（120 秒节拍，常量先行不新增配置面）调用 pm_engine 新方法：扫 STATE.md 中 implementing+带标志条目 → 逐个在 _main_tree_lock 内调 _retry_merge_back_only → 成功走 _finalize_merge_success 并显式 resolve 对应 mergeback_wip_overlap 告警（沿用 stuck-signal-hygiene 处置记录范式，AdminStore 写 result=resolved 处置记录，先例 infra_classify.py:549）；失败仍 wip 阻断则计数 +1。**守卫拆两层（勿合并成一条「须带标志才放行」）**：`_retry_merge_back_only` 前置补的 status 守卫只拦「status 非 implementing」（跳过并清账后返回）——该方法既有唯一生产调用链是 spec_dir_inflight 顺延定时器（queue.py:2078），其条目仅带 _merge_retry_pending（queue.py:1988）不带新标志，既有测试亦不带标志直调（tests/test_merge_back_spec_dir_guard.py:557-562、585-587）；「implementing + _wip_gate_deferred」的严格筛选放在新扫描方法处。
3. **降级**：等待超 90 分钟或重试超 6 次（对齐 code-fix defer D6 范式）→ 停止自动重试，走 rollback.py:432 同型降级告警，现场标志保留供人工。
4. **顺序**：120 秒节拍远短于 orphaned_state 15 分钟阈值，自动合回先于孤儿探测；admin 巡检（5 分钟）亦晚于本检查。**orphaned_state 豁免**：等待落在 15–90 分钟窗口的条目若不豁免，orphaned_state major（缺省 15 分钟，admin_monitor.py:14-15/1725）照发召唤 admin，与「admin 仅处理真冲突与超限降级」的目标矛盾（且其处置复位 implementing→ready，admin_monitor.py:368，会与周期消费者守卫相撞）——_detect_orphaned_state 增设与 _repair_awaiting_remerge 同型豁免（admin_monitor.py:1754 先例）：`_wip_gate_deferred=True 且未超限（计数<6 且窗口<90 分钟）` 跳过探测；超限降级后豁免自动失效（标志保留，孤儿探测恢复兜底）。

## 风险与边界

- 与人工 merge 并发：_main_tree_lock 串行化，人工先行则状态守卫跳过。
- 分支被删/rebase：_retry_merge_back_only 已有分支缺失兜底（queue.py:2095-2100）；重试即重跑 merge_back_from_branch（mergeback.py:47），预演闸与 WIP 闸全在锁内、主树零污染语义不变。
- 真冲突（分支与主树内容冲突而非 WIP 重叠）：merge 失败走既有失败路径计数，超限降级人工——不尝试自动解决内容冲突。
- 标志生命周期不变式（消费者免查活动 run 的依据）：implementing+_wip_gate_deferred ⇒ 无在飞实现 run——落标志时触发阻断的 run 已收尾（_report_mergeback_wip_overlap 在 run 结果处理期调用），新 run 只能自 ready 派发而两个 boot 复位写点已清标志（见设计 1）。实现方依赖此不变式即可，无需在消费者内再探活在飞 run。
- 计数复用混账（已知、接受）：_merge_retry_count/_merge_retry_first_at 为 wip 与 spec_dir_inflight 两条顺延路径共用记账（queue.py:1973-1990），同一 spec 先后经历两种阻断时窗口/轮数混合累计，wip 降级预算可能被顺延轮数加速消耗；两预算均有界（90 分钟/6 次与 30 分钟/3 次），可接受，不引入独立第二套计数。
