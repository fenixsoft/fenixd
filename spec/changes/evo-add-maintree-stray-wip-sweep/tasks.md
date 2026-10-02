## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: new
- path: fenixd.py
  kind: modify
- path: core/admin_monitor.py
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
- [ ] 1.2 core/worktree_manager/stray_wip.py：改动集指纹 = 路径排序集 + `git diff` 内容哈希；整个盘点在 worktree_manager 主树锁上非阻塞 acquire（对齐 stash_guard.py `reclaim_stale_autostash` 的锁纪律），锁被占用即放弃本轮
- [ ] 1.3 core/worktree_manager/stray_wip.py：归因复用 core/worktree_manager/types.py 的 `WipOccupantInfo`（在飞实现车道分支改动集求交）：命中则不计时不告警；零命中则按指纹维护 first_seen 注册表，指纹不变沿用原 first_seen（不以 mtime 计时）
- [ ] 1.4 core/worktree_manager/stray_wip.py：宽限耗尽（`admin.maintree_stray_wip_grace_minutes`，经 ConfigLoader 点号键读取、缺省 30）时按 core/code_fix.py `_write_defer_orphan_alert` 同型经 AdminStore.append 发一次性 major 告警 `signal_type=maintree_stray_wip_stale`，evidence 含文件清单/first_seen/归因证据/BLIND_SPOT_NOTE，recommended_action 指向人工提交或 stash；同指纹先查后记去重
- [ ] 1.5 core/worktree_manager/stray_wip.py：指纹在后续盘点中不再出现时清除注册表条目（状态复位，不告警不残留）；全程不执行任何 stash/checkout/clean/reset 写操作

## 2. 接线与登记

- [ ] 2.1 fenixd.py：主循环在既有 `reclaim_stale_autostash_if_idle()` 调用点（fenixd.py:901 附近）旁挂接周期 sweep 调用，异常捕获留日志、不阻断主循环
- [ ] 2.2 core/admin_monitor.py：在 SIGNAL_SEVERITY（core/admin_monitor.py:251）登记 `maintree_stray_wip_stale` → `major`

## 3. 测试

- [ ] 3.1 tests/test_maintree_stray_wip_sweep.py：进程内真实 git 仓库夹具覆盖——滞留 tracked 改动宽限耗尽恰发一次告警、重复盘点不重复告警、mtime 被批量重写而内容不变时 first_seen 不归零、在飞车道命中时不计时不告警、改动消失后状态复位、主树锁被占用时本轮放弃、每次盘点/告警前后 `git status --porcelain` 输出逐字节一致（零触碰）