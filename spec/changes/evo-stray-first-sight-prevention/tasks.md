## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: tests/test_stray_first_sight_prevention.py
  kind: new
```

## 1. 盘点首现提示

- [ ] 1.1 core/worktree_manager/stray_wip.py：untracked 散件盘点在 below_threshold 早退之前插入首现判定——对登记表无 first_seen 记录、路径未被 .gitignore 覆盖的目录型产物集合，发出一次 info 级首现提示信号（kind=maintree_untracked_stray_first_sight），evidence 携带目录清单、总体积与预防性 .gitignore 条目草案（含成因注释）
- [ ] 1.2 core/worktree_manager/stray_wip.py：首现即写既有持久化登记表（first_seen/指纹），同目录不重复提示；目录消失走既有复位逻辑，复位后再现视为新首现；跨 daemon 重启不重复提示
- [ ] 1.3 core/worktree_manager/stray_wip.py：首现提示不启动 24 小时升级时钟、不加入 STORED_SIGNAL_TYPES 自动唤起收录、不改变 info/major 既有阈值与升级判定语义；排除集沿用既有散件判定名单

## 2. 交付侧检查点

- [ ] 2.1 agents/implementer.md：收尾检查清单新增 MUST 级条目——交付引入运行时落盘路径（日志、dump、产物目录）且落在仓库树内时，同提交追加对应 .gitignore 覆盖或将默认落盘路径移出仓库树，提交前以 git status 自查零 untracked 产物

## 3. 测试

- [ ] 3.1 tests/test_stray_first_sight_prevention.py：覆盖首现提示触发（新目录集合、低于 entry 阈值也提示）、gitignore 已覆盖目录不提示、同目录仅提示一次、目录消失复位后再现重提示、跨 daemon 重启不重复提示
- [ ] 3.2 tests/test_stray_first_sight_prevention.py：钉住非回归——既有 maintree_untracked_stray_stale/escalated 升级路径与阈值语义不变，首现提示不进入自动唤起收录