## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: tests/test_stray_tracked_registry_persistence.py
  kind: new
```

## 1. tracked 流注册表落盘

- [ ] 1.1 core/worktree_manager/stray_wip.py：tracked 流 first_seen 注册表同构落盘——复用 untracked 注册表先例（路径常量/字段白名单/加载/原子写 tmp+replace，参照现有 UNTRACKED_REGISTRY_RELPATH(:123)、_PERSISTED_FIELDS(:1925)、_load(:1968)、_persist(:2121) 三件套形态），运行时文件 .fenix/stray_tracked_registry.json，daemon 重启后恢复宽限与升级时钟
- [ ] 1.2 core/worktree_manager/stray_wip.py：同指纹静默窗——24 小时内 diff 字节级零演进的同一指纹不重发 maintree_stray_wip_stale 告警、仅累计度数；指纹演进即正常重告并刷新 first_seen 与静默窗起点
- [ ] 1.3 core/worktree_manager/stray_wip.py：同步改写模块 docstring 与类 docstring 的 D5 注记（:22-33/:511-518），删除「tracked 流维持内存态/损失仅时效」表述并记录推翻依据（两窗 14 次处置 run 约 11.8 美元实测、重启后 4/4 命中 69-71 秒）

## 2. 测试

- [ ] 2.1 tests/test_stray_tracked_registry_persistence.py：覆盖注册表落盘与重启恢复（原子写、字段白名单）、静默窗内同指纹不重告仅累计度数、指纹演进后重告并复位计时、注册表损坏回退内存态不阻塞盘点，装配方式参照现有 test_maintree_stray_wip_sweep.py