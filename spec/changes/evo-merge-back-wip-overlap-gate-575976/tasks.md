## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: tests/test_worktree_merge_guard.py
  kind: modify
```

## 1. 落地校验

- [ ] 1.1 core/worktree_manager.py：merge-back 前 WIP 重叠命中（_detect_wip_overlap 非空）时默认阻塞——不进入 stash→merge→pop，产出 mergeback_wip_overlap major 告警（含重叠文件清单与 git stash show 找回命令），等待人工确认；配置 worktree.mergeback_auto_stash_overlap=true 时改为自动收纳（重叠改动并入带 AUTOSTASH_MSG_PREFIX 标记的 stash 条目并标记待回收）后继续 merge
- [ ] 1.2 core/worktree_manager.py：pop 冲突自愈路径保留，被丢弃文件逐文件列出并核对是否含必要改动；无重叠/主树干净路径行为不变
- [ ] 1.3 core/pm_engine/dispatch.py：mergeback_wip_overlap 告警组装经 _str_field 序列化兜底（evidence/context 为 dict 时不崩），文案含重叠清单与处置指引

## 2. 测试

- [ ] 2.1 tests/test_worktree_merge_guard.py：新增用例——主树脏 tracked 与分支重叠时 merge-back 被阻塞且产生 mergeback_wip_overlap 告警、主树保持可写、无文件被丢弃
- [ ] 2.2 tests/test_worktree_merge_guard.py：新增用例——auto_stash_overlap=true 时重叠改动被收纳并成功 merge，未提交内容可在 stash 中找到
- [ ] 2.3 tests/test_worktree_merge_guard.py：新增用例——不重叠时 merge-back 行为与既有用例逐字节一致（回归无破坏）