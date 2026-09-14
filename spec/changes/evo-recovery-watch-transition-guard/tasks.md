# 任务

## Deliverables

```yaml
- path: core/pm_engine/recovery.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: tests/test_recovery_watch_transition_guard.py
  kind: new
```

## 1. 过渡窗口豁免

- [ ] 1.1 core/pm_engine/recovery.py check_recovery_watch：判定 stale 前检查待合并分支（pending merge），存在则跳过/顺延本次判定（design D1）

- [ ] 1.2 implementer succeed 信号到达时重置/顺延该 spec 的 recovery watch 计时器（recovery.py 登记侧，design D2 兜底）

- [ ] 1.3 core/pm_engine/engine.py 假就绪巡检（BLOCKER CHECK）：同源豁免（待合并分支或 succeed 缓冲窗口）

## 2. 支撑

- [ ] 2.1 core/worktree_manager.py：暴露该 spec 待合并分支查询（若尚不存在，沿用 has_active_worktree 同风格；原草稿误写 core/agent_runner/worktree_manager.py，该目录下无此文件，已订正）。

## 3. 测试

- [ ] 3.1 tests/test_recovery_watch_transition_guard.py：过渡窗口复查不误报 dispatch_stalled（成功-合并窗口场景）

- [ ] 3.2 真实 stale 仍升级 dispatch_stalled（回归断言）
