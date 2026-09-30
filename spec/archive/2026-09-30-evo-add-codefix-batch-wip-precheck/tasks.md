## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_wip_precheck.py
  kind: new
```

## 1. 选批前 WIP 重叠预检

- [x] 1.1 core/code_fix.py：CodeFixExecutor.checkpoint 在 select_batch 之后、契约守卫与批投递之前插入预检——复用 core/worktree_manager/stash_guard.py 的 _list_dirty_tracked_files 取主树脏 tracked 文件，与候选批条目 file 字段求交，并按 mergeback 的产物判别口径排除 dist 类路径——产物判别器以与 WorktreeManager 同配置源构造（normalize_artifact_patterns(build_artifact_paths) + has_build_artifacts 三态，先例 core/worktree_manager/lifecycle.py:127），禁止硬编码 dist 前缀或无参默认构造
- [x] 1.2 core/code_fix.py：预检命中即整批推迟——写 progress（running=False、phase=blocked、reason=wip_overlap_at_select、附交集文件文案）并返回未触发，不置单飞、不投递批 worker、不耗实现预算，下轮节拍自然重查（写点无条件写，不受既有「选批为空」出口 live 链条件约束，保证可观测）
- [x] 1.3 core/code_fix.py：推迟出口纳入既有「选批为空」reason 分流文案体系，WIP 长期不清理时落入既有 defer/预算降级语义，不产生无限空转

## 2. 测试

- [x] 2.1 tests/test_code_fix_wip_precheck.py：覆盖主树脏文件与候选批重叠时整批推迟且台账条目保持 open、无重叠时选批投递行为与现状一致、交集仅含 dist 产物路径时不误伤三个场景
