# 设计：maintree-stray-wip-sweep

## Context

- 实证案例：potplayer-base 主树 4 文件（25+/15-）滞留超 6 小时，仅被 daily self-review 复盘车道（review-2026-10-03 run，02:12 检出）发现；merge-back autostash（fenixd.log:1096）使其对 overlap 闸门不可见并覆写 mtime。
- 既有机制：`core/worktree_manager/types.py:14` `WipOccupantInfo`（机械归因 + BLIND_SPOT_NOTE）；`core/code_fix.py:2378` `_write_defer_orphan_alert`（一次性 major 告警型制 + owner 先查后记去重 + AdminStore 落盘）；`core/worktree_manager/stash_guard.py:591` `reclaim_stale_autostash`（非阻塞 `_main_tree_lock` 互斥纪律、tracked-only 脏口径、「脏不抢」保护语义）；周期挂点 `fenixd.py:901`（主循环调用 `pm_engine.reclaim_stale_autostash_if_idle`）；信号分级登记点 `core/admin_monitor.py:251` `SIGNAL_SEVERITY`；宽限配置先例 `admin.mergeback_wip_orphan_grace_minutes`（code_fix.py:3444，ConfigLoader 点号键读取）。

## Goals

- 散件滞留由机械巡检在分钟级周期内建档、宽限耗尽时以 major 告警浮出，替代 LLM 复盘车道的偶然检出。
- 与既有 autostash/merge-back/WIP-overlap 车道零互扰：只读盘点、锁纪律对齐、告警一次不重复。

## Decisions

- D1 计时用内容指纹，不用 mtime：本次案例中 4 文件 mtime 被 02:22:13 autostash pop 纳秒级同刻重写，mtime 计时会被外部操作归零。指纹 = 改动路径排序集 + `git diff HEAD` 内容哈希（diff 对 HEAD 求，含暂存+未暂存，与 porcelain tracked 口径一致——纯 `git diff` 对纯暂存态散件为空，哈希退化为空串）；指纹不变即沿用原 first_seen。
- D2 归因复用而非新造：直呼既有机械归因器 `identify_wip_occupant`（core/worktree_manager/mergeback.py:675，入参改动集 + 在飞实现车道 run_ids，内部完成 worktree 注册表真相 + 分支三点式 diff 求交，返回 `WipOccupantInfo`），不重造求交逻辑；证据文本携带既有 BLIND_SPOT_NOTE（人工/主树直改形态必零命中→按无主走宽限，误判影响有界）。接线隐含约束：engine 包装方法须供 run_ids 与 WorktreeManager 句柄（对齐 engine.py:4478 `reclaim_stale_autostash_if_idle` 先例；sweep 不设 `_active_runs` 空闲预检，否则永远看不到在飞车道、全部按无主升级）。
- D3 告警型制照抄 `_write_defer_orphan_alert`：`signal_type=maintree_stray_wip_stale`、severity=major、AdminStore.append、同指纹先查后记一次性去重、recommended_action 指向提交/stash（无 spec 可重派，同 coordination spec 的批语义适配）。登记须 admin_monitor 三表齐全：SIGNAL_SEVERITY + SIGNAL_RECOMMENDATION + STORED_SIGNAL_TYPES（摄取门 admin_monitor.py:2008 只放行收录类型；漏 STORED_SIGNAL_TYPES 则记录落 store 后无人摄取、Administrator 不唤起——姊妹信号 :430 注记明言的既有落空模式）。
- D4 锁纪律对齐 stash_guard：sweep 以非阻塞 acquire 参与 `_main_tree_lock`，锁忙即弃本轮——与 reclaim_stale_autostash 同款退化语义，绝不与 stash→merge→pop 临界区并发。
- D5 注册表进程内持有：first_seen 注册表为 daemon 内存态，daemon 重启即重置宽限。可接受：重启后散件仍在场会重新起算并最终再告警，损失仅是时效；不引入新的持久化状态文件。
- D6 只增不改：不改动 autostash 路径、reclaim「脏不抢」语义、WIP overlap 闸门任何现行行为；sweep 是旁路只读观察者。

## Risks

- 与 merge-back 并发：非阻塞锁 + 锁忙放弃兜住；sweep 内部 git 子进程均为秒级只读。
- 在飞车道长期不终态：持有者命中则持续 defer 不告警——与 add-mergeback-wip-active-coordination 的「事件驱动等待」同语义，可接受。
- untracked 不计入：对齐 tracked-only 口径；构建产物类 untracked 噪音因此天然免疫，代价是纯 untracked 散件不在本能力覆盖内（留待后续按需扩展）。
- 告警疲劳：一次性去重 + 指纹变化才重置计时，同批散件不会周期性刷屏。