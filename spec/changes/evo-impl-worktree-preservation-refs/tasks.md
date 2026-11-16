## Deliverables

```yaml
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: core/worktree_manager/stale_sweep.py
  kind: modify
- path: tests/test_impl_delivery_preservation.py
  kind: new
```

## 1. 快照真引用

- [ ] 1.1 core/worktree_manager/lifecycle.py：`_snapshot_dirty_worktree`（约 :1170）在生成快照 commit 后写入主 gitdir 共享引用 refs/preservation/<run_id>（update-ref 幂等），失败回退现状行为并升 ERROR；恢复指引文案（约 :1298-1305）改为引用名形态

## 2. 引用生命周期

- [ ] 2.1 core/worktree_manager/stale_sweep.py：删除终态 impl 分支前校验对应 preservation 引用就位；spec 终态消费后的宽限期清扫删除对应引用；冻结待人工裁决在途时跳过删除

## 3. 测试

- [ ] 3.1 tests/test_impl_delivery_preservation.py：覆盖「清扫后 refs/preservation/<run_id> 存在且交付链 for-each-ref --contains 可达」「update-ref 失败回退并 ERROR」「冻结在途不删引用」「终态消费后清理引用」四场景