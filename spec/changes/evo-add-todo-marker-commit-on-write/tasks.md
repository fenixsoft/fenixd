## Deliverables

```yaml
- path: core/evolution.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_evolution_todo_marker_commit.py
  kind: new
- path: spec/knowledge/adr/ADR-060-framework-artifact-commit-points.md
  kind: reference
```

## 1. 写后即时提交

- [ ] 1.1 core/evolution.py：write_todo_marker() 在向 tracked 的 .fenix/todo.md 写入成功后就地执行 git add -- .fenix/todo.md 与 git commit（形态参照 core/self_review.py:1974 _commit_todo）；todo.md 未被 git 跟踪时跳过提交且不报错
- [ ] 1.2 core/evolution.py：accept / reject / delete 三个单点写路径复用同一提交动作；git 提交失败（如 index.lock 竞争）捕获后降级为日志留痕，不向调用方抛错、不回滚写入
- [ ] 1.3 core/agent_runner/maintenance_runs.py：ingest_item 批量落条目的一轮处理改为批末触发一次合并提交，避免一次分析轮产生逐条提交

## 2. 测试

- [ ] 2.1 tests/test_evolution_todo_marker_commit.py：覆盖 tracked 项目写后产生恰一个含 .fenix/todo.md 的提交且工作区对该文件干净、untracked 项目跳过提交、提交失败降级不抛错三个场景