## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: tests/test_stray_first_sight_prevention.py
  kind: new
```

## 1. 盘点首现提示

- [ ] 1.1 core/worktree_manager/stray_wip.py：untracked 散件盘点在 below_threshold 早退之前插入首现判定——散件条目按目录型产物集合的规范化根目录归组（顶层散文件不在首现面），对首现登记无目录记录的集合发出一次 info 级首现提示信号（kind=maintree_untracked_stray_first_sight），evidence 携带目录清单、总体积与预防性 .gitignore 条目草案（含成因注释）；ignore 豁免由上游 _untracked_stray_entries 保证，无须重复 check-ignore；信号在 core/admin_monitor.py SIGNAL_SEVERITY + SIGNAL_RECOMMENDATION 两表登记（info 先例 maintree_untracked_stray_stale，admin_monitor.py:359/459）
- [ ] 1.2 core/worktree_manager/stray_wip.py：首现去重键为目录路径（MUST NOT 复用条目集指纹——双层指纹随集合增删/跨档切换漂移，stray_wip.py:773；_reset_untracked_registry_absent({fp}) 只保留当轮指纹，stray_wip.py:794），首现登记以独立目录键结构由既有持久化文件（.fenix/stray_untracked_registry.json）承载、读写与字段适配同步（字段白名单机制见 stray_wip.py:106-112）；同目录不重复提示、集合内容增长不重提示；目录整轮不再贡献散件条目即复位，复位后再现视为新首现；跨 daemon 重启不重复提示
- [ ] 1.3 core/worktree_manager/stray_wip.py：首现提示不启动 24 小时升级时钟、不加入 STORED_SIGNAL_TYPES 自动唤起收录、不改变 info/major 既有阈值与升级判定语义；排除集沿用既有散件判定名单

## 2. 交付侧检查点

- [ ] 2.1 agents/implementer.md：约束段收尾语义区（「全部任务完成后，写文件 .fenix-run-result.json」区块，agents/implementer.md:48 附近）新增 MUST 级检查条目——交付引入运行时落盘路径（日志、dump、产物目录）且落在仓库树内时，同提交追加对应 .gitignore 覆盖或将默认落盘路径移出仓库树，提交前以 git status 自查零 untracked 产物

## 3. 测试

- [ ] 3.1 tests/test_stray_first_sight_prevention.py：覆盖首现提示触发（新目录集合、低于 entry 阈值也提示）、gitignore 已覆盖目录不提示、同目录仅提示一次（含集合内容增长/跨阈值档切换后仍不重提示）、目录整轮不再贡献条目复位后再现重提示、跨 daemon 重启不重复提示
- [ ] 3.2 tests/test_stray_first_sight_prevention.py：钉住非回归——既有 maintree_untracked_stray_stale/escalated 升级路径与阈值语义不变，首现提示不进入自动唤起收录