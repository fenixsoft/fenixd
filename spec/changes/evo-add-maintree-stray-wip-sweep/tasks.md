## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: new
- path: fenixd.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_maintree_stray_wip_sweep.py
  kind: new
- path: core/worktree_manager/types.py
  kind: reference
- path: core/worktree_manager/stash_guard.py
  kind: reference
- path: core/code_fix.py
  kind: reference
```

## 1. 散件 WIP 盘点模块

- [ ] 1.1 core/worktree_manager/stray_wip.py：实现只读盘点函数——`git status --porcelain` 取主树 tracked 未提交改动（排除 untracked，口径对齐 stash_guard 的 tracked-only 脏判定），空集直接返回
- [ ] 1.2 core/worktree_manager/stray_wip.py：改动集指纹 = 路径排序集 + `git diff HEAD` 内容哈希（diff 对 HEAD 求，含暂存+未暂存，与 porcelain tracked 口径一致——纯 `git diff` 对纯暂存态散件为空，内容哈希会退化为空串哈希）；整个盘点在 worktree_manager 主树锁上非阻塞 acquire（对齐 stash_guard.py `reclaim_stale_autostash` 的锁纪律，stash_guard.py:629 同款 `acquire(blocking=False)`；临界区内只调只读 git，不调会再取锁的函数），锁被占用即放弃本轮
- [ ] 1.3 core/worktree_manager/stray_wip.py：归因直呼复用既有机械归因器 `identify_wip_occupant(改动集, running_run_ids=在飞实现车道 run_ids)`（core/worktree_manager/mergeback.py:675，内部完成 worktree 注册表真相 + 车道前缀过滤 + 分支三点式 diff 求交，返回 core/worktree_manager/types.py 的 `WipOccupantInfo`；MUST NOT 重造求交逻辑）：命中则不计时不告警；零命中则按指纹维护 first_seen 注册表，指纹不变沿用原 first_seen（不以 mtime 计时）
- [ ] 1.4 core/worktree_manager/stray_wip.py：宽限耗尽（`admin.maintree_stray_wip_grace_minutes`，经 ConfigLoader 点号键读取、缺省 30）时按 core/code_fix.py `_write_defer_orphan_alert` 同型经 AdminStore.append 发一次性 major 告警 `signal_type=maintree_stray_wip_stale`，evidence 含文件清单/first_seen/归因证据/BLIND_SPOT_NOTE，recommended_action 指向人工提交或 stash；同指纹先查后记去重
- [ ] 1.5 core/worktree_manager/stray_wip.py：指纹在后续盘点中不再出现时清除注册表条目（状态复位，不告警不残留）；全程不执行任何 stash/checkout/clean/reset 写操作

## 2. 接线与登记

- [ ] 2.1 fenixd.py + core/pm_engine/engine.py：主循环在既有 `reclaim_stale_autostash_if_idle()` 调用点（fenixd.py:901 附近，60s 节拍块内）旁挂接周期 sweep；接线取 engine 包装方法形态（对齐 engine.py:4478 `reclaim_stale_autostash_if_idle` 先例），由 engine 供在飞 run_ids（run 注册表，供 1.3 归因入参）与 WorktreeManager 句柄（主树锁 + 归因器），sweep 不设 `_active_runs` 空闲预检（须能看到在飞车道做归因），异常捕获留日志、不阻断主循环
- [ ] 2.2 core/admin_monitor.py：三表登记 `maintree_stray_wip_stale`，缺一不可——① SIGNAL_SEVERITY（:251，姊妹条目 :305）→ `major`；② SIGNAL_RECOMMENDATION（:331，姊妹条目 :374）→ 摄取唤起时呈现的处置建议（指向人工提交/stash）；③ STORED_SIGNAL_TYPES（:405，姊妹条目 :431）→ 摄取收录。本告警与姊妹信号 `mergeback_wip_orphan_stuck` 同为「组件直写 AdminStore」形态：漏 ③ 则记录落 store 后无人摄取、Administrator 不唤起（摄取门 admin_monitor.py:2008 只放行收录类型），「告警浮出」目标静默落空

## 3. 测试

- [ ] 3.1 tests/test_maintree_stray_wip_sweep.py：进程内真实 git 仓库夹具覆盖——滞留 tracked 改动宽限耗尽恰发一次告警、重复盘点不重复告警、mtime 被批量重写而内容不变时 first_seen 不归零、在飞车道命中时不计时不告警、改动消失后状态复位、主树锁被占用时本轮放弃、每次盘点/告警前后 `git status --porcelain` 输出逐字节一致（零触碰）、admin_monitor 三表登记完备性断言（SIGNAL_SEVERITY/SIGNAL_RECOMMENDATION/STORED_SIGNAL_TYPES 均含 `maintree_stray_wip_stale`，防摄取门漏登记回归）