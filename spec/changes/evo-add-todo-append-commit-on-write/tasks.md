## Deliverables

```yaml
- path: core/knowledge_backfill.py
  kind: modify
- path: tests/test_knowledge_backfill.py
  kind: modify
```

## 1. 写后就地提交

- [ ] 1.1 core/knowledge_backfill.py：append_todo_line 在实际追加成功（幂等去重未命中、原子回写完成）后执行就地提交——git add -- .fenix/todo.md、带 pathspec 的 git commit -- .fenix/todo.md（信息形如 [fenix] todo: <来源摘要>）、尝试 push；优先函数内延迟导入复用 core/evolution.py 既有提交助手（LC_ALL=C、30s 超时、push 失败降级同款），如循环导入则把助手下沉共享模块后两侧引用。
- [ ] 1.2 core/knowledge_backfill.py：提交动作放在 .fenix/todo.md 的 flock 释放之后执行，git 子命令不进锁内临界区。
- [ ] 1.3 core/knowledge_backfill.py：降级路径——todo.md 未被 git 跟踪（含非 git 仓库）跳过提交不报错；commit 失败经既有日志通道留痕且不向调用方抛错；push 失败降级 WARNING 不重试。

## 2. 测试

- [ ] 2.1 tests/test_knowledge_backfill.py：tracked 夹具仓库中实际追加一行后，git log 出现恰一个仅含 .fenix/todo.md 的提交、工作区对该文件干净，且索引中预置的其他暂存内容不被卷入提交。
- [ ] 2.2 tests/test_knowledge_backfill.py：重复追加已存在行不产生第二次提交；untracked/无 git 夹具下写入成功、无提交、无异常穿透。