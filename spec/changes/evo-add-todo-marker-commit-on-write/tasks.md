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

- [x] 1.1 core/evolution.py：write_todo_marker() 在向 tracked 的 .fenix/todo.md 写入成功后就地执行 git add -- .fenix/todo.md 与同样带 pathspec 限定的 git commit -- .fenix/todo.md（形态参照 core/self_review.py:1974 _commit_todo，commit 不带 pathspec 会卷入索引里并发暂存的 merge-back / 守卫产物），随后 push（失败降级 WARNING）；提交动作实现为独立函数并带开关参数，在 todo.md 的 flock 释放后执行；todo.md 未被 git 跟踪（含 ls-files 非零退出，如目录非 git 仓库）时跳过提交且不报错
- [x] 1.2 core/evolution.py：accept / reject / delete 三个单点写路径（1648/1729/1778）复用同一提交动作（开关缺省开）；ingest_item 内部 4 处调用（1141/1150/1165/1170）传开关关闭，避免批量路径退化为逐条提交；git 提交失败（如 index.lock 竞争）捕获后降级为日志留痕，不向调用方抛错、不回滚写入
- [x] 1.3 core/agent_runner/maintenance_runs.py：ingest_item 批量落条目的一轮处理改为批末对本轮涉及的项目集合按项目各触发一次合并提交（write_todo_marker 按条目 project 名经 registry 解析目标项目，一轮可涉及多个项目），避免一次分析轮产生逐条提交

## 2. 测试

- [x] 2.1 tests/test_evolution_todo_marker_commit.py：覆盖 tracked 项目写后产生恰一个含 .fenix/todo.md 的提交且工作区对该文件干净、untracked 项目跳过提交、提交失败降级不抛错三个场景

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/evo-add-todo-marker-commit-on-write/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
