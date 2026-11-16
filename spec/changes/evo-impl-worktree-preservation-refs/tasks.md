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

- [ ] 1.1 core/worktree_manager/lifecycle.py：`_snapshot_dirty_worktree`（:1203）在生成快照 commit 后写入主 gitdir 共享引用 refs/preservation/<run_id>（run_id 取 impl 分支名去 `fenix/` 前缀，含 spec+时间戳；update-ref 幂等），失败回退现状行为并升 ERROR；恢复指引文案（:1336-1338）改为引用名形态；快照 commit MUST 含 untracked 文件（临时 index 构树等价方式，blob 日志留档保留为冗余）；worktree clean（`status --porcelain` 为空，:1237 skip 返回空 SHA）时改以 impl 分支 tip 写该引用

## 2. 引用生命周期

- [ ] 2.1 core/worktree_manager/stale_sweep.py：删除终态 impl 分支前校验对应 preservation 引用就位（就位口径 = 引用 --contains 分支 tip）；spec 终态消费后的宽限期清扫删除对应引用；冻结待人工裁决在途时跳过删除（与既有分支 GC 守卫链 :214-227 合并判定，不另起炉灶）

## 3. 测试

- [ ] 3.1 tests/test_impl_delivery_preservation.py：覆盖「清扫后 refs/preservation/<run_id> 存在且交付链 for-each-ref --contains 可达」「update-ref 失败回退并 ERROR」「冻结在途不删引用」「终态消费后清理引用」「untracked 文件经引用链检出」「clean worktree 引用指向分支 tip、分支删除后链可达」六场景